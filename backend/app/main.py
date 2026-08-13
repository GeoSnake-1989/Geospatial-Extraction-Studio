from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import (
    CACHE_DIR,
    EXPORT_DIR,
    FRONTEND_DIST_DIR,
    LEGACY_DATA_ROOTS,
    NAIP_ORIGINAL_DIR,
    NAIP_PROCESSED_DIR,
    NOMINATIM_MIN_INTERVAL_SECONDS,
    NOMINATIM_SEARCH_URL,
    NOMINATIM_USER_AGENT,
    ORIGINAL_DIR,
    PROJECT_ROOT,
    PROCESSED_DIR,
    ensure_data_directories,
)
from .database import (
    delete_dataset as delete_dataset_record,
    delete_naip_imagery as delete_naip_imagery_record,
    delete_osm_export as delete_osm_export_record,
    get_dataset,
    get_naip_imagery,
    get_osm_export,
    initialize_database,
    list_datasets,
    list_naip_imagery,
    list_osm_exports,
    save_dataset,
    save_naip_imagery,
    save_osm_export,
)
from .models import (
    BoundingBox,
    ExtractionRequest,
    JobResponse,
    JobState,
    NAIPExtractionRequest,
    OSMExtractionRequest,
    PlaceResult,
)
from .osm import OSMExtractionError, boundary_area_km2, build_osm_map_preview, extract_osm_features
from .package_api import naip_package_response, terrain_package_response
from .providers import (
    NAIPProvider,
    NAIPProviderError,
    USGS3DEPProvider,
    source_grid_dimensions,
)
from .provenance import file_integrity, write_source_documentation
from .rate_limit import AsyncIntervalLimiter
from .raster import build_preview
from .storage import (
    StorageSafetyError,
    clear_directory_contents,
    managed_path,
    remove_path,
    storage_summary,
)


jobs: dict[str, JobResponse] = {}
place_cache: dict[tuple[str, str], list[PlaceResult]] = {}
MAX_COMPLETED_JOB_RECORDS = 100
place_request_limiter = AsyncIntervalLimiter(NOMINATIM_MIN_INTERVAL_SECONDS)
osm_job_lock = asyncio.Lock()
naip_job_lock = asyncio.Lock()
def dataset_storage_paths(item: dict[str, Any], kind: Literal["original", "processed"]) -> list[Path]:
    dataset_id = str(item.get("id", ""))
    if len(dataset_id) != 12 or any(character not in "0123456789abcdef" for character in dataset_id.lower()):
        raise StorageSafetyError("The dataset identifier is invalid")
    expected_names = (
        {f"{dataset_id}_usgs_3dep.tif", f"{dataset_id}_terrain_source.tif"}
        if kind == "original"
        else {f"{dataset_id}_preview.tif"}
    )
    try:
        stored_name = Path(item["files"][kind]).name
    except KeyError as exc:
        raise StorageSafetyError("The dataset file history is incomplete") from exc
    expected_name = next((name for name in expected_names if stored_name.lower() == name.lower()), "")
    if not expected_name:
        raise StorageSafetyError("The dataset filename does not match its identifier")

    subdirectory = "original" if kind == "original" else "processed"
    roots = [ORIGINAL_DIR if kind == "original" else PROCESSED_DIR]
    roots.extend(root / subdirectory for root in LEGACY_DATA_ROOTS)
    paths: list[Path] = []
    for root in roots:
        for candidate in (root / "terrain" / dataset_id / expected_name, root / expected_name):
            path = managed_path(str(candidate), root)
            if path not in paths:
                paths.append(path)
    return paths


def dataset_cleanup_paths(item: dict[str, Any]) -> list[Path]:
    dataset_id = str(item.get("id", ""))
    paths = dataset_storage_paths(item, "original") + dataset_storage_paths(item, "processed")
    roots = [ORIGINAL_DIR, PROCESSED_DIR]
    roots.extend(
        root / subdirectory
        for root in LEGACY_DATA_ROOTS
        for subdirectory in ("original", "processed")
    )
    for root in roots:
        directory = managed_path(str(root / "terrain" / dataset_id), root)
        if directory not in paths:
            paths.append(directory)
    return paths


def dataset_documentation_paths(item: dict[str, Any]) -> list[Path]:
    dataset_id = str(item.get("id", ""))
    if len(dataset_id) != 12 or any(
        character not in "0123456789abcdef" for character in dataset_id.lower()
    ):
        raise StorageSafetyError("The dataset identifier is invalid")
    stored = item.get("files", {}).get("documentation")
    if not stored:
        return []
    if Path(stored).name.lower() != "source_provenance.md":
        raise StorageSafetyError("The source-documentation filename is invalid")
    roots = [ORIGINAL_DIR, *(root / "original" for root in LEGACY_DATA_ROOTS)]
    return [
        managed_path(
            str(root / "terrain" / dataset_id / "SOURCE_PROVENANCE.md"),
            root,
        )
        for root in roots
    ]


def osm_export_storage_paths(item: dict[str, Any]) -> list[Path]:
    export_id = str(item.get("id", ""))
    allowed_characters = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if (
        not export_id
        or len(export_id) > 64
        or any(character not in allowed_characters for character in export_id)
    ):
        raise StorageSafetyError("The OSM export identifier is invalid")
    try:
        geodatabase_name = Path(item["files"]["geodatabase"]).name
        archive_name = Path(item["files"]["archive"]).name
    except KeyError as exc:
        raise StorageSafetyError("The OSM export file history is incomplete") from exc
    dataset_suffix = Path(geodatabase_name).suffix.lower()
    if dataset_suffix not in {".gdb", ".gpkg"}:
        raise StorageSafetyError("The OSM dataset filename is invalid")
    if not archive_name.startswith(f"{export_id}_") or not archive_name.lower().endswith(".zip"):
        raise StorageSafetyError("The OSM archive filename does not match its identifier")

    roots = [EXPORT_DIR, *(root / "exports" for root in LEGACY_DATA_ROOTS)]
    paths: list[Path] = []
    for root in roots:
        for candidate in (root / export_id, root / archive_name):
            path = managed_path(str(candidate), root)
            if path not in paths:
                paths.append(path)
    return paths

def naip_imagery_storage_candidates(item: dict[str, Any]) -> dict[str, list[Path]]:
    imagery_id = str(item.get("id", ""))
    if len(imagery_id) != 12 or any(
        character not in "0123456789abcdef" for character in imagery_id.lower()
    ):
        raise StorageSafetyError("The NAIP imagery identifier is invalid")
    expected = {
        "manifest": f"{imagery_id}_naip_sources.json",
        "imagery": f"{imagery_id}_naip_mosaic.tif",
        "preview": f"{imagery_id}_naip_preview.png",
    }
    paths: dict[str, list[Path]] = {}
    for kind, expected_name in expected.items():
        try:
            stored_name = Path(item["files"][kind]).name
        except KeyError as exc:
            raise StorageSafetyError("The NAIP imagery file history is incomplete") from exc
        if stored_name.lower() != expected_name.lower():
            raise StorageSafetyError("A NAIP imagery filename does not match its identifier")
        legacy_root = NAIP_ORIGINAL_DIR if kind == "manifest" else NAIP_PROCESSED_DIR
        paths[kind] = [
            managed_path(
                str(NAIP_PROCESSED_DIR / imagery_id / expected_name),
                NAIP_PROCESSED_DIR,
            ),
            managed_path(str(legacy_root / expected_name), legacy_root),
        ]
    return paths


def naip_imagery_storage_paths(item: dict[str, Any]) -> list[Path]:
    candidates = naip_imagery_storage_candidates(item)
    return [
        next((path for path in candidates[kind] if path.is_file()), candidates[kind][0])
        for kind in ("manifest", "imagery", "preview")
    ]


def naip_cleanup_paths(item: dict[str, Any]) -> list[Path]:
    imagery_id = str(item.get("id", ""))
    candidates = naip_imagery_storage_candidates(item)
    paths = [path for kind_paths in candidates.values() for path in kind_paths]
    directory = managed_path(str(NAIP_PROCESSED_DIR / imagery_id), NAIP_PROCESSED_DIR)
    if directory not in paths:
        paths.append(directory)
    return paths


def naip_documentation_paths(item: dict[str, Any]) -> list[Path]:
    imagery_id = str(item.get("id", ""))
    if len(imagery_id) != 12 or any(
        character not in "0123456789abcdef" for character in imagery_id.lower()
    ):
        raise StorageSafetyError("The NAIP imagery identifier is invalid")
    stored = item.get("files", {}).get("documentation")
    if not stored:
        return []
    if Path(stored).name.lower() != "source_provenance.md":
        raise StorageSafetyError("The source-documentation filename is invalid")
    return [
        managed_path(
            str(NAIP_PROCESSED_DIR / imagery_id / "SOURCE_PROVENANCE.md"),
            NAIP_PROCESSED_DIR,
        )
    ]


@asynccontextmanager
async def lifespan(_: FastAPI):
    ensure_data_directories()
    initialize_database()
    yield


app = FastAPI(
    title="Geospatial Extraction Studio API",
    version="0.4.1",
    description="Local-first elevation, OpenStreetMap, and NAIP imagery extraction service",
    license_info={"name": "Apache License 2.0", "identifier": "Apache-2.0"},
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LEGAL_DOCUMENTS = {
    "license": PROJECT_ROOT / "LICENSE",
    "notice": PROJECT_ROOT / "NOTICE",
    "third-party-notices": PROJECT_ROOT / "THIRD_PARTY_NOTICES.md",
    "content-provenance": PROJECT_ROOT / "CONTENT_PROVENANCE.md",
    "asset-licenses": PROJECT_ROOT / "ASSET_LICENSES.md",
}


@app.get("/api/legal/{document}", response_class=FileResponse)
def legal_document(document: Literal["license", "notice", "third-party-notices", "content-provenance", "asset-licenses"]):
    path = LEGAL_DOCUMENTS[document]
    media_type = "text/plain" if not path.suffix else "text/markdown"
    return FileResponse(path, media_type=media_type)


def prune_completed_jobs() -> None:
    terminal_ids = [
        job_id
        for job_id, job in list(jobs.items())
        if job.state in {JobState.completed, JobState.failed}
    ]
    for job_id in terminal_ids[:-MAX_COMPLETED_JOB_RECORDS]:
        jobs.pop(job_id, None)


def set_job(job_id: str, **changes: Any) -> None:
    current = jobs[job_id].model_copy(update=changes)
    jobs[job_id] = current
    if current.state in {JobState.completed, JobState.failed}:
        prune_completed_jobs()


async def run_extraction(job_id: str, request: ExtractionRequest) -> None:
    dataset_id = uuid.uuid4().hex[:12]
    original_directory = ORIGINAL_DIR / "terrain" / dataset_id
    processed_directory = PROCESSED_DIR / "terrain" / dataset_id
    original_path = original_directory / f"{dataset_id}_terrain_source.tif"
    processed_path = processed_directory / f"{dataset_id}_preview.tif"
    evidence_path = original_directory / f"{dataset_id}_source_provenance.json"
    documentation_path = original_directory / "SOURCE_PROVENANCE.md"
    try:
        original_directory.mkdir(parents=True, exist_ok=True)
        processed_directory.mkdir(parents=True, exist_ok=True)
        set_job(job_id, state=JobState.downloading, progress=12, message="Requesting USGS 3DEP seamless terrain")
        source_width, source_height = source_grid_dimensions(request.bounds)
        asset = await USGS3DEPProvider().extract(
            request.bounds, original_path, source_width, source_height
        )
        set_job(job_id, state=JobState.processing, progress=72, message="Validating raster and building terrain mesh")
        preview = await asyncio.to_thread(
            build_preview, asset.path, processed_path, int(request.preview_size)
        )

        provenance = {
            **asset.provider_metadata,
            "source_url": asset.source_url,
            "requested_source": "usgs_seamless",
            "acquisition_note": asset.acquisition_note,
        }
        source_urls = [
            url
            for url in (
                asset.provider_metadata.get("service"),
                asset.source_url,
            )
            if url
        ]
        write_source_documentation(
            evidence_path,
            documentation_path,
            title=f"DEM source provenance - {request.label}",
            evidence={
                "dataset_id": dataset_id,
                "data_type": "Digital Elevation Model (DEM)",
                "label": request.label,
                "provider": asset.provider_name,
                "product": asset.product_name,
                "bounds_wgs84": request.bounds.model_dump(),
                "area_km2": round(request.bounds.area_km2(), 2),
                "source_urls": list(dict.fromkeys(source_urls)),
                "source": provenance,
                "spatial": preview["spatial"],
                "output": file_integrity(original_path),
            },
        )

        result = {
            "id": dataset_id,
            "label": request.label,
            "provider": asset.provider_name,
            "product": asset.product_name,
            "bounds": request.bounds.model_dump(),
            "area_km2": round(request.bounds.area_km2(), 2),
            "preview": preview,
            "provenance": provenance,
            "files": {
                "original": str(original_path),
                "processed": str(processed_path),
                "source_evidence": str(evidence_path),
                "documentation": str(documentation_path),
                "original_download": f"/api/datasets/{dataset_id}/download/original",
                "processed_download": f"/api/datasets/{dataset_id}/download/processed",
                "documentation_download": f"/api/datasets/{dataset_id}/download/documentation",
                "package_download": f"/api/datasets/{dataset_id}/download/package",
            },
        }
        save_dataset(result)
        set_job(
            job_id,
            state=JobState.completed,
            progress=100,
            message="Terrain ready",
            result=result,
        )
    except Exception as exc:
        for path in (original_directory, processed_directory):
            remove_path(path)
        set_job(
            job_id,
            state=JobState.failed,
            progress=100,
            message="Extraction failed",
            error=str(exc),
        )


async def run_osm_extraction(job_id: str, request: OSMExtractionRequest) -> None:
    export_id = request.target_export_id or uuid.uuid4().hex[:12]
    format_label = "GeoPackage" if request.output_format.value == "geopackage" else "OpenFileGDB"
    await osm_job_lock.acquire()
    try:
        existing_export = None
        if request.target_export_id:
            existing_export = get_osm_export(request.target_export_id)
            if existing_export is None:
                raise ValueError("The selected geodatabase no longer exists in Geospatial Extraction Studio history")
        set_job(
            job_id,
            state=JobState.downloading,
            progress=15,
            message=(
                f"Requesting features to add to the existing {format_label} dataset"
                if existing_export
                else "Requesting features from OpenStreetMap"
            ),
        )
        set_job(
            job_id,
            state=JobState.processing,
            progress=55,
            message="Writing feature classes and attribution",
        )
        result = await asyncio.to_thread(
            extract_osm_features,
            request.bounds,
            request.label,
            request.feature_type,
            request.feature_subtype,
            EXPORT_DIR,
            export_id,
            request.boundary,
            existing_export,
            request.output_format.value,
        )
        save_osm_export(result)
        set_job(
            job_id,
            state=JobState.completed,
            progress=100,
            message=(
                f"Feature classes added to {format_label} dataset"
                if existing_export
                else f"OSM {format_label} dataset ready"
            ),
            result=result,
        )
    except Exception as exc:
        set_job(
            job_id,
            state=JobState.failed,
            progress=100,
            message="OSM extraction failed",
            error=str(exc),
        )
    finally:
        osm_job_lock.release()

async def run_naip_extraction(job_id: str, request: NAIPExtractionRequest) -> None:
    imagery_id = uuid.uuid4().hex[:12]
    imagery_directory = NAIP_PROCESSED_DIR / imagery_id
    manifest_path = imagery_directory / f"{imagery_id}_naip_sources.json"
    imagery_path = imagery_directory / f"{imagery_id}_naip_mosaic.tif"
    preview_path = imagery_directory / f"{imagery_id}_naip_preview.png"
    documentation_path = imagery_directory / "SOURCE_PROVENANCE.md"
    await naip_job_lock.acquire()
    try:
        imagery_directory.mkdir(parents=True, exist_ok=True)
        set_job(
            job_id,
            state=JobState.downloading,
            progress=15,
            message="Finding the newest NAIP coverage for the selected location",
        )
        set_job(
            job_id,
            state=JobState.processing,
            progress=45,
            message="Reading source imagery and building the bounded GeoTIFF mosaic",
        )
        asset = await NAIPProvider().extract(
            request.bounds,
            request.selection_mode,
            request.year,
            request.bands,
            manifest_path,
            imagery_path,
            preview_path,
        )

        source_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        collection = source_manifest.get("collection") or {}
        source_urls = list(
            dict.fromkeys(
                url
                for url in (
                    collection.get("source_url"),
                    *(
                        link.get("href")
                        for link in collection.get("license_links") or []
                        if isinstance(link, dict)
                    ),
                    *(
                        item.get("stac_item_url")
                        for item in source_manifest.get("items", [])
                    ),
                    *(
                        item.get("source_href")
                        for item in source_manifest.get("items", [])
                    ),
                )
                if url
            )
        )
        write_source_documentation(
            manifest_path,
            documentation_path,
            title=f"Aerial imagery source provenance - {request.label}",
            evidence={
                **source_manifest,
                "imagery_id": imagery_id,
                "data_type": "Aerial imagery",
                "label": request.label,
                "product": asset["product"],
                "source_urls": source_urls,
                "area_km2": round(request.bounds.area_km2(), 2),
                "bands": request.bands.value,
                "spatial": asset["spatial"],
                "output": file_integrity(imagery_path),
            },
        )

        result = {
            "id": imagery_id,
            "label": request.label,
            **asset,
            "bounds": request.bounds.model_dump(),
            "area_km2": round(request.bounds.area_km2(), 2),
            "selection_mode": request.selection_mode.value,
            "requested_year": request.year,
            "bands": request.bands.value,
            "files": {
                "manifest": str(manifest_path),
                "imagery": str(imagery_path),
                "preview": str(preview_path),
                "documentation": str(documentation_path),
                "manifest_download": f"/api/naip/imagery/{imagery_id}/download/manifest",
                "imagery_download": f"/api/naip/imagery/{imagery_id}/download/imagery",
                "documentation_download": f"/api/naip/imagery/{imagery_id}/download/documentation",
                "package_download": f"/api/naip/imagery/{imagery_id}/download/package",
                "preview_download": f"/api/naip/imagery/{imagery_id}/preview",
            },
        }
        save_naip_imagery(result)
        set_job(
            job_id,
            state=JobState.completed,
            progress=100,
            message="NAIP imagery ready",
            result=result,
        )
    except Exception as exc:
        remove_path(imagery_directory)
        set_job(
            job_id,
            state=JobState.failed,
            progress=100,
            message="NAIP extraction failed",
            error=str(exc),
        )
    finally:
        naip_job_lock.release()


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "Geospatial Extraction Studio",
        "providers": [
            "USGS 3DEP seamless",
            "OpenStreetMap",
            "USDA NAIP",
        ],
    }



@app.get("/api/storage")
def get_storage() -> dict[str, Any]:
    return storage_summary(
        CACHE_DIR,
        ORIGINAL_DIR,
        PROCESSED_DIR,
        EXPORT_DIR,
        NAIP_ORIGINAL_DIR,
        NAIP_PROCESSED_DIR,
    )


@app.delete("/api/cache")
async def clear_cache() -> dict[str, Any]:
    async with osm_job_lock:
        removed = await asyncio.to_thread(clear_directory_contents, CACHE_DIR)
        place_cache.clear()
    return {
        "message": "Reusable request cache cleared",
        "removed": removed,
        "storage": storage_summary(
            CACHE_DIR,
            ORIGINAL_DIR,
            PROCESSED_DIR,
            EXPORT_DIR,
            NAIP_ORIGINAL_DIR,
            NAIP_PROCESSED_DIR,
        ),
    }


@app.get("/api/places", response_model=list[PlaceResult])
async def search_places(
    q: str = Query(min_length=2, max_length=120),
    scope: Literal["us", "world"] = "us",
) -> list[PlaceResult]:
    key = (scope, q.strip().lower())
    if key in place_cache:
        return place_cache[key]
    params: dict[str, str | int] = {
        "q": q,
        "format": "jsonv2",
        "limit": 5,
        "addressdetails": 1,
    }
    if scope == "us":
        params["countrycodes"] = "us"
    else:
        params["polygon_geojson"] = 1
        # Preserve topology while keeping county boundaries responsive in the browser.
        params["polygon_threshold"] = 0.0001
    headers = {"User-Agent": NOMINATIM_USER_AGENT}
    try:
        await place_request_limiter.wait()
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.get(NOMINATIM_SEARCH_URL, params=params)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Place search is unavailable: {exc}") from exc

    results: list[PlaceResult] = []
    for item in payload:
        raw = [float(value) for value in item["boundingbox"]]
        south, north, west, east = raw
        center_lat = float(item["lat"])
        center_lon = float(item["lon"])
        # Elevation stays bounded to a practical USGS extraction window. OSM
        # keeps the full administrative extent and polygon returned by Nominatim.
        if scope == "us" and ((east - west) > 0.45 or (north - south) > 0.45):
            west, east = center_lon - 0.08, center_lon + 0.08
            south, north = center_lat - 0.06, center_lat + 0.06
        try:
            bounds = BoundingBox(west=west, south=south, east=east, north=north)
        except ValueError:
            continue
        boundary = item.get("geojson") if scope == "world" else None
        boundary_area = None
        if not isinstance(boundary, dict) or boundary.get("type") not in {"Polygon", "MultiPolygon"}:
            boundary = None
        else:
            try:
                boundary_area = round(boundary_area_km2(boundary), 2)
            except Exception:
                boundary = None

        results.append(
            PlaceResult(
                name=item["display_name"],
                latitude=center_lat,
                longitude=center_lon,
                bounds=bounds,
                kind=item.get("type"),
                boundary=boundary,
                boundary_area_km2=boundary_area,
            )
        )
    place_cache[key] = results
    return results


@app.post("/api/elevation/jobs", response_model=JobResponse, status_code=202)
def create_extraction_job(request: ExtractionRequest, background_tasks: BackgroundTasks) -> JobResponse:
    job_id = uuid.uuid4().hex
    job = JobResponse(
        id=job_id,
        state=JobState.queued,
        progress=2,
        message="Extraction queued",
    )
    jobs[job_id] = job
    background_tasks.add_task(run_extraction, job_id, request)
    return job


@app.get("/api/elevation/jobs/{job_id}", response_model=JobResponse)
def get_extraction_job(job_id: str) -> JobResponse:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]

@app.get("/api/naip/availability")
async def naip_availability(
    west: float = Query(ge=-180, le=180),
    south: float = Query(ge=-90, le=90),
    east: float = Query(ge=-180, le=180),
    north: float = Query(ge=-90, le=90),
) -> dict[str, Any]:
    try:
        bounds = BoundingBox(west=west, south=south, east=east, north=north)
        if bounds.area_km2() > 500:
            raise ValueError("NAIP catalog selections must be smaller than 500 km?")
        return await NAIPProvider().availability(bounds)
    except (ValueError, NAIPProviderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/naip/jobs", response_model=JobResponse, status_code=202)
def create_naip_job(request: NAIPExtractionRequest, background_tasks: BackgroundTasks) -> JobResponse:
    job_id = uuid.uuid4().hex
    job = JobResponse(
        id=job_id,
        state=JobState.queued,
        progress=2,
        message="NAIP extraction queued",
    )
    jobs[job_id] = job
    background_tasks.add_task(run_naip_extraction, job_id, request)
    return job


@app.get("/api/naip/jobs/{job_id}", response_model=JobResponse)
def get_naip_job(job_id: str) -> JobResponse:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/naip/imagery")
def naip_imagery() -> list[dict[str, Any]]:
    return list_naip_imagery()


@app.get("/api/naip/imagery/{imagery_id}/preview", response_class=FileResponse)
def preview_naip_imagery(imagery_id: str) -> FileResponse:
    item = get_naip_imagery(imagery_id)
    if not item:
        raise HTTPException(status_code=404, detail="NAIP imagery not found")
    try:
        path = naip_imagery_storage_paths(item)[2]
    except StorageSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="NAIP preview is missing")
    return FileResponse(path, media_type="image/png", filename=path.name)


@app.get("/api/naip/imagery/{imagery_id}/download/{kind}")
def download_naip_imagery(
    imagery_id: str,
    kind: Literal["imagery", "manifest", "documentation", "package"],
) -> FileResponse:
    item = get_naip_imagery(imagery_id)
    if not item:
        raise HTTPException(status_code=404, detail="NAIP imagery not found")
    try:
        if kind == "package":
            paths = naip_imagery_storage_paths(item)
            if not paths[0].is_file() or not paths[1].is_file():
                raise HTTPException(status_code=404, detail="NAIP package files are missing")
            return naip_package_response(item, paths[0], paths[1], CACHE_DIR)
        if kind == "documentation":
            candidates = naip_documentation_paths(item)
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
        else:
            paths = naip_imagery_storage_paths(item)
            path = paths[1] if kind == "imagery" else paths[0]
    except StorageSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="NAIP download is missing")
    media_type = {
        "imagery": "image/tiff",
        "manifest": "application/json",
        "documentation": "text/markdown",
    }[kind]
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.delete("/api/naip/imagery/{imagery_id}")
async def delete_naip_imagery(imagery_id: str) -> dict[str, Any]:
    async with naip_job_lock:
        item = get_naip_imagery(imagery_id)
        if not item:
            raise HTTPException(status_code=404, detail="NAIP imagery not found")
        try:
            paths = naip_cleanup_paths(item)
        except StorageSafetyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        removed_files = any(path.exists() or path.is_symlink() for path in paths)
        for path in paths:
            await asyncio.to_thread(remove_path, path)
        delete_naip_imagery_record(imagery_id)
    return {
        "message": (
            "NAIP imagery deleted"
            if removed_files
            else "Saved NAIP entry removed; no managed imagery files were found"
        ),
        "id": imagery_id,
        "removed_files": removed_files,
    }


@app.post("/api/osm/jobs", response_model=JobResponse, status_code=202)
def create_osm_job(request: OSMExtractionRequest, background_tasks: BackgroundTasks) -> JobResponse:
    job_id = uuid.uuid4().hex
    job = JobResponse(
        id=job_id,
        state=JobState.queued,
        progress=2,
        message="OSM extraction queued",
    )
    jobs[job_id] = job
    background_tasks.add_task(run_osm_extraction, job_id, request)
    return job


@app.get("/api/osm/jobs/{job_id}", response_model=JobResponse)
def get_osm_job(job_id: str) -> JobResponse:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]


@app.get("/api/osm/exports")
def osm_exports() -> list[dict[str, Any]]:
    return list_osm_exports()


@app.get("/api/osm/exports/{export_id}/download")
def download_osm_export(export_id: str) -> FileResponse:
    item = get_osm_export(export_id)
    if not item:
        raise HTTPException(status_code=404, detail="OSM export not found")
    try:
        candidates = [
            path
            for path in osm_export_storage_paths(item)
            if path.suffix.lower() == ".zip"
        ]
    except StorageSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise HTTPException(status_code=404, detail="OSM export archive is missing")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.get("/api/osm/exports/{export_id}/preview")
def preview_osm_export(export_id: str) -> dict[str, Any]:
    item = get_osm_export(export_id)
    if not item:
        raise HTTPException(status_code=404, detail="OSM export not found")
    try:
        geodatabase = managed_path(item["files"]["geodatabase"], EXPORT_DIR)
        if geodatabase.parent != (EXPORT_DIR / export_id).resolve():
            raise StorageSafetyError("The export directory does not match its identifier")
        suffix = geodatabase.suffix.lower()
        valid_dataset = (
            geodatabase.is_dir()
            if suffix == ".gdb"
            else geodatabase.is_file() if suffix == ".gpkg" else False
        )
        if not valid_dataset:
            raise HTTPException(status_code=404, detail="OSM export dataset is missing")
        return build_osm_map_preview(geodatabase, list(item.get("feature_classes", [])))
    except HTTPException:
        raise
    except (KeyError, OSMExtractionError, StorageSafetyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/osm/exports/{export_id}")
async def delete_osm_export(export_id: str) -> dict[str, Any]:
    async with osm_job_lock:
        item = get_osm_export(export_id)
        if not item:
            raise HTTPException(status_code=404, detail="OSM export not found")
        try:
            paths = osm_export_storage_paths(item)
        except StorageSafetyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        removed_files = any(path.exists() or path.is_symlink() for path in paths)
        for path in paths:
            await asyncio.to_thread(remove_path, path)
        delete_osm_export_record(export_id)
    return {
        "message": (
            "OSM dataset deleted"
            if removed_files
            else "Saved OSM entry removed; no managed dataset files were found"
        ),
        "id": export_id,
        "removed_files": removed_files,
    }


@app.get("/api/datasets")
def datasets() -> list[dict[str, Any]]:
    return list_datasets()


@app.get("/api/datasets/{dataset_id}")
def dataset(dataset_id: str) -> dict[str, Any]:
    item = get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return item


@app.delete("/api/datasets/{dataset_id}")
def delete_dataset(dataset_id: str) -> dict[str, Any]:
    item = get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        paths = dataset_cleanup_paths(item)
    except StorageSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    for path in paths:
        remove_path(path)
    delete_dataset_record(dataset_id)
    return {"message": "Terrain dataset deleted", "id": dataset_id}


@app.get("/api/datasets/{dataset_id}/download/{kind}")
def download_dataset(dataset_id: str, kind: str) -> FileResponse:
    if kind not in {"original", "processed", "documentation", "package"}:
        raise HTTPException(
            status_code=400,
            detail="Download kind must be original, processed, documentation, or package",
        )
    item = get_dataset(dataset_id)
    if not item:
        raise HTTPException(status_code=404, detail="Dataset not found")
    try:
        if kind == "package":
            candidates = dataset_storage_paths(item, "original")
            path = next((candidate for candidate in candidates if candidate.is_file()), None)
            if path is None:
                raise HTTPException(status_code=404, detail="DEM package file is missing")
            return terrain_package_response(item, path, CACHE_DIR)
        candidates = (
            dataset_documentation_paths(item)
            if kind == "documentation"
            else dataset_storage_paths(item, kind)
        )
    except StorageSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise HTTPException(status_code=404, detail="Dataset file is missing")
    if kind == "documentation":
        return FileResponse(path, media_type="text/markdown", filename=path.name)
    suffix = "source" if kind == "original" else "preview"
    return FileResponse(path, media_type="image/tiff", filename=f"{dataset_id}_{suffix}.tif")


# Register the single-page application last so every /api route keeps
# precedence. The development workflow continues to use Vite when no built
# frontend is present.
if FRONTEND_DIST_DIR.joinpath("index.html").is_file():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST_DIR, html=True), name="frontend")
