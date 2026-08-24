import json
import re
from importlib import metadata
from pathlib import Path

from app import main


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEVELOPMENT_ONLY = {"pytest"}
NOTICE_NAMES = {
    "fastapi": "FastAPI",
    "uvicorn": "Uvicorn",
    "httpx": "HTTPX",
    "requests": "Requests",
    "numpy": "NumPy",
    "rasterio": "Rasterio",
    "pydantic": "Pydantic",
    "python-multipart": "python-multipart",
    "osmnx": "OSMnx",
    "geopandas": "GeoPandas",
    "pyogrio": "Pyogrio",
}


def requirement_name(line: str) -> str:
    return re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_requirements() -> dict[str, str]:
    lockfile = PROJECT_ROOT / "backend" / "requirements.lock.txt"
    entries: dict[str, str] = {}
    for line in lockfile.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, separator, version = line.partition("==")
        assert separator and version, f"Unpinned lockfile entry: {line}"
        entries[canonical_name(name)] = version
    return entries


def test_all_direct_runtime_dependencies_are_in_third_party_notices():
    requirements = (PROJECT_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    notices = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").lower()

    runtime_dependencies = {
        requirement_name(line)
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    } - DEVELOPMENT_ONLY

    missing = sorted(name for name in runtime_dependencies if name not in notices)
    assert not missing, f"Runtime dependencies missing from THIRD_PARTY_NOTICES.md: {missing}"


def test_direct_runtime_dependencies_are_pinned_and_notice_versions_match():
    requirements = (PROJECT_ROOT / "backend" / "requirements.txt").read_text(encoding="utf-8")
    notices = (PROJECT_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    runtime_dependencies = {
        canonical_name(requirement_name(line))
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    } - DEVELOPMENT_ONLY
    locked = locked_requirements()

    missing = sorted(runtime_dependencies - locked.keys())
    assert not missing, f"Direct runtime dependencies missing from lockfile: {missing}"

    for package_name in sorted(runtime_dependencies):
        locked_version = locked[package_name]
        assert metadata.version(package_name) == locked_version
        display_name = NOTICE_NAMES[package_name]
        assert f"| {display_name} | {locked_version} |" in notices


def test_lockfile_matches_the_complete_active_environment():
    for package_name, locked_version in locked_requirements().items():
        assert metadata.version(package_name) == locked_version


def test_release_version_records_match():
    frontend_manifest = (PROJECT_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    version_match = re.search(r'"version"\s*:\s*"([^"]+)"', frontend_manifest)
    assert version_match, "Frontend package version is missing"
    release_version = version_match.group(1)

    lockfile_header = (PROJECT_ROOT / "backend" / "requirements.lock.txt").read_text(
        encoding="utf-8"
    ).splitlines()[0]
    packager = (PROJECT_ROOT / "package-source.ps1").read_text(encoding="utf-8")

    assert main.app.version == release_version
    assert f"{release_version} release." in lockfile_header
    assert f"source-{release_version}.zip" in packager


def test_excluded_research_pdfs_are_not_present():
    assert not list(PROJECT_ROOT.glob("*.pdf"))


def test_public_release_governance_documents_are_present():
    contributing = (PROJECT_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    asset_licenses = (PROJECT_ROOT / "ASSET_LICENSES.md").read_text(encoding="utf-8")

    assert "Developer Certificate of Origin" in contributing
    assert "Apache License 2.0" in asset_licenses
    assert "confirmed this authorization on August 7, 2026" in asset_licenses


def test_legal_documents_are_available_to_the_api():
    expected = {
        "license": "LICENSE",
        "notice": "NOTICE",
        "third-party-notices": "THIRD_PARTY_NOTICES.md",
        "content-provenance": "CONTENT_PROVENANCE.md",
        "asset-licenses": "ASSET_LICENSES.md",
    }

    for slug, filename in expected.items():
        response = main.legal_document(slug)
        assert Path(response.path).resolve() == (PROJECT_ROOT / filename).resolve()
        assert Path(response.path).stat().st_size > 0


def test_ai_logo_is_recorded_as_branding_not_copyrighted_project_material():
    asset_licenses = (PROJECT_ROOT / "ASSET_LICENSES.md").read_text(encoding="utf-8")
    provenance = (PROJECT_ROOT / "CONTENT_PROVENANCE.md").read_text(encoding="utf-8")
    notice = (PROJECT_ROOT / "NOTICE").read_text(encoding="utf-8")
    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    assert "makes no copyright claim" in asset_licenses
    assert "grants no copyright license" in asset_licenses
    assert "does not grant trademark permission" in asset_licenses
    assert "licenses those rights under the Apache License" not in asset_licenses
    assert "no copyright claim\nor copyright-license assertion" in provenance
    assert "logo files are branding, not\ncopyrighted project material" in notice
    assert "no copyright claim or copyright license" in readme


def test_source_release_excludes_generated_data_and_package_caches():
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    packager = (PROJECT_ROOT / "package-source.ps1").read_text(encoding="utf-8")

    for expected in {
        "/.pnpm-store/",
        "/build/",
        "data/app.db",
        "data/original/*",
        "data/processed/*",
        "data/cache/*",
        "data/logs/*",
        "data/exports/*",
    }:
        assert expected in gitignore
    assert "^\\.pnpm-store" in packager
    assert "tmp|release|build" in packager
    assert "requirements-installer.lock.txt" in packager
    assert "python-components.json" in packager
    assert "visual-studio-entitlement.json" in packager
    assert "python-source\\README.md" in packager
    assert "Python source evidence referenced by the release is missing" in packager
    assert "SOURCE-REVISION.txt" in packager
    assert "status --porcelain --untracked-files=all" in packager
    assert "ls-files" in packager
    assert "not tagged v0.4.3" in packager

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "Downloaded data and generated datasets" in readme


    assert 'runtime-components.json' in packager
    assert 'build-components.json' in packager
    assert 'frontend-components.json' in packager
    assert 'prepare-runtime.ps1' in packager
    assert 'audit_frozen_binary.py' in packager

    installer_builder = (PROJECT_ROOT / 'packaging' / 'build-installer.ps1').read_text(
        encoding='utf-8'
    )
    assert 'Refusing to publish an installer from a dirty working tree' in installer_builder
    assert 'tag --points-at' in installer_builder
    assert "'package-source.ps1'" in installer_builder
    assert '$provenance.application_source = $applicationSourceProvenance' in installer_builder
    assert 'archive_sha256 = $sourceArchiveHash' in installer_builder


def test_frontend_notices_follow_the_locked_approved_production_graph():
    policy = json.loads(
        (PROJECT_ROOT / 'packaging' / 'frontend-components.json').read_text(
            encoding='utf-8'
        )
    )
    assert policy['schema_version'] == 1
    assert policy['status'] == 'approved'
    assert len(policy['lockfile_sha256']) == 64
    assert {item['name'] for item in policy['components']} == {
        'leaflet',
        'lucide-react',
        'react',
        'react-dom',
        'scheduler',
        'three',
    }
    assert all(len(item['license_sha256']) == 64 for item in policy['components'])

    collector = (
        PROJECT_ROOT / 'frontend' / 'scripts' / 'copy-legal-notices.mjs'
    ).read_text(encoding='utf-8')
    assert "['list', '--prod', '--depth', 'Infinity', '--json']" in collector
    assert 'Frontend production graph differs from approved policy' in collector
    assert 'Frontend lockfile changed without an approved component-policy update' in collector
    assert 'runtimePackages = [' not in collector


def test_custom_tile_configuration_requires_visible_terms():
    selector = (
        PROJECT_ROOT / "frontend" / "src" / "components" / "MapSelector.tsx"
    ).read_text(encoding="utf-8")
    example = (PROJECT_ROOT / "frontend" / ".env.example").read_text(encoding="utf-8")

    assert "VITE_OSM_TILE_LICENSE_URL" in selector
    assert "Incomplete custom tile configuration" in selector
    assert "Tile provider terms" in selector
    assert "checkedHttpUrl" in selector
    for setting in (
        "VITE_OSM_TILE_URL=",
        "VITE_OSM_TILE_ATTRIBUTION=",
        "VITE_OSM_TILE_LICENSE_URL=",
    ):
        assert setting in example
