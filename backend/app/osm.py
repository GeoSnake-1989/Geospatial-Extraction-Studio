from __future__ import annotations

import json
import logging
import shutil
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import osmnx as ox
import pyogrio
import requests
from pyproj import Geod
from shapely.geometry import MultiPolygon, Polygon, shape

from .config import OSM_CACHE_DIR, OSM_OVERPASS_URLS, OSM_USER_AGENT
from .models import BoundingBox


logger = logging.getLogger(__name__)

OSM_COPYRIGHT_URL = "https://www.openstreetmap.org/copyright"
ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"
OVERPASS_REQUEST_TIMEOUT = 180
HEAVY_FEATURE_MAX_QUERY_AREA_SIZE = 25_000_000
HEAVY_FEATURE_TYPES = {"route"}
MAX_OSM_BOUNDARY_AREA_KM2 = 10_000
MAX_MAP_PREVIEW_FEATURES = 2_000
GEODATABASE_RESERVED_FIELD_NAMES = {"objectid"}
GEODATABASE_MAX_FIELD_NAME_LENGTH = 64
OSM_OUTPUT_FORMATS: dict[str, dict[str, Any]] = {
    "openfilegdb": {
        "driver": "OpenFileGDB",
        "extension": ".gdb",
        "display_name": "OpenFileGDB",
        "layer_options": {"TARGET_ARCGIS_VERSION": "ARCGIS_PRO_3_2_OR_LATER"},
    },
    "geopackage": {
        "driver": "GPKG",
        "extension": ".gpkg",
        "display_name": "GeoPackage",
        "layer_options": {"FID": "OBJECTID"},
    },
}

# OSMnx stores service configuration globally, so downloads are serialized.
_OSMNX_LOCK = threading.Lock()


class OSMExtractionError(RuntimeError):
    pass


def configure_osmnx() -> None:
    OSM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ox.settings.http_user_agent = OSM_USER_AGENT
    ox.settings.http_referer = OSM_USER_AGENT
    ox.settings.use_cache = True
    ox.settings.cache_folder = OSM_CACHE_DIR


configure_osmnx()


def _sanitize_name(value: str, max_length: int = 60) -> str:
    sanitized = "".join(
        character if character.isalnum() or character == "_" else "_"
        for character in value.strip()
    )
    return "_".join(part for part in sanitized.split("_") if part)[:max_length]


def _unique_field_name(
    base_name: str,
    used_names: set[str],
    max_length: int | None = None,
) -> str:
    candidate = base_name[:max_length] if max_length is not None else base_name
    suffix = 1
    while candidate.lower() in used_names:
        suffix_text = f"_{suffix}"
        candidate = (
            f"{base_name[:max_length - len(suffix_text)]}{suffix_text}"
            if max_length is not None
            else f"{base_name}{suffix_text}"
        )
        suffix += 1
    return candidate


def _rename_reserved_fields(gdf):
    """Apply OpenFileGDB-compatible field names before writing either format."""
    geometry_column = gdf.geometry.name
    used_names: set[str] = set()
    rename_map = {}
    for column in gdf.columns:
        if column == geometry_column:
            continue
        original_name = str(column)
        base_name = (
            f"osm_{original_name}".lower()
            if original_name.lower() in GEODATABASE_RESERVED_FIELD_NAMES
            else original_name
        )
        base_name = "".join(
            character if character.isascii() and (character.isalnum() or character == "_") else "_"
            for character in base_name
        )
        if base_name and base_name[0].isdigit():
            base_name = f"_{base_name}"
        base_name = base_name or "_"
        new_name = _unique_field_name(
            base_name,
            used_names,
            max_length=GEODATABASE_MAX_FIELD_NAME_LENGTH,
        )
        if new_name != original_name:
            rename_map[column] = new_name
        used_names.add(new_name.lower())
    return gdf.rename(columns=rename_map) if rename_map else gdf


def _call_with_cache_recovery(operation, *args):
    try:
        return operation(*args)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring an unreadable OSM cache entry and retrying: %s", exc)
        original_use_cache = ox.settings.use_cache
        try:
            ox.settings.use_cache = False
            return operation(*args)
        finally:
            ox.settings.use_cache = original_use_cache


def _validated_boundary(boundary: dict[str, Any]) -> tuple[Polygon | MultiPolygon, float]:
    try:
        geometry = shape(boundary)
    except (TypeError, ValueError) as exc:
        raise OSMExtractionError(f"The selected place boundary is invalid: {exc}") from exc
    if not isinstance(geometry, (Polygon, MultiPolygon)) or geometry.is_empty:
        raise OSMExtractionError("The selected place boundary must be a non-empty polygon")
    if not geometry.is_valid:
        raise OSMExtractionError("The selected place boundary contains invalid polygon geometry")
    west, south, east, north = geometry.bounds
    if west < -180 or east > 180 or south < -90 or north > 90:
        raise OSMExtractionError("The selected place boundary contains coordinates outside EPSG:4326")
    geod = Geod(ellps="WGS84")
    area_m2, _ = geod.geometry_area_perimeter(geometry)
    return geometry, abs(float(area_m2)) / 1_000_000


def boundary_area_km2(boundary: dict[str, Any]) -> float:
    """Return the geodesic area of a validated GeoJSON place boundary."""
    _, area = _validated_boundary(boundary)
    return area


def build_osm_map_preview(
    geodatabase: Path,
    feature_classes: list[str],
    max_features: int = MAX_MAP_PREVIEW_FEATURES,
) -> dict[str, Any]:
    """Read a browser-sized, EPSG:4326 GeoJSON preview from an OGR dataset."""
    if max_features < 1:
        raise ValueError("Map preview feature limit must be at least one")
    if not geodatabase.exists():
        raise OSMExtractionError("The OSM dataset is missing")

    available_layers = {str(layer[0]): str(layer[1]) for layer in pyogrio.list_layers(geodatabase)}
    requested_layers = [name for name in feature_classes if name in available_layers]
    layer_info: list[dict[str, Any]] = []
    for layer_name in requested_layers:
        info = pyogrio.read_info(geodatabase, layer=layer_name)
        layer_info.append(
            {
                "name": layer_name,
                "geometry_type": available_layers[layer_name],
                "feature_count": int(info["features"]),
            }
        )

    features: list[dict[str, Any]] = []
    remaining = max_features
    remaining_layers = len(layer_info)
    for item in layer_info:
        quota = max(1, remaining // remaining_layers) if remaining else 0
        displayed_count = min(item["feature_count"], quota)
        item["displayed_feature_count"] = displayed_count
        if displayed_count:
            frame = pyogrio.read_dataframe(
                geodatabase,
                layer=item["name"],
                max_features=displayed_count,
            )
            if frame.crs is None:
                raise OSMExtractionError(
                    f"Feature class {item['name']} has no coordinate reference system and cannot be mapped"
                )
            if frame.crs.to_epsg() != 4326:
                frame = frame.to_crs(epsg=4326)
            collection = json.loads(frame.to_json(drop_id=True))
            for feature in collection["features"]:
                if feature.get("geometry") is None:
                    continue
                feature.setdefault("properties", {})["_layer"] = item["name"]
                features.append(feature)
        remaining -= displayed_count
        remaining_layers -= 1

    total_features = sum(item["feature_count"] for item in layer_info)
    return {
        "type": "FeatureCollection",
        "features": features,
        "feature_count": total_features,
        "displayed_feature_count": len(features),
        "truncated": len(features) < total_features,
        "layers": layer_info,
        "crs": "EPSG:4326",
    }


def _download_features(
    bounds: BoundingBox,
    tags: dict[str, bool | str],
    boundary_geometry: Polygon | MultiPolygon | None = None,
):
    query_operation = ox.features_from_polygon if boundary_geometry is not None else ox.features_from_bbox
    query_area = (
        boundary_geometry
        if boundary_geometry is not None
        else (bounds.west, bounds.south, bounds.east, bounds.north)
    )
    feature_type = next(iter(tags))
    if feature_type not in HEAVY_FEATURE_TYPES:
        return _call_with_cache_recovery(query_operation, query_area, tags)

    original_settings = {
        "overpass_url": ox.settings.overpass_url,
        "requests_timeout": ox.settings.requests_timeout,
        "max_query_area_size": ox.settings.max_query_area_size,
    }
    errors: list[str] = []
    try:
        ox.settings.requests_timeout = OVERPASS_REQUEST_TIMEOUT
        ox.settings.max_query_area_size = HEAVY_FEATURE_MAX_QUERY_AREA_SIZE
        for endpoint in OSM_OVERPASS_URLS:
            ox.settings.overpass_url = endpoint
            try:
                return _call_with_cache_recovery(query_operation, query_area, tags)
            except requests.exceptions.RequestException as exc:
                errors.append(f"{endpoint}: {exc}")
        raise OSMExtractionError(
            "Could not connect to a configured Overpass endpoint. Route relations can be "
            "large; try a narrower subtype or smaller area. Tried: " + "; ".join(errors)
        )
    finally:
        for name, value in original_settings.items():
            setattr(ox.settings, name, value)


def _write_attribution_notice(
    path: Path,
    label: str,
    bounds: BoundingBox,
    tags: dict[str, bool | str],
    feature_classes: list[str],
    selection_kind: str,
    feature_count: int,
) -> None:
    tag_description = ", ".join(
        f"{key}={value}" if value is not True else key for key, value in tags.items()
    )
    header = f"""OPENSTREETMAP DATA ATTRIBUTION

This geodatabase contains data from OpenStreetMap.
© OpenStreetMap contributors

This geodatabase is made available under the Open Data Commons Open Database
License (ODbL) 1.0. Retain this attribution and license notice when using or
redistributing the data, and comply with applicable ODbL share-alike
requirements for derivative databases. The Geospatial Extraction Studio Apache License 2.0 does not
apply to this geodatabase.

OpenStreetMap copyright: {OSM_COPYRIGHT_URL}
ODbL 1.0 license: {ODBL_URL}
"""

    record = f"""Extraction record
-----------------
Label: {label}
Selection geometry: {selection_kind}
Bounding box (west, south, east, north): {bounds.west}, {bounds.south}, {bounds.east}, {bounds.north}
OSM tag selection: {tag_description}
Extracted at: {datetime.now(UTC).replace(microsecond=0).isoformat()}
Features added: {feature_count}
Feature classes written: {", ".join(feature_classes)}
"""
    existing = path.read_text(encoding="utf-8") if path.exists() else header
    path.write_text(existing.rstrip() + "\n\n" + record, encoding="utf-8")


def _zip_export(export_dir: Path, archive_path: Path) -> None:
    archive_path.unlink(missing_ok=True)
    with ZipFile(archive_path, "w", ZIP_DEFLATED) as archive:
        for path in sorted(export_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(export_dir))


def _commit_staged_export(
    staging_dir: Path,
    final_dir: Path,
    staging_archive: Path,
    final_archive: Path,
) -> None:
    """Atomically replace an export, restoring the previous version on failure."""
    backup_dir = final_dir.with_name(f".{final_dir.name}.backup")
    backup_archive = final_archive.with_name(f".{final_archive.name}.backup")
    shutil.rmtree(backup_dir, ignore_errors=True)
    backup_archive.unlink(missing_ok=True)
    had_directory = final_dir.exists()
    had_archive = final_archive.exists()
    try:
        if had_directory:
            final_dir.replace(backup_dir)
        if had_archive:
            final_archive.replace(backup_archive)
        staging_dir.replace(final_dir)
        staging_archive.replace(final_archive)
    except Exception:
        shutil.rmtree(final_dir, ignore_errors=True)
        final_archive.unlink(missing_ok=True)
        if had_directory and backup_dir.exists():
            backup_dir.replace(final_dir)
        if had_archive and backup_archive.exists():
            backup_archive.replace(final_archive)
        raise
    finally:
        shutil.rmtree(backup_dir, ignore_errors=True)
        backup_archive.unlink(missing_ok=True)


def extract_osm_features(
    bounds: BoundingBox,
    label: str,
    feature_type: str,
    feature_subtype: str | None,
    output_root: Path,
    export_id: str,
    boundary: dict[str, Any] | None = None,
    existing_export: dict[str, Any] | None = None,
    output_format: str = "openfilegdb",
) -> dict:
    if output_format not in OSM_OUTPUT_FORMATS:
        raise OSMExtractionError(f"Unsupported OSM output format: {output_format}")
    format_config = OSM_OUTPUT_FORMATS[output_format]
    subtype = (feature_subtype or "").strip()
    tags: dict[str, bool | str] = {feature_type: subtype or True}
    safe_feature = _sanitize_name(
        f"{feature_type}_{subtype}" if subtype else feature_type,
        max_length=45,
    )
    boundary_geometry: Polygon | MultiPolygon | None = None
    selected_area_km2 = bounds.area_km2()
    selection_kind = "bounding_box"
    if boundary is not None:
        boundary_geometry, selected_area_km2 = _validated_boundary(boundary)
        selection_kind = "named_place_boundary"
        if selected_area_km2 > MAX_OSM_BOUNDARY_AREA_KM2:
            raise OSMExtractionError(
                f"The selected place boundary is {selected_area_km2:,.0f} km²; choose one smaller than {MAX_OSM_BOUNDARY_AREA_KM2:,} km²"
            )

    output_root.mkdir(parents=True, exist_ok=True)
    staging_dir = output_root / f".{export_id}.staging-{uuid.uuid4().hex[:8]}"
    staging_archive = output_root / f".{export_id}.staging.zip"
    final_dir: Path
    geodatabase_name: str
    notice_name: str
    archive_path: Path
    previous_feature_classes: list[str] = []
    previous_feature_count = 0
    previous_extractions: list[dict[str, Any]] = []

    if existing_export is not None:
        files = existing_export.get("files", {})
        existing_geodatabase = Path(str(files.get("geodatabase", ""))).resolve()
        stored_output_format = (
            str(existing_export.get("output_format"))
            if existing_export.get("output_format")
            else "geopackage" if existing_geodatabase.suffix.lower() == ".gpkg" else "openfilegdb"
        )
        if stored_output_format not in OSM_OUTPUT_FORMATS:
            raise OSMExtractionError("The selected export has an unsupported output format")
        if output_format != stored_output_format:
            raise OSMExtractionError("The selected export must be extended using its existing output format")
        output_format = stored_output_format
        format_config = OSM_OUTPUT_FORMATS[output_format]
        existing_notice = Path(str(files.get("attribution", ""))).resolve()
        archive_path = Path(str(files.get("archive", ""))).resolve()
        final_dir = existing_geodatabase.parent
        resolved_output_root = output_root.resolve()
        if (
            final_dir.parent != resolved_output_root
            or final_dir.name != export_id
            or archive_path.parent != resolved_output_root
        ):
            raise OSMExtractionError("The selected export has an invalid storage location")
        existing_dataset_exists = (
            existing_geodatabase.is_dir()
            if output_format == "openfilegdb"
            else existing_geodatabase.is_file()
        )
        if not existing_dataset_exists or not existing_notice.is_file():
            raise OSMExtractionError("The selected OSM dataset or its attribution notice is missing")
        label = str(existing_export.get("label") or label)
        geodatabase_name = existing_geodatabase.name
        notice_name = existing_notice.name
        previous_feature_classes = [str(item) for item in existing_export.get("feature_classes", [])]
        previous_feature_count = int(existing_export.get("feature_count", 0))
        previous_extractions = list(existing_export.get("extractions") or [])
        if not previous_extractions:
            previous_extractions.append(
                {
                    "feature_type": existing_export.get("feature_type"),
                    "feature_subtype": existing_export.get("feature_subtype"),
                    "feature_count": previous_feature_count,
                    "feature_classes": previous_feature_classes,
                    "bounds": existing_export.get("bounds"),
                    "area_km2": existing_export.get("area_km2"),
                    "selection_kind": existing_export.get("selection_kind", "bounding_box"),
                }
            )
    else:
        safe_label = _sanitize_name(label) or "Selected_area"
        final_dir = output_root / export_id
        geodatabase_name = f"{safe_label}{format_config['extension']}"
        notice_name = f"{safe_label}_OSM_ATTRIBUTION.txt"
        archive_path = output_root / f"{export_id}_{safe_label}_OSM.zip"
        if final_dir.exists() or archive_path.exists():
            raise OSMExtractionError("An export with this identifier already exists")

    try:
        with _OSMNX_LOCK:
            gdf = _download_features(bounds, tags, boundary_geometry)
        if gdf.empty:
            raise OSMExtractionError(
                f"No features were found for {feature_type}{'=' + subtype if subtype else ''} in the selected area."
            )
        driver = str(format_config["driver"])
        if "w" not in pyogrio.list_drivers().get(driver, ""):
            display_name = str(format_config["display_name"])
            raise OSMExtractionError(f"This GDAL installation cannot write {display_name} datasets.")

        gdf = _rename_reserved_fields(gdf)
        geometry_column = gdf.geometry.name
        for column in gdf.columns:
            if column == geometry_column:
                continue
            if gdf[column].map(lambda value: isinstance(value, (list, dict, set, tuple))).any():
                gdf[column] = gdf[column].map(
                    lambda value: json.dumps(value, default=str)
                    if isinstance(value, (list, dict, set, tuple))
                    else value
                )

        grouped_layers: list[tuple[str, Any]] = []
        for geometry_type, group in gdf.groupby(gdf.geometry.type):
            geometry_name = _sanitize_name(str(geometry_type)).lower()
            layer_prefix = "main_" if output_format == "openfilegdb" else ""
            layer_name = f"{layer_prefix}{safe_feature.lower()}_{geometry_name}"[:60]
            grouped_layers.append((layer_name, group))
        if not grouped_layers:
            raise OSMExtractionError("The query returned no supported geometries to export.")

        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_archive.unlink(missing_ok=True)
        if existing_export is not None:
            shutil.copytree(final_dir, staging_dir)
        else:
            staging_dir.mkdir(parents=True)

        working_geodatabase = staging_dir / geodatabase_name
        working_notice = staging_dir / notice_name
        existing_layer_names = (
            {str(layer[0]).lower() for layer in pyogrio.list_layers(working_geodatabase)}
            if working_geodatabase.exists()
            else set()
        )
        duplicate_layers = [
            layer_name for layer_name, _ in grouped_layers if layer_name.lower() in existing_layer_names
        ]
        if duplicate_layers:
            raise OSMExtractionError(
                "The existing geodatabase already contains: "
                + ", ".join(duplicate_layers)
                + ". Choose a different feature subtype or create a new geodatabase."
            )

        feature_classes: list[str] = []
        write_options: dict[str, Any] = {"driver": driver, "engine": "pyogrio"}
        if format_config["layer_options"]:
            write_options["layer_options"] = format_config["layer_options"]
        for layer_name, group in grouped_layers:
            group.to_file(
                working_geodatabase,
                layer=layer_name,
                **write_options,
            )
            feature_classes.append(layer_name)

        _write_attribution_notice(
            working_notice,
            label,
            bounds,
            tags,
            feature_classes,
            selection_kind,
            int(len(gdf)),
        )
        _zip_export(staging_dir, staging_archive)
        _commit_staged_export(staging_dir, final_dir, staging_archive, archive_path)

        all_feature_classes = previous_feature_classes + feature_classes
        extraction_record = {
            "feature_type": feature_type,
            "feature_subtype": subtype or None,
            "feature_count": int(len(gdf)),
            "feature_classes": feature_classes,
            "bounds": bounds.model_dump(),
            "area_km2": round(selected_area_km2, 2),
            "selection_kind": selection_kind,
            "extracted_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        }
        return {
            "id": export_id,
            "label": label,
            "provider": "OpenStreetMap",
            "output_format": output_format,
            "feature_type": feature_type,
            "feature_subtype": subtype or None,
            "feature_count": previous_feature_count + int(len(gdf)),
            "last_extraction_count": int(len(gdf)),
            "feature_classes": all_feature_classes,
            "extractions": previous_extractions + [extraction_record],
            "bounds": bounds.model_dump(),
            "area_km2": round(selected_area_km2, 2),
            "selection_kind": selection_kind,
            "license": "Open Data Commons Open Database License (ODbL) 1.0",
            "files": {
                "geodatabase": str(final_dir / geodatabase_name),
                "attribution": str(final_dir / notice_name),
                "archive": str(archive_path),
                "download": f"/api/osm/exports/{export_id}/download",
            },
        }
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_archive.unlink(missing_ok=True)
        raise
