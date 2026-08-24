from __future__ import annotations

import os
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2]
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve()
PROJECT_ROOT = RESOURCE_ROOT if IS_FROZEN else SOURCE_ROOT
FRONTEND_DIST_DIR = RESOURCE_ROOT / "frontend" / "dist"


def default_data_root(
    *,
    frozen: bool = IS_FROZEN,
    local_app_data: str | None = os.getenv("LOCALAPPDATA"),
    project_root: Path = PROJECT_ROOT,
) -> Path:
    if not frozen:
        return project_root / "data"
    if not local_app_data:
        raise RuntimeError(
            "LOCALAPPDATA is required to select a writable data directory for the installed application"
        )
    return Path(local_app_data) / "Geospatial Extraction Studio" / "data"


DATA_ROOT = Path(os.getenv("ELEVATION_DATA_DIR") or default_data_root()).resolve()
ORIGINAL_DIR = DATA_ROOT / "original"
PROCESSED_DIR = DATA_ROOT / "processed"
NAIP_ORIGINAL_DIR = ORIGINAL_DIR / "naip"
NAIP_PROCESSED_DIR = PROCESSED_DIR / "naip"
CACHE_DIR = DATA_ROOT / "cache"
EXPORT_DIR = DATA_ROOT / "exports"
DB_PATH = DATA_ROOT / "app.db"
_automatic_legacy_roots = (
    ()
    if IS_FROZEN
    else (PROJECT_ROOT.parent.parent / PROJECT_ROOT.name / "data",)
)
_configured_legacy_roots_value = os.getenv("GES_LEGACY_DATA_DIRS", "")
_configured_legacy_roots = [
    Path(value.strip())
    for value in _configured_legacy_roots_value.split(os.pathsep)
    if value.strip()
]
LEGACY_DATA_ROOTS = tuple(
    path.resolve()
    for path in (*_automatic_legacy_roots, *_configured_legacy_roots)
    if path.resolve() != DATA_ROOT.resolve()
)
OSM_CACHE_DIR = Path(os.getenv("OSM_EXTRACTOR_CACHE_DIR", CACHE_DIR / "osmnx"))
OSM_USER_AGENT = os.getenv(
    "OSM_EXTRACTOR_USER_AGENT",
    "GeospatialExtractionStudio/0.4.2 (local terrain, NAIP, and OSM extractor)",
)
OSM_OVERPASS_URLS = tuple(
    endpoint.strip()
    for endpoint in os.getenv(
        "OSM_EXTRACTOR_OVERPASS_URLS",
        "https://overpass-api.de/api,https://overpass.private.coffee/api",
    ).split(",")
    if endpoint.strip()
)
NOMINATIM_SEARCH_URL = os.getenv(
    "NOMINATIM_SEARCH_URL", "https://nominatim.openstreetmap.org/search"
)
NOMINATIM_USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT",
    "GeospatialExtractionStudio/0.4.2 (local terrain, NAIP, and OSM extractor)",
)
NOMINATIM_MIN_INTERVAL_SECONDS = float(
    os.getenv("NOMINATIM_MIN_INTERVAL_SECONDS", "1.0")
)
NAIP_STAC_SEARCH_URL = os.getenv(
    "NAIP_STAC_SEARCH_URL", "https://planetarycomputer.microsoft.com/api/stac/v1/search"
)
NAIP_STAC_COLLECTION_URL = os.getenv(
    "NAIP_STAC_COLLECTION_URL",
    "https://planetarycomputer.microsoft.com/api/stac/v1/collections/naip",
)
NAIP_SIGN_URL = os.getenv(
    "NAIP_SIGN_URL", "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
)
NAIP_MAX_OUTPUT_PIXELS = int(os.getenv("NAIP_MAX_OUTPUT_PIXELS", "250000000"))


def ensure_data_directories() -> None:
    for path in (
        DATA_ROOT,
        ORIGINAL_DIR,
        PROCESSED_DIR,
        NAIP_ORIGINAL_DIR,
        NAIP_PROCESSED_DIR,
        CACHE_DIR,
        OSM_CACHE_DIR,
        EXPORT_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
