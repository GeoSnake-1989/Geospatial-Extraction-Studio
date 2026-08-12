import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


project_root = Path.cwd()
frontend_dist = project_root / "frontend" / "dist"
license_bundle = project_root / "build" / "installer" / "licenses"

if not frontend_dist.joinpath("index.html").is_file():
    raise SystemExit("frontend/dist is missing; run the frontend production build first")
if not license_bundle.joinpath("THIRD_PARTY_COMPONENTS.json").is_file():
    raise SystemExit("installer license bundle is missing; run collect_licenses.py first")

datas = copy_metadata("osmnx") + [
    (str(frontend_dist), "frontend/dist"),
    (str(license_bundle), "licenses"),
]
for filename in (
    "LICENSE",
    "NOTICE",
    "THIRD_PARTY_NOTICES.md",
    "CONTENT_PROVENANCE.md",
    "ASSET_LICENSES.md",
):
    datas.append((str(project_root / filename), "."))

binaries = []
hiddenimports = [
    "pyogrio._err",
    "pyogrio._geometry",
    "pyogrio._io",
    "pyogrio._ogr",
    "pyogrio._vsi",
    "uvicorn.lifespan.on",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.h11_impl",
]
for package in ("rasterio", "pyogrio"):
    hiddenimports += collect_submodules(package, filter=lambda name: ".tests" not in name)

for package in ("rasterio", "pyogrio", "pyproj", "shapely", "geopandas", "osmnx"):
    datas += collect_data_files(package, excludes=["**/tests/**", "**/test/**"])

a = Analysis(
    [str(project_root / "backend" / "app" / "launcher.py")],
    pathex=[str(project_root / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "iniconfig",
        "httptools",
        "pluggy",
        "pytest",
        "Pygments",
        "setuptools",
        "_distutils_hack",
        "watchfiles",
        "websockets",
        "yaml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GeospatialExtractionStudio",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=os.getenv("GES_BUILD_CONSOLE") == "1",
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="GeospatialExtractionStudio",
)
