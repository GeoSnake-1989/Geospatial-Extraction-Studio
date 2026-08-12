from __future__ import annotations

import fnmatch
import hashlib
import json
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
