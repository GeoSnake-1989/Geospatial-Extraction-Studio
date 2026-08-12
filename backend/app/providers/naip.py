from __future__ import annotations

import asyncio
import json
import math
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds
from shapely.geometry import box, shape
from shapely.ops import unary_union

from ..config import (
    NAIP_MAX_OUTPUT_PIXELS,
    NAIP_SIGN_URL,
    NAIP_STAC_COLLECTION_URL,
    NAIP_STAC_SEARCH_URL,
)
from ..models import BoundingBox, NAIPBands, NAIPSelectionMode


class NAIPProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class NAIPItem:
    id: str
    year: int
    acquisition_datetime: str
    gsd_m: float
    epsg: int
    href: str
    bbox: tuple[float, float, float, float]
    geometry: dict[str, Any] | None
    stac_license: str | None = None
    stac_providers: tuple[dict[str, Any], ...] = ()
    asset_metadata: dict[str, Any] | None = None
    stac_item_url: str | None = None
    stac_license_links: tuple[dict[str, str], ...] = ()

    @classmethod
    def from_feature(cls, feature: dict[str, Any]) -> "NAIPItem":
        properties = feature.get("properties") or {}
        asset = (feature.get("assets") or {}).get("image") or {}
        raw_bbox = feature.get("bbox") or []
        raw_datetime = str(properties.get("datetime") or "")
        raw_year = properties.get("naip:year") or raw_datetime[:4]
        epsg = properties.get("proj:epsg")
        raw_providers = feature.get("providers") or []
        providers = tuple(
            dict(provider)
            for provider in raw_providers
            if isinstance(provider, dict)
        )
        raw_links = feature.get("links") or []
        stac_item_url = next(
            (
                str(link["href"])
                for link in raw_links
                if isinstance(link, dict)
                and link.get("rel") == "self"
                and link.get("href")
            ),
            None,
        )
        stac_license_links = tuple(
            {
                key: str(link[key])
                for key in ("href", "title", "type")
                if link.get(key)
            }
            for link in raw_links
            if isinstance(link, dict)
            and link.get("rel") == "license"
            and link.get("href")
        )
        raw_license = feature.get("license") or properties.get("license")
        stac_license = str(raw_license) if raw_license else None
        asset_metadata = {
            key: asset[key]
            for key in ("title", "description", "type", "roles", "license", "attribution")
            if key in asset
        }
        if len(raw_bbox) < 4 or not asset.get("href") or not epsg or not raw_year:
            raise NAIPProviderError("The NAIP catalog returned an item with incomplete spatial metadata")
        return cls(
            id=str(feature["id"]),
            year=int(raw_year),
            acquisition_datetime=raw_datetime,
            gsd_m=float(properties.get("gsd") or 1.0),
            epsg=int(epsg),
            href=str(asset["href"]),
            bbox=tuple(float(value) for value in raw_bbox[:4]),
            geometry=feature.get("geometry"),
            stac_license=stac_license,
            stac_providers=providers,
            asset_metadata=asset_metadata,
            stac_item_url=stac_item_url,
            stac_license_links=stac_license_links,
        )

    def footprint(self):
        try:
            return shape(self.geometry) if self.geometry else box(*self.bbox)
        except Exception:
            return box(*self.bbox)


class NAIPProvider:
    provider_name = "USDA NAIP via Microsoft Planetary Computer"
    product_name = "NAIP AOI GeoTIFF mosaic"
    attribution = "NAIP imagery provided by USDA Farm Service Agency"
    non_spdx_license_values = {"other", "proprietary", "various"}
    license_note = (
        "Asset-level STAC license metadata takes precedence over item metadata only "
        "when the declarations do not conflict; item metadata otherwise takes precedence "
        "over collection metadata. Legacy non-SPDX asset or item values require a "
        "same-record license link. Conflicts or missing terms disable extraction."
    )

    def __init__(
        self,
        search_url: str = NAIP_STAC_SEARCH_URL,
        collection_url: str = NAIP_STAC_COLLECTION_URL,
        sign_url: str = NAIP_SIGN_URL,
        max_output_pixels: int = NAIP_MAX_OUTPUT_PIXELS,
    ) -> None:
        self.search_url = search_url
        self.collection_url = collection_url
        self.sign_url = sign_url
        self.max_output_pixels = max_output_pixels
        self.collection_metadata: dict[str, Any] = {}

    @staticmethod
    def collection_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
        license_links = [
            {
                key: link[key]
                for key in ("href", "title", "type")
                if link.get(key)
            }
            for link in payload.get("links") or []
            if isinstance(link, dict) and link.get("rel") == "license" and link.get("href")
        ]
        providers = [
            dict(provider)
            for provider in payload.get("providers") or []
            if isinstance(provider, dict)
        ]
        return {
            "id": str(payload.get("id") or "naip"),
            "title": payload.get("title"),
            "license": payload.get("license"),
            "license_links": license_links,
            "providers": providers,
            "source_url": next(
                (
                    str(link["href"])
                    for link in payload.get("links") or []
                    if isinstance(link, dict)
                    and link.get("rel") == "self"
                    and link.get("href")
                ),
                None,
            ),
        }

    @classmethod
    def validate_collection_license_metadata(cls, metadata: dict[str, Any]) -> None:
        declaration = str(metadata.get("license") or "").strip()
        license_links = metadata.get("license_links") or []
        if not declaration and not license_links:
            raise ValueError("collection response does not declare or link a license")
        if declaration.lower() in cls.non_spdx_license_values and not license_links:
            raise ValueError(
                f"collection license '{declaration}' requires a linked license text"
            )

    def effective_item_license(
        self,
        item: NAIPItem,
    ) -> tuple[str, str, tuple[dict[str, str], ...]]:
        asset_license = str((item.asset_metadata or {}).get("license") or "").strip()
        item_license = str(item.stac_license or "").strip()
        if asset_license and item_license and asset_license.casefold() != item_license.casefold():
            raise NAIPProviderError(
                f"NAIP item {item.id} has conflicting asset and item license declarations "
                f"('{asset_license}' and '{item_license}'); extraction is disabled until "
                "the source record is reviewed"
            )
        if asset_license:
            return asset_license, "asset", item.stac_license_links
        if item_license:
            return item_license, "item", item.stac_license_links
        collection_license = str(self.collection_metadata.get("license") or "").strip()
        collection_links = tuple(self.collection_metadata.get("license_links") or ())
        return collection_license, "collection", collection_links

    def validate_selected_item_licenses(self, items: list[NAIPItem]) -> None:
        try:
            self.validate_collection_license_metadata(self.collection_metadata)
        except ValueError as exc:
            raise NAIPProviderError(
                "The NAIP collection license metadata is not valid for redistribution: "
                f"{exc}"
            ) from exc
        for item in items:
            declaration, level, license_links = self.effective_item_license(item)
            if not declaration and not license_links:
                raise NAIPProviderError(
                    f"NAIP item {item.id} has no effective license declaration or link; "
                    "extraction is disabled until its redistribution terms can be verified"
                )
            if declaration.casefold() in self.non_spdx_license_values and not license_links:
                raise NAIPProviderError(
                    f"NAIP item {item.id} has {level}-level license '{declaration}' without "
                    "a same-record linked license text; extraction is disabled until its "
                    "redistribution terms can be verified"
                )

    async def _load_collection_metadata(self, client: httpx.AsyncClient) -> None:
        try:
            response = await client.get(self.collection_url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("collection response is not an object")
            metadata = self.collection_metadata_from_payload(payload)
            self.validate_collection_license_metadata(metadata)
            self.collection_metadata = metadata
        except (httpx.HTTPError, ValueError) as exc:
            raise NAIPProviderError(
                "The NAIP collection license metadata is unavailable; extraction is disabled "
                f"until its redistribution terms can be verified: {exc}"
            ) from exc

    async def search(self, bounds: BoundingBox) -> list[NAIPItem]:
        params: dict[str, str | int] | None = {
            "collections": "naip",
            "bbox": bounds.as_arcgis_bbox(),
            "limit": 500,
        }
        url: str | None = self.search_url
        features: list[dict[str, Any]] = []
        headers = {"User-Agent": "GeospatialExtractionStudio/0.4 (local NAIP extractor)"}
        async with httpx.AsyncClient(timeout=45, headers=headers, follow_redirects=True) as client:
            await self._load_collection_metadata(client)
            while url and len(features) < 5_000:
                try:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    payload = response.json()
                except (httpx.HTTPError, ValueError) as exc:
                    raise NAIPProviderError(f"The NAIP catalog is unavailable: {exc}") from exc
                features.extend(payload.get("features") or [])
                next_link = next(
                    (link for link in payload.get("links") or [] if link.get("rel") == "next"),
                    None,
                )
                url = str(next_link["href"]) if next_link and next_link.get("href") else None
                params = None
        items: list[NAIPItem] = []
        for feature in features:
            try:
                items.append(NAIPItem.from_feature(feature))
            except (KeyError, TypeError, ValueError, NAIPProviderError):
                continue
        if not items:
            raise NAIPProviderError("No published NAIP imagery intersects the selected location")
        return sorted(items, key=lambda item: (item.acquisition_datetime, item.id), reverse=True)

    @staticmethod
    def coverage(bounds: BoundingBox, items: list[NAIPItem]) -> float:
        aoi = box(bounds.west, bounds.south, bounds.east, bounds.north)
        intersections = [item.footprint().intersection(aoi) for item in items]
        intersections = [geometry for geometry in intersections if not geometry.is_empty]
        if not intersections or aoi.area <= 0:
            return 0.0
        return min(1.0, unary_union(intersections).area / aoi.area)

    def summarize(self, bounds: BoundingBox, items: list[NAIPItem]) -> dict[str, Any]:
        by_year: dict[int, list[NAIPItem]] = {}
        for item in items:
            by_year.setdefault(item.year, []).append(item)
        years: list[dict[str, Any]] = []
        latest_complete_year: int | None = None
        for year in sorted(by_year, reverse=True):
            year_items = by_year[year]
            coverage = self.coverage(bounds, year_items)
            if latest_complete_year is None and coverage >= 0.995:
                latest_complete_year = year
            dates = sorted(item.acquisition_datetime for item in year_items if item.acquisition_datetime)
            gsd = min(item.gsd_m for item in year_items)
            years.append(
                {
                    "year": year,
                    "coverage_percent": round(coverage * 100, 1),
                    "fully_covered": coverage >= 0.995,
                    "tile_count": len(year_items),
                    "gsd_m": gsd,
                    "acquisition_start": dates[0] if dates else None,
                    "acquisition_end": dates[-1] if dates else None,
                    "estimated_pixels": round(bounds.area_km2() * 1_000_000 / (gsd * gsd)),
                }
            )
        latest_items = self.select_items(bounds, items, NAIPSelectionMode.latest_per_tile, None)
        self.validate_selected_item_licenses(latest_items)
        latest_dates = sorted(item.acquisition_datetime for item in latest_items if item.acquisition_datetime)
        latest_gsd = min(item.gsd_m for item in latest_items)
        return {
            "provider": self.provider_name,
            "catalog": "Microsoft Planetary Computer STAC collection naip",
            "collection": self.collection_metadata,
            "attribution": self.attribution,
            "license_note": self.license_note,
            "source_license_summary": self.source_license_summary(latest_items),
            "latest_complete_year": latest_complete_year,
            "latest_acquisition_date": latest_dates[-1] if latest_dates else None,
            "latest_per_tile_years": sorted({item.year for item in latest_items}, reverse=True),
            "latest_per_tile_coverage_percent": round(self.coverage(bounds, latest_items) * 100, 1),
            "latest_per_tile_gsd_m": latest_gsd,
            "latest_per_tile_estimated_pixels": round(
                bounds.area_km2() * 1_000_000 / (latest_gsd * latest_gsd)
            ),
            "max_output_pixels": self.max_output_pixels,
            "years": years,
        }

    def select_items(
        self,
        bounds: BoundingBox,
        items: list[NAIPItem],
        mode: NAIPSelectionMode,
        year: int | None,
    ) -> list[NAIPItem]:
        aoi = box(bounds.west, bounds.south, bounds.east, bounds.north)
        if mode == NAIPSelectionMode.year:
            selected = [item for item in items if item.year == year and item.footprint().intersects(aoi)]
            if not selected:
                raise NAIPProviderError(f"NAIP imagery for {year} does not intersect the selected location")
            if self.coverage(bounds, selected) < 0.995:
                raise NAIPProviderError(f"NAIP {year} does not completely cover the selected location")
            return selected

        if mode == NAIPSelectionMode.latest_complete:
            for candidate_year in sorted({item.year for item in items}, reverse=True):
                selected = [item for item in items if item.year == candidate_year]
                if self.coverage(bounds, selected) >= 0.995:
                    return selected
            raise NAIPProviderError("No single NAIP acquisition year completely covers the selected location")

        remaining = aoi
        selected = []
        for item in sorted(items, key=lambda value: (value.acquisition_datetime, value.id), reverse=True):
            contribution = item.footprint().intersection(remaining)
            if contribution.is_empty or contribution.area <= aoi.area * 1e-10:
                continue
            selected.append(item)
            remaining = remaining.difference(item.footprint())
            if remaining.is_empty or remaining.area / aoi.area <= 0.005:
                break
        if self.coverage(bounds, selected) < 0.995:
            raise NAIPProviderError("Published NAIP imagery does not completely cover the selected location")
        return selected

    async def _sign_items(self, items: list[NAIPItem]) -> list[str]:
        headers = {"User-Agent": "GeospatialExtractionStudio/0.4 (local NAIP extractor)"}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            async def sign_item(item: NAIPItem) -> str:
                try:
                    response = await client.get(self.sign_url, params={"href": item.href})
                    response.raise_for_status()
                    return str(response.json()["href"])
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    raise NAIPProviderError(f"Could not authorize access to NAIP tile {item.id}: {exc}") from exc

            return list(await asyncio.gather(*(sign_item(item) for item in items)))

    def _write_mosaic(
        self,
        bounds: BoundingBox,
        items: list[NAIPItem],
        signed_urls: list[str],
        bands: NAIPBands,
        selection_mode: NAIPSelectionMode,
        output_path: Path,
    ) -> dict[str, Any]:
        target_epsg = items[0].epsg
        target_crs = f"EPSG:{target_epsg}"
        resolution = min(item.gsd_m for item in items)
        target_bounds = transform_bounds(
            "EPSG:4326",
            target_crs,
            bounds.west,
            bounds.south,
            bounds.east,
            bounds.north,
            densify_pts=21,
        )
        width = math.ceil((target_bounds[2] - target_bounds[0]) / resolution)
        height = math.ceil((target_bounds[3] - target_bounds[1]) / resolution)
        pixel_count = width * height
        if pixel_count > self.max_output_pixels:
            raise NAIPProviderError(
                f"The requested native-resolution mosaic is approximately {pixel_count:,} pixels; "
                f"reduce the area below the {self.max_output_pixels:,}-pixel safety limit"
            )
        indexes = [1, 2, 3] if bands == NAIPBands.rgb else [1, 2, 3, 4]
        datasets: list[Any] = []
        sources: list[Any] = []
        output_path.parent.mkdir(parents=True, exist_ok=True)
        env_options = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "GDAL_HTTP_MULTIRANGE": "YES",
            "VSI_CACHE": "TRUE",
            "VSI_CACHE_SIZE": 16_777_216,
        }
        try:
            with rasterio.Env(**env_options):
                for item, url in zip(items, signed_urls, strict=True):
                    dataset = rasterio.open(url)
                    datasets.append(dataset)
                    if dataset.count < len(indexes):
                        raise NAIPProviderError(f"NAIP tile {item.id} does not contain the requested bands")
                    if dataset.crs and dataset.crs.to_epsg() != target_epsg:
                        vrt = WarpedVRT(dataset, crs=target_crs, resampling=Resampling.bilinear)
                        sources.append(vrt)
                    else:
                        sources.append(dataset)
                merge(
                    sources,
                    bounds=target_bounds,
                    res=resolution,
                    nodata=0,
                    dtype="uint8",
                    indexes=indexes,
                    output_count=len(indexes),
                    resampling=Resampling.bilinear,
                    method="first",
                    target_aligned_pixels=True,
                    mem_limit=96,
                    dst_path=output_path,
                    dst_kwds={
                        "driver": "GTiff",
                        "compress": "DEFLATE",
                        "predictor": 2,
                        "tiled": True,
                        "blockxsize": 512,
                        "blockysize": 512,
                        "BIGTIFF": "IF_SAFER",
                    },
                )
        except NAIPProviderError:
            raise
        except Exception as exc:
            raise NAIPProviderError(f"Could not build the NAIP GeoTIFF mosaic: {exc}") from exc
        finally:
            for source in reversed(sources):
                if isinstance(source, WarpedVRT):
                    source.close()
            for dataset in reversed(datasets):
                dataset.close()

        with rasterio.open(output_path, "r+") as dataset:
            descriptions = ["Red", "Green", "Blue"] + (["Near infrared"] if len(indexes) == 4 else [])
            dataset.descriptions = tuple(descriptions)
            dataset.update_tags(
                provider=self.provider_name,
                product=self.product_name,
                attribution=self.attribution,
                source_license_summary=self.source_license_summary(items),
                collection_license=str(self.collection_metadata.get("license") or "Not declared"),
                collection_license_url=str(
                    (self.collection_metadata.get("license_links") or [{}])[0].get("href")
                    or "Not declared"
                ),
                license_note=self.license_note,
                selection_mode=selection_mode.value,
                acquisition_years=",".join(str(value) for value in sorted({item.year for item in items})),
            )
            factors = [factor for factor in (2, 4, 8, 16, 32) if min(dataset.width, dataset.height) // factor >= 64]
            if factors:
                dataset.build_overviews(factors, Resampling.average)
                dataset.update_tags(ns="rio_overview", resampling="average")
            return {
                "crs": dataset.crs.to_string() if dataset.crs else "Not declared",
                "width": dataset.width,
                "height": dataset.height,
                "pixel_count": dataset.width * dataset.height,
                "band_count": dataset.count,
                "resolution_m": resolution,
                "nodata": dataset.nodata,
            }

    @staticmethod
    def _png_chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    def _write_preview(self, imagery_path: Path, preview_path: Path) -> dict[str, int]:
        with rasterio.open(imagery_path) as dataset:
            scale = min(1.0, 1024 / max(dataset.width, dataset.height))
            width = max(1, round(dataset.width * scale))
            height = max(1, round(dataset.height * scale))
            rgb = dataset.read(
                [1, 2, 3],
                out_shape=(3, height, width),
                resampling=Resampling.bilinear,
            )
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        rows = b"".join(b"\x00" + np.moveaxis(rgb, 0, 2)[row].tobytes() for row in range(height))
        png = b"\x89PNG\r\n\x1a\n"
        png += self._png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        png += self._png_chunk(b"IDAT", zlib.compress(rows, 6))
        png += self._png_chunk(b"IEND", b"")
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_bytes(png)
        return {"width": width, "height": height}

    async def availability(self, bounds: BoundingBox) -> dict[str, Any]:
        return self.summarize(bounds, await self.search(bounds))

    async def extract(
        self,
        bounds: BoundingBox,
        selection_mode: NAIPSelectionMode,
        year: int | None,
        bands: NAIPBands,
        manifest_path: Path,
        output_path: Path,
        preview_path: Path,
    ) -> dict[str, Any]:
        items = await self.search(bounds)
        selected = self.select_items(bounds, items, selection_mode, year)
        self.validate_selected_item_licenses(selected)
        signed_urls = await self._sign_items(selected)
        spatial = await asyncio.to_thread(
            self._write_mosaic,
            bounds,
            selected,
            signed_urls,
            bands,
            selection_mode,
            output_path,
        )
        preview = await asyncio.to_thread(self._write_preview, output_path, preview_path)
        dates = sorted(item.acquisition_datetime for item in selected if item.acquisition_datetime)
        years = sorted({item.year for item in selected}, reverse=True)
        manifest = {
            "provider": self.provider_name,
            "catalog": "Microsoft Planetary Computer STAC collection naip",
            "collection": self.collection_metadata,
            "attribution": self.attribution,
            "license_note": self.license_note,
            "source_license_summary": self.source_license_summary(selected),
            "selection_mode": selection_mode.value,
            "requested_year": year,
            "bounds_wgs84": bounds.model_dump(),
            "items": [
                {
                    "id": item.id,
                    "year": item.year,
                    "acquisition_datetime": item.acquisition_datetime,
                    "gsd_m": item.gsd_m,
                    "epsg": item.epsg,
                    "source_href": item.href,
                    "stac_item_url": item.stac_item_url,
                    "license": item.stac_license,
                    "license_links": list(item.stac_license_links),
                    "providers": list(item.stac_providers),
                    "asset_metadata": item.asset_metadata or {},
                }
                for item in selected
            ],
        }
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {
            "provider": self.provider_name,
            "product": self.product_name,
            "attribution": self.attribution,
            "license_note": self.license_note,
            "source_license_summary": self.source_license_summary(selected),
            "years": years,
            "acquisition_start": dates[0] if dates else None,
            "acquisition_end": dates[-1] if dates else None,
            "tile_count": len(selected),
            "coverage_percent": round(self.coverage(bounds, selected) * 100, 1),
            "spatial": spatial,
            "preview": preview,
        }

    def source_license_summary(self, items: list[NAIPItem]) -> str:
        source_licenses: set[str] = set()
        for item in items:
            declaration = str(
                (item.asset_metadata or {}).get("license") or item.stac_license or ""
            ).strip()
            if not declaration:
                continue
            if (
                declaration.casefold() in self.non_spdx_license_values
                and item.stac_license_links
            ):
                links = "; ".join(
                    f"{str(link.get('title') or 'linked license')}: {link['href']}"
                    for link in item.stac_license_links
                )
                source_licenses.add(f"{declaration} (linked terms: {links})")
            else:
                source_licenses.add(declaration)
        if source_licenses:
            return "Source asset/item declarations: " + "; ".join(sorted(source_licenses))

        collection_license = self.collection_metadata.get("license")
        license_links = self.collection_metadata.get("license_links") or []
        if (
            collection_license
            and str(collection_license).lower() in self.non_spdx_license_values
            and license_links
        ):
            linked_terms = "; ".join(
                f"{str(link.get('title') or 'linked license')}: {link['href']}"
                for link in license_links
            )
            return (
                f"Linked license terms: {linked_terms} "
                f"(catalog uses legacy STAC '{collection_license}' for non-SPDX terms)"
            )
        parts = []
        if collection_license:
            parts.append(f"collection declaration: {collection_license}")
        for link in license_links:
            label = str(link.get("title") or "linked license")
            parts.append(f"{label}: {link['href']}")
        return "; ".join(parts) if parts else "Not declared by source STAC assets, items, or collection"
