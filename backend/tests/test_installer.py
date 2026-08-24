from __future__ import annotations

import fnmatch
import hashlib
import json
import logging.config
import sys
from importlib import metadata
from pathlib import Path

import pytest

from app import config, launcher


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_installed_data_root_uses_local_app_data(tmp_path: Path):
    assert config.default_data_root(
        frozen=True,
        local_app_data=str(tmp_path),
        project_root=Path("unused"),
    ) == tmp_path / "Geospatial Extraction Studio" / "data"


def test_installed_data_root_requires_explicit_windows_metadata():
    with pytest.raises(RuntimeError, match="LOCALAPPDATA"):
        config.default_data_root(
            frozen=True,
            local_app_data=None,
            project_root=Path("unused"),
        )


def test_installer_runtime_lock_excludes_development_server_extras():
    lock = (PROJECT_ROOT / "backend" / "requirements-installer.lock.txt").read_text(encoding="utf-8").lower()
    for excluded in ("pytest==", "httptools==", "watchfiles==", "websockets==", "pyyaml=="):
        assert excluded not in lock
    assert "uvicorn==0.51.0" in lock


def test_python_release_policy_approves_exact_lock_and_license_evidence():
    locked = {
        line.split("==", 1)[0].replace("_", "-").lower(): line.split("==", 1)[1]
        for line in (
            PROJECT_ROOT / "backend" / "requirements-installer.lock.txt"
        ).read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    policy = json.loads(
        (PROJECT_ROOT / "packaging" / "python-components.json").read_text(
            encoding="utf-8"
        )
    )
    assert policy["schema_version"] == 1
    entries = {entry["name"]: entry for entry in policy["components"]}
    assert set(entries) == set(locked)
    assert len(entries) == 38
    for name, version in locked.items():
        entry = entries[name]
        assert entry["version"] == version
        assert entry["status"] == "approved"
        assert entry["license"] and entry["license"].upper() != "UNKNOWN"
        distribution = metadata.distribution(entry["distribution"])
        assert distribution.version == version
        assert entry["license_evidence"]
        for evidence in entry["license_evidence"]:
            path = Path(distribution.locate_file(evidence["path"]))
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
            text = path.read_text(encoding="utf-8", errors="replace")
            assert all(marker in text for marker in evidence["contains"])
        source_required = any(
            marker in entry["license"]
            for marker in ("MPL-", "LGPL-", "GPL-", "AGPL-", "EPL-", "CDDL-")
        )
        source_evidence = entry.get("source_evidence", [])
        if source_required:
            assert source_evidence
        for evidence in source_evidence:
            assert evidence["source_url"].startswith("https://")
            path = PROJECT_ROOT / evidence["repository_path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]


def test_visual_studio_entitlement_is_scoped_to_this_open_source_project():
    entitlement = json.loads(
        (PROJECT_ROOT / "packaging" / "visual-studio-entitlement.json").read_text(
            encoding="utf-8"
        )
    )
    assert entitlement["use_basis"] == "osi_approved_open_source_project"
    assert entitlement["project_license"] == "Apache-2.0"
    assert entitlement["attested_by"] == "GeoSnake1989"
    project_license = PROJECT_ROOT / entitlement["project_license_path"]
    assert hashlib.sha256(project_license.read_bytes()).hexdigest() == entitlement[
        "project_license_sha256"
    ]
    assert "proprietary derivative" in entitlement["statement"]


def test_native_manifest_covers_every_wheel_dll_once():
    manifest = json.loads((PROJECT_ROOT / "packaging" / "native-components.json").read_text(encoding="utf-8"))
    entries = manifest["components"]
    site_packages = Path(config.__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        pytest.skip("Windows wheel environment is not available")
    for path in sorted(directory_file for directory in site_packages.glob("*.libs") for directory_file in directory.glob("*.dll")):
        matches = [entry["component"] for entry in entries if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in entry["patterns"])]
        assert len(matches) == 1, f"{path.name} matched {matches}"


def test_native_manifest_pins_wheel_origins_and_records_blockers():
    manifest = json.loads((PROJECT_ROOT / "packaging" / "native-components.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert set(manifest["default_blocking_reasons"]) == {"notice_required", "review_required"}

    site_packages = Path(config.__file__).resolve().parents[1] / ".venv" / "Lib" / "site-packages"
    if not site_packages.is_dir():
        pytest.skip("Windows wheel environment is not available")

    wheel_directories = {path.name for path in site_packages.glob("*.libs")}
    assert wheel_directories == set(manifest["wheel_bundles"])
    for wheel_directory, bundle in manifest["wheel_bundles"].items():
        distribution = metadata.distribution(bundle["distribution"])
        assert distribution.version == bundle["version"], wheel_directory
        evidence = bundle["build_evidence"]
        evidence_path = Path(distribution.locate_file(evidence["path"]))
        assert evidence_path.is_file(), wheel_directory
        assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == evidence["sha256"]
        evidence_text = evidence_path.read_text(encoding="utf-8")
        for marker in evidence["contains"]:
            assert marker in evidence_text

    for entry in manifest["components"]:
        assert entry["status"] in {"approved", "notice_required", "review_required"}
        if entry["status"] == "approved":
            assert entry.get("approval"), entry["component"]
        else:
            reason = entry.get("blocking_reason") or manifest["default_blocking_reasons"][entry["status"]]
            assert reason.strip(), entry["component"]


def test_native_approvals_are_bound_to_exact_wheel_license_evidence():
    manifest = json.loads((PROJECT_ROOT / "packaging" / "native-components.json").read_text(encoding="utf-8"))
    registry = json.loads(
        (PROJECT_ROOT / manifest["evidence_registry"]).read_text(encoding="utf-8")
    )
    approved = [entry for entry in manifest["components"] if entry["status"] == "approved"]
    assert len(approved) == len(manifest["components"]) == 33
    for entry in approved:
        approval = entry["approval"]
        assert approval["covered_wheel_directories"]
        assert isinstance(approval["source_offer_required"], bool)
        evidence_items = approval.get("license_evidence") or [
            registry["licenses"][identifier]
            for identifier in approval["license_evidence_ids"]
        ]
        for evidence in evidence_items:
            if "repository_path" in evidence:
                path = PROJECT_ROOT / evidence["repository_path"]
                assert evidence["source_url"].startswith("https://")
                assert (
                    len(evidence.get("source_commit", "")) == 40
                    or evidence.get("source_archive_sha512")
                    or evidence.get("retrieved_on")
                )
            else:
                distribution = metadata.distribution(evidence["distribution"])
                path = Path(distribution.locate_file(evidence["path"]))
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
            text = path.read_text(encoding="utf-8")
            for marker in evidence["contains"]:
                assert marker in text
        source_items = [
            registry["sources"][identifier]
            for identifier in approval.get("source_evidence_ids", [])
        ]
        if approval["source_offer_required"]:
            assert source_items
        for evidence in source_items:
            path = PROJECT_ROOT / evidence["repository_path"]
            assert path.is_file()
            assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]


def test_microsoft_evidence_links_to_terms_without_copying_webpages():
    manifest = json.loads(
        (PROJECT_ROOT / "packaging" / "native-components.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (PROJECT_ROOT / "packaging" / "native-evidence-registry.json").read_text(
            encoding="utf-8"
        )
    )
    microsoft = next(
        entry for entry in manifest["components"]
        if entry["component"] == "Microsoft Visual C++ Runtime"
    )
    assert microsoft["approval"]["license_evidence_ids"] == ["microsoft-runtime-audit"]
    assert microsoft["approval"]["system_redist_sha256"]
    audit = registry["licenses"]["microsoft-runtime-audit"]
    assert audit["repository_path"].endswith("REDISTRIBUTION_AUDIT.md")
    assert audit["source_url"].startswith("https://learn.microsoft.com/")
    microsoft_directory = PROJECT_ROOT / "packaging" / "native-evidence" / "microsoft"
    assert not list(microsoft_directory.rglob("*.html"))


def test_collector_emits_hashes_and_a_human_readable_review():
    collector = (PROJECT_ROOT / "packaging" / "collect_licenses.py").read_text(encoding="utf-8")
    assert "'sha256': sha256_file(binary_path)" in collector
    assert "'version_probe': version_probe" in collector
    assert "NATIVE_REVIEW_SUMMARY.md" in collector
    assert "PYTHON_COMPONENT_POLICY.json" in collector
    assert "verify_approval_evidence" in collector
    assert "verify_source_evidence" in collector
    assert "verify_system_evidence" in collector
    assert "verify_python_approval" in collector
    assert "load_python_policy" in collector
    assert "verify_python_source_evidence" in collector
    assert "PYTHON_SOURCE_REQUIRED_MARKERS" in collector


def test_release_runtime_is_an_immutable_approved_artifact():
    manifest = json.loads(
        (PROJECT_ROOT / 'packaging' / 'runtime-components.json').read_text(
            encoding='utf-8'
        )
    )
    assert manifest['schema_version'] == 1
    assert manifest['status'] == 'approved'
    assert manifest['distribution'] == 'astral-python-build-standalone'
    assert manifest['release'] == '20260303'
    assert manifest['python_version'] == '3.12.13'
    assert manifest['archive']['url'].startswith('https://github.com/astral-sh/')
    assert len(manifest['archive']['sha256']) == 64
    assert manifest['combined_license']['url'].startswith(
        'https://raw.githubusercontent.com/astral-sh/'
    )
    assert len(manifest['combined_license']['sha256']) == 64
    components = {entry['name']: entry for entry in manifest['components']}
    assert {'CPython', 'libffi', 'OpenSSL', 'SQLite'} <= components.keys()
    critical = {entry['path']: entry for entry in manifest['critical_files']}
    for path in (
        'python3.dll',
        'python312.dll',
        'vcruntime140.dll',
        'vcruntime140_1.dll',
        'DLLs/libcrypto-3-x64.dll',
        'DLLs/libssl-3-x64.dll',
        'DLLs/libffi-8.dll',
        'DLLs/sqlite3.dll',
    ):
        assert len(critical[path]['sha256']) == 64


def test_publication_build_freshly_extracts_and_audits_the_pinned_runtime():
    preparer = (PROJECT_ROOT / 'packaging' / 'prepare-runtime.ps1').read_text(
        encoding='utf-8'
    )
    builder = (PROJECT_ROOT / 'packaging' / 'build-installer.ps1').read_text(
        encoding='utf-8'
    )
    auditor = (PROJECT_ROOT / 'packaging' / 'audit_frozen_binary.py').read_text(
        encoding='utf-8'
    )
    assert 'Invoke-WebRequest -Uri $manifest.archive.url' in preparer
    assert 'Pinned runtime archive hash mismatch' in preparer
    assert 'Remove-Item -LiteralPath (Assert-BuildChild $runtimeRoot)' in preparer
    assert '& tar -xf $archivePath' in preparer
    assert 'prepare-runtime.ps1' in builder
    assert '--runtime-manifest' in builder
    assert '--runtime-archive' in builder
    assert 'audit_frozen_binary.py' in builder
    assert builder.index('PyInstaller --noconfirm') < builder.index('audit_frozen_binary.py')
    assert builder.index('audit_frozen_binary.py') < builder.index('$smokePort = $null')
    assert 'NATIVE_SUFFIXES' in auditor
    assert 'Build runtime lacks the verified pinned-archive marker' in auditor
    assert 'Pinned runtime archive is missing or has the wrong hash' in auditor
    assert 'Unrecognized frozen native files' in auditor
    assert 'Frozen application is missing pinned runtime files' in auditor
    assert 'FINAL_BINARY_INVENTORY.json' in auditor
    assert 'PURE_PYTHON_INVENTORY.json' in auditor
    assert 'EXECUTABLE_PROVENANCE.json' in auditor
    assert 'FRONTEND_BUNDLE_INVENTORY.json' in auditor
    assert 'Embedded PYZ module inventory differs' in auditor
    assert 'Unapproved Python distribution in embedded PYZ' in auditor
    assert "project_root / 'backend' / 'app'" in auditor
    assert 'Generated executable does not retain the pinned bootloader code sections' in auditor
    assert 'Frozen frontend license directories differ from approved policy' in auditor
    assert '--pyz-toc' in builder
    assert '--exe-toc' in builder
    assert '--frontend-manifest' in builder

    spec = (PROJECT_ROOT / 'packaging' / 'GeospatialExtractionStudio.spec').read_text(
        encoding='utf-8'
    )
    assert '"setuptools"' in spec
    assert '"_distutils_hack"' in spec


def test_pyinstaller_toolchain_and_embedded_licenses_are_exactly_pinned():
    requirements = {
        line.strip()
        for line in (PROJECT_ROOT / 'backend' / 'requirements-build.txt').read_text(
            encoding='utf-8'
        ).splitlines()
        if line.strip() and not line.startswith('#')
    }
    assert requirements == {
        'altgraph==0.17.5',
        'pefile==2024.8.26',
        'pyinstaller==6.22.0',
        'pyinstaller-hooks-contrib==2026.6',
        'pywin32-ctypes==0.2.3',
        'setuptools==84.0.0',
    }
    manifest = json.loads(
        (PROJECT_ROOT / 'packaging' / 'build-components.json').read_text(
            encoding='utf-8'
        )
    )
    assert manifest['schema_version'] == 1
    assert {entry['distribution'] for entry in manifest['components']} == {
        'pyinstaller',
        'pyinstaller-hooks-contrib',
    }
    assert all(len(entry['license_sha256']) == 64 for entry in manifest['components'])
    assert {entry['path'] for entry in manifest['pyinstaller_bootloaders']} == {
        'PyInstaller/bootloader/Windows-64bit-intel/run.exe',
        'PyInstaller/bootloader/Windows-64bit-intel/runw.exe',
    }
    assert all(
        len(entry['sha256']) == 64 for entry in manifest['pyinstaller_bootloaders']
    )


def test_corresponding_source_includes_rebuild_and_replacement_instructions():
    instructions = (
        PROJECT_ROOT / "packaging" / "native-source" / "README.md"
    ).read_text(encoding="utf-8")
    for requirement in (
        "THIRD_PARTY_COMPONENTS.json",
        "replace",
        "ABI-compatible",
        "GEOS",
        "libiconv",
    ):
        assert requirement.lower() in instructions.lower()


def test_certifi_source_availability_is_explicit_and_hash_pinned():
    instructions = (
        PROJECT_ROOT / "packaging" / "python-source" / "README.md"
    ).read_text(encoding="utf-8")
    for requirement in (
        "Certifi 2026.6.17",
        "Source Code Form",
        "MPL-2.0",
        "024c88eeec92ca068db80f02b8b07c9cef7b9fe261d1d535abfd5abd6f6af432",
    ):
        assert requirement in instructions


def test_native_version_audit_has_queries_for_core_permissive_components():
    audit = (PROJECT_ROOT / "packaging" / "inspect_native_versions.py").read_text(encoding="utf-8")
    for function in (
        "curl_version",
        "XML_ExpatVersion",
        "json_c_version",
        "OpenSSL_version",
        "sqlite3_libversion",
        "ZSTD_versionString",
    ):
        assert function in audit


def test_launcher_validates_configured_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GES_BACKEND_PORT", "70000")
    with pytest.raises(RuntimeError, match="between 1 and 65535"):
        launcher.configured_port()


def test_launcher_logging_does_not_require_console_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    config = launcher.uvicorn_log_config(tmp_path)

    assert config["handlers"]["default"]["class"] == "logging.FileHandler"
    assert config["handlers"]["default"]["filename"] == str(tmp_path / "application.log")
    assert "()" not in config["formatters"]["default"]

    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    logging.config.dictConfig(config)
    logging.getLogger("uvicorn.error").info("windowed startup test")
    logging.shutdown()

    assert "windowed startup test" in (tmp_path / "application.log").read_text(encoding="utf-8")


def test_portable_builder_reuses_audited_onedir_and_is_fail_closed():
    builder = (PROJECT_ROOT / "packaging" / "build-portable.ps1").read_text(encoding="utf-8")
    source_packager = (PROJECT_ROOT / "package-source.ps1").read_text(encoding="utf-8")

    assert "Refusing to publish a portable package from a dirty working tree" in builder
    assert "tag --points-at" in builder
    assert "$buildArguments = @{ SkipNsis = $true }" in builder
    assert "build-installer.ps1" in builder
    installer_builder = (
        PROJECT_ROOT / "packaging" / "build-installer.ps1"
    ).read_text(encoding="utf-8")
    assert "Created and smoke-tested one-folder application" in installer_builder
    assert "exit 0" not in installer_builder
    assert "EngineeringBuild" not in builder
    assert "Compress-Archive" in builder
    assert "Expand-Archive" in builder
    assert "extracted_executable_digest" in builder
    assert "package-source.ps1" in builder
    assert "build-portable.ps1" in source_packager
