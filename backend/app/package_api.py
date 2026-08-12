from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from .packages import build_raster_package, safe_package_component
from .provenance import file_integrity


def _package_response(
    item: dict[str, Any],
    *,
    cache_root: Path,
    raster_path: Path,
    suffix: str,
    data_type: str,
    evidence: dict[str, Any],
) -> FileResponse:
    item_id = str(item["id"])
    label = str(item.get("label") or item_id)
    label_component = safe_package_component(label, item_id)
    folder_name = safe_package_component(f"{label_component}_{suffix}", item_id)
    raster_filename = f"{folder_name}.tif"
    evidence = {
        **evidence,
        "output": {**evidence.get("output", {}), "filename": raster_filename},
    }
    archive_path = cache_root / "downloads" / f"{item_id}_{uuid.uuid4().hex}.zip"
    build_raster_package(
        archive_path,
        folder_name=folder_name,
        raster_path=raster_path,
        raster_filename=raster_filename,
        title=f"{data_type} source provenance - {label}",
        evidence=evidence,
    )
    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{folder_name}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


def terrain_package_response(
    item: dict[str, Any], raster_path: Path, cache_root: Path
) -> FileResponse:
    provenance = dict(item.get("provenance") or {})
    source_urls = [
        url
        for url in (provenance.get("service"), provenance.get("source_url"))
        if url
    ]
    evidence = {
        "dataset_id": item["id"],
        "data_type": "Digital Elevation Model (DEM)",
        "label": item.get("label"),
        "provider": item.get("provider"),
        "product": item.get("product"),
        "bounds_wgs84": item.get("bounds"),
        "area_km2": item.get("area_km2"),
        "source_urls": list(dict.fromkeys(source_urls)),
        "source": provenance,
        "spatial": item.get("preview", {}).get("spatial", {}),
        "output": file_integrity(raster_path),
    }
    return _package_response(
        item,
        cache_root=cache_root,
        raster_path=raster_path,
        suffix="DEM",
        data_type="DEM",
        evidence=evidence,
    )


def naip_package_response(
    item: dict[str, Any],
    manifest_path: Path,
    raster_path: Path,
    cache_root: Path,
) -> FileResponse:
    source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source_urls = source_manifest.get("source_urls") or [
        source_item["source_href"]
        for source_item in source_manifest.get("items", [])
        if source_item.get("source_href")
    ]
    evidence = {
        **source_manifest,
        "imagery_id": item["id"],
        "data_type": "Aerial imagery",
        "label": item.get("label"),
        "provider": item.get("provider"),
        "product": item.get("product"),
        "source_urls": source_urls,
        "area_km2": item.get("area_km2"),
        "bands": item.get("bands"),
        "spatial": item.get("spatial", {}),
        "output": file_integrity(raster_path),
    }
    return _package_response(
        item,
        cache_root=cache_root,
        raster_path=raster_path,
        suffix="Aerial_Imagery",
        data_type="Aerial imagery",
        evidence=evidence,
    )
