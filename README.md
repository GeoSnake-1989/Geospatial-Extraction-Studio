# Geospatial Extraction Studio

Geospatial Extraction Studio is the sole maintained application in this workspace. It provides elevation viewing, NAIP aerial-imagery extraction, and OpenStreetMap extraction in one local-first Windows application. A single place search and map define the area of interest, then the user chooses a workflow.

This `Geospatial Extraction Studio` directory is intended to be the root of the
public GitHub repository. Do not publish its parent workspace as the repository
root; the parent can contain planning material outside this project's license
and release controls.

## Combined workflows

### Elevation

- Search U.S. places covered by the USGS 3DEP seamless service.
- Draw rectangles with mouse, pen, or touch; accidental near-zero drags are ignored.
- Use USGS 3DEP seamless as the single elevation source.
- Request bounded float32 GeoTIFF extracts from the USGS 3DEP seamless dynamic service on an adaptive approximately 10-meter grid, capped to the service and local-processing limits.
- Build a bounded derivative for the interactive Three.js terrain viewer.
- Adjust ArcGIS-style vertical exaggeration continuously from a flat `0×` surface through `4×`; `1×` preserves real-world vertical-to-horizontal scale.
- Toggle a translucent sea-level (`0 m`) reference plane and compare it with the terrain-floor elevation; the source vertical datum remains visible so the reference is not mistaken for a datum conversion.
- Inspect CRS, NoData, horizontal units, vertical units, and vertical datum without inventing missing metadata.
- Download one ZIP that expands into a folder containing the DEM GeoTIFF, JSON source evidence, and human-readable source documentation; raw GeoTIFF endpoints remain available for compatibility.
- Store every DEM in its own acquisition folder with JSON and Markdown source-evidence records and a SHA-256 checksum.

### NAIP aerial imagery

- Search U.S. locations or draw the same rectangle used by the other workflows.
- Query the Microsoft Planetary Computer STAC catalog for USDA National Agriculture Imagery Program (NAIP) acquisitions intersecting the area.
- Default to the newest single acquisition year that completely covers the area, choose a historical complete year, or fill each part from its newest published tile.
- Choose natural-color RGB or four-band RGB plus near-infrared output.
- Enforce a native-resolution pixel limit before reading remote imagery, then write a tiled, compressed AOI GeoTIFF with overviews and a bounded PNG preview.
- Preserve a JSON source-item manifest containing acquisition dates, source asset URLs, resolution, CRS, and selected tile identifiers.
- Store each aerial GeoTIFF, preview, source manifest, and human-readable source-evidence record in its own extraction folder, including a SHA-256 checksum.
- Download one ZIP that expands into a folder containing the aerial GeoTIFF, JSON source manifest, and human-readable source documentation; reopen or delete completed imagery from local history.

### OpenStreetMap features

- Search worldwide and retain named Polygon/MultiPolygon boundaries, or draw the same rectangle selection used by elevation.
- Choose an OSM tag key and an optional tag value, such as `building` or `amenity=school`.
- Query OSM through OSMnx/Overpass, split mixed geometries into separate feature classes, and write either an OpenFileGDB (`.gdb`) or GeoPackage (`.gpkg`) dataset.
- Create a new OSM dataset or add later tag extractions to any recent dataset in its original format.
- Download one ZIP containing the selected dataset and a required OSM attribution/ODbL notice.
- Reopen completed OSM exports from local history. Expanded datasets retain cumulative layer and extraction history.
- Open the Storage panel to clear reusable request cache or permanently delete individual saved outputs.

## Architecture

```text
React + TypeScript + Leaflet + Three.js
                    |
            one local FastAPI service
          /             |              \
 USGS 3DEP       USDA NAIP / STAC    OSMnx / Overpass
     |                  |              |
 source + preview   AOI GeoTIFF      GDB/GPKG + notice
          \             |             /
                SQLite local history
```

The three processing pipelines remain separate behind the API because their formats, licensing, and metadata rules differ. They share the user-facing search, map, bounding box, job progress, history, and launcher.

## First-time setup on Windows 11

Python 3.12 and Node.js are required.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt

cd ..\frontend
pnpm install
```

This project includes `frontend/.npmrc` for drives that do not support symbolic links.

## Run

Double-click `start.bat`. It starts the one backend and one browser UI, then opens <http://127.0.0.1:5173>. Double-click `stop.bat` when finished.

PowerShell users can run:

```powershell
.\start.ps1
.\stop.ps1
```

## Verify

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
pnpm run build
```

## Storage and metadata rules

- Each bounded USGS 3DEP seamless extract and its JSON/Markdown source evidence are grouped under `data/original/terrain/<dataset-id>/`; source dimensions are independent of the interactive preview setting.
- Elevation derivatives remain under `data/processed/` and are bounded to 128 × 128 cells for display.
- Each NAIP source-item manifest, clipped mosaic, bounded PNG preview, and Markdown source-evidence record is grouped under `data/processed/naip/<imagery-id>/`.
- OSM datasets, notices, and ZIP packages are written under `data/exports/`.
- OSMnx cache files are written under `data/cache/osmnx/`.
- Runtime logs are kept separately under `data/logs/`, so clearing cache is safe while Geospatial Extraction Studio is running.
- SQLite history is stored at `data/app.db`.
- Missing CRS/unit/datum metadata stays explicitly labeled as not declared.
- Do not commit downloaded elevation files, generated NAIP imagery, generated OSM exports, caches, the SQLite database, or build output.

Use the **Storage** button in the top bar to see disk usage. **Clear cache** removes only reusable OSM request responses; it does not remove completed terrain, NAIP, or OSM datasets. Saved terrain, NAIP, and OSM outputs can be deleted individually from the same panel, which also removes their local history entries.

## Service configuration

The defaults are suitable for modest, directly user-triggered local use. Public OSM and Planetary Computer services have usage policies and no SLA. Deployments with many users should configure an appropriate hosted or self-hosted provider.

Environment variables:

- `NOMINATIM_SEARCH_URL`
- `NOMINATIM_USER_AGENT`
- `NOMINATIM_MIN_INTERVAL_SECONDS` (do not reduce below `1.0` for public Nominatim)
- `OSM_EXTRACTOR_USER_AGENT`
- `OSM_EXTRACTOR_OVERPASS_URLS` (comma-separated)
- `OSM_EXTRACTOR_CACHE_DIR`
- `NAIP_STAC_SEARCH_URL` (optional STAC search endpoint; defaults to the Microsoft Planetary Computer `naip` collection)
- `NAIP_STAC_COLLECTION_URL` (collection metadata endpoint paired with the configured STAC search endpoint; required for license provenance)
- `NAIP_SIGN_URL` (optional asset-signing endpoint paired with the configured STAC catalog)
- `NAIP_MAX_OUTPUT_PIXELS` (default `250000000`; bounds native-resolution output size)
- `GES_BACKEND_PORT` (optional backend port; otherwise the launcher selects an available port from 8000 through 8020)
- `GES_LEGACY_DATA_DIRS` (optional semicolon-separated former application data folders)
- `VITE_OSM_TILE_URL` (optional custom tile template)
- `VITE_OSM_TILE_ATTRIBUTION` (visible provider credit; may contain Leaflet-compatible HTML)
- `VITE_OSM_TILE_LICENSE_URL` (direct HTTPS or HTTP link to the provider's controlling terms)
- `ELEVATION_DATA_DIR`

Custom map tiles are activated only when all three tile variables are set.
Incomplete configuration or a non-HTTP(S) tile/license URL stops application
startup instead of silently displaying unlicensed tiles. The configured credit
and a visible link to the provider's terms are displayed alongside a permanent
OpenStreetMap credit because place search and OSM extraction continue to use
OpenStreetMap data regardless of the tile provider. Confirm the provider's
current logo, token, caching, and usage-policy requirements before configuring
it.

NAIP catalog searches and imagery reads are user-triggered; availability,
throttling, and publication lag are controlled by the configured catalog
provider. The application records asset-, item-, and collection-level license
metadata and refuses extraction when terms are missing, when asset and item
declarations conflict, or when a legacy non-SPDX asset/item value such as
`proprietary` has no same-record license link. Raw catalog values
remain visible; linked terms are identified separately from legacy STAC syntax,
and actual conflicts must be verified before redistribution. “Latest” means the
newest item published in that catalog, not imagery that has been acquired but
not yet indexed.

The public Nominatim implementation is user-triggered, cached, rate-limited to at most one request per second, and provider-switchable without a code change. The map keeps visible provider attribution. Every OSM data export includes a separate attribution notice. The top-bar **Legal notices** link serves the notices bundled with this release.

## Maintenance status

The application source directory is named `Geospatial Extraction Studio`. Published source archives use the filesystem-friendly `Geospatial-Extraction-Studio` form as their top-level directory. This is the only maintained application. The earlier standalone elevation and OSM applications have been consolidated and removed; do not recreate or maintain separate copies of those implementations.

## Deliberate limits

- Elevation and manually drawn OSM rectangles enforce a 2,500 km² maximum. Named OSM place boundaries can be up to 10,000 km².
- NAIP availability searches are limited to 500 km², and extraction is additionally limited by estimated native-resolution pixels; the default is 250,000,000 pixels.
- “Latest complete” uses one acquisition year covering at least 99.5% of the rectangle. “Newest per tile” can mix acquisition dates and show seams.
- Elevation place search and extraction are U.S.-focused because USGS 3DEP seamless is the only elevation source.
- Public Overpass queries can time out for dense or relation-heavy selections; narrow the area or tag value when this occurs.
- Adding a feature class whose generated layer name already exists is rejected; choose another subtype or create a new OSM dataset.
- In-memory job progress resets on restart; completed elevation, NAIP, and OSM history persists in SQLite.
- Raw LAS/LAZ/COPC point-cloud viewing, user-supplied LiDAR import, polygon clipping, general vertical-datum transformation, and multi-user deployment remain future work. Geospatial Extraction Studio currently consumes the USGS 3DEP seamless DEM rather than storing full raw point clouds.

See `THIRD_PARTY_NOTICES.md` for dependency licenses, data attribution, and public-service policies.

## License and source releases

Geospatial Extraction Studio's original source code and documentation are
available under the Apache License 2.0. Downloaded data and generated datasets
retain their respective provider licenses; they are not relicensed under
Apache License 2.0 merely because this application downloaded, processed, or
exported them.

| Material | Governing terms |
| --- | --- |
| Original application source and documentation | Apache License 2.0 |
| Project logo files | Apache License 2.0 only to the extent protectable rights subsist; see `ASSET_LICENSES.md` |
| OpenStreetMap data and derived databases | Open Database License 1.0 and required attribution |
| USGS and USDA source data | Applicable source record, embedded metadata, and provider terms; generally public domain in the United States when authored solely by the U.S. government |
| Hosted APIs, tiles, and catalog services | Provider access and usage policies |
| Software dependencies and native libraries | Their respective package licenses |

See `THIRD_PARTY_NOTICES.md` and the source metadata saved with each dataset for
the controlling terms. Do not describe all application output as Apache-2.0 or
unrestricted.

Publish source releases from a clean checkout. Do not include `.venv`,
`node_modules`, `.pnpm-store`, package caches, `frontend/dist`, generated elevation, NAIP, or OSM
data, `data/app.db`, runtime logs, temporary files, or PDFs. Retain `LICENSE`,
`NOTICE`, `THIRD_PARTY_NOTICES.md`, `CONTENT_PROVENANCE.md`,
`ASSET_LICENSES.md`, `backend/requirements.lock.txt`, and
`frontend/pnpm-lock.yaml`. Contributions from other people should follow
`CONTRIBUTING.md` so the project retains a clear licensing record.

Before the first GitHub publication, initialize the repository locally and
review both the proposed source files and ignored files:

```powershell
git init -b main
git status --short
git status --short --ignored
```

Only stage reviewed source files. Do not use GitHub's browser upload to copy the
working folder wholesale. Before distributing a bundled executable or
installer, perform a separate dependency-license review and preserve the
license directories and notices for every included binary and native library.

## Windows binary installer

The installer build is intentionally separate from the source-archive build. It creates a PyInstaller **onedir** application in which native libraries remain separate files, then wraps that directory in a per-user NSIS installer. The installed FastAPI process serves the production frontend itself; end users do not need Python, Node.js, Vite, or an OpenAI connection.

```powershell
.\packaging\build-installer.ps1
```

A publication build is fail-closed. It will not write an installer to `release/` while any bundled native library is unmatched in `packaging/native-components.json` or lacks an `approved` status backed by hash-pinned evidence for the exact wheel build. The generated license bundle records every DLL's SHA-256 digest and wheel origin and includes `NATIVE_REVIEW_SUMMARY.md`. The engineering override exists only for smoke testing and writes under `build/installer/`, never the release directory:

```powershell
.\packaging\build-installer.ps1 -EngineeringBuild -SkipNsis
```

The current pinned build passes this native evidence gate for all 73 DLLs.
Publication no longer uses whichever Python happens to be installed. It
downloads the immutable Astral `python-build-standalone` 20260303 archive for
CPython 3.12.13, verifies the archive and combined-license SHA-256 values in
`packaging/runtime-components.json`, freshly extracts it, and builds from a
virtual environment tied to that exact runtime. After PyInstaller completes,
`packaging/audit_frozen_binary.py` inventories every `.exe`, `.dll`, and `.pyd`
and every pure-Python module in the finished application. It independently
matches the executable's code sections to a hash-pinned PyInstaller bootloader,
compares its embedded archives with the controlled build artifacts, and maps
each PYZ module to the verified runtime archive, application source, or an
approved distribution whose source hash matches its installed `RECORD`.
Setuptools is excluded because it is not a runtime dependency. An unrecognized
native file or Python module, a missing pinned runtime DLL, or changed executable
or archive content blocks smoke testing and publication. The installed legal
bundle includes the native, pure-Python, and executable-provenance inventories,
runtime policy and notices, and exact PyInstaller licenses.

The frontend legal step derives the complete production dependency graph from
the pnpm lock/install state and compares it with
`packaging/frontend-components.json`. Package versions, declared licenses, and
license-file hashes must match. The final frozen-app audit verifies those copied
files and ships `FRONTEND_BUNDLE_INVENTORY.json` with the installed legal bundle.
All 38 pinned Python runtime packages must also match approved canonical license
classifications and exact license-file hashes in `packaging/python-components.json`.
Certifi's exact MPL-2.0 source distribution is retained, hash-verified, and
included with recipient-facing source-availability instructions.
Corresponding source and pinned build recipes for the LGPL/MPL components are
included in the generated license bundle. Microsoft webpages are linked rather
than redistributed. Microsoft runtime approval is accepted only on the exact
Visual Studio 2022 release host recorded by policy, with its installed REDIST
pointer digest verified and its open-source-project entitlement record present.

Installed program files live under `%LOCALAPPDATA%\Programs\Geospatial Extraction Studio`. Writable datasets, the SQLite database, caches, logs, and exports live under `%LOCALAPPDATA%\Geospatial Extraction Studio\data` and remain after uninstall. See `packaging/README.md` for the release gates and signing requirement.
On Windows, create the filtered source archive with:

```powershell
.\package-source.ps1 -Destination ..\Geospatial-Extraction-Studio-source-0.4.0.zip
```

The script refuses to overwrite an existing archive, verifies every native
notice and corresponding-source artifact referenced by the evidence registry,
and writes a `.sha256` checksum beside the archive.
