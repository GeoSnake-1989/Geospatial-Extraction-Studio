from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

from inspect_native_versions import query_version


LICENSE_NAMES = re.compile(r"^(license|licence|copying|notice|copyright|authors)([._-].*)?$", re.I)
APPROVED_STATUS = 'approved'
REVIEW_STATUSES = {APPROVED_STATUS, 'notice_required', 'review_required'}
PYTHON_SOURCE_REQUIRED_MARKERS = ('MPL-', 'LGPL-', 'GPL-', 'AGPL-', 'EPL-', 'CDDL-')


def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def locked_requirements(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator or not version:
            raise SystemExit(f"Installer requirement is not exactly pinned: {line}")
        result[canonical_name(name)] = version
    return result


def copy_distribution_licenses(distribution: metadata.Distribution, destination: Path) -> list[str]:
    copied: list[str] = []
    package_destination = destination / f"{distribution.metadata['Name']}-{distribution.version}"
    for entry in distribution.files or ():
        relative = Path(str(entry))
        if not any(LICENSE_NAMES.match(part) for part in relative.parts):
            continue
        source = Path(distribution.locate_file(entry))
        if not source.is_file():
            continue
        if any(part in {"..", "."} for part in relative.parts):
            raise SystemExit(f"Unsafe license path recorded for {distribution.metadata['Name']}: {relative}")
        target = package_destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination)).replace("\\", "/"))
    if not copied:
        raise SystemExit(f"No license or notice file was found for {distribution.metadata['Name']}")
    return sorted(set(copied))


def verify_python_approval(
    entry: dict,
    distribution: metadata.Distribution,
) -> None:
    component = str(entry.get('name') or '')
    required = {
        'name', 'distribution', 'version', 'status', 'license', 'license_evidence'
    }
    missing = sorted(required - entry.keys())
    if missing:
        raise SystemExit(
            f'Python policy for {component or "unknown component"} lacks: '
            + ', '.join(missing)
        )
    if entry['status'] != APPROVED_STATUS:
        raise SystemExit(f'Python component is not approved for release: {component}')
    if canonical_name(str(entry['distribution'])) != canonical_name(
        str(distribution.metadata['Name'])
    ):
        raise SystemExit(f'Python distribution identity changed: {component}')
    if str(entry['version']) != distribution.version:
        raise SystemExit(
            f'Python policy version changed for {component}: '
            f'{distribution.version} != {entry["version"]}'
        )
    if not str(entry['license']).strip() or str(entry['license']).upper() == 'UNKNOWN':
        raise SystemExit(f'Python component has no approved license: {component}')
    evidence_items = entry['license_evidence']
    if not isinstance(evidence_items, list) or not evidence_items:
        raise SystemExit(f'Python component lacks license evidence: {component}')
    actual_license_paths = {
        Path(str(item)).as_posix()
        for item in distribution.files or ()
        if any(LICENSE_NAMES.match(part) for part in Path(str(item)).parts)
        and Path(distribution.locate_file(item)).is_file()
    }
    policy_paths: set[str] = set()
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            raise SystemExit(f'Malformed Python license evidence: {component}')
        missing = sorted({'path', 'sha256', 'contains'} - evidence.keys())
        if missing:
            raise SystemExit(
                f'Python license evidence for {component} lacks: {", ".join(missing)}'
            )
        relative = Path(str(evidence['path']))
        if relative.is_absolute() or '..' in relative.parts:
            raise SystemExit(f'Unsafe Python license evidence path: {component}')
        source = Path(distribution.locate_file(str(evidence['path']))).resolve()
        if not source.is_file():
            raise SystemExit(f'Python license evidence is missing: {component}: {source}')
        if sha256_file(source) != str(evidence['sha256']).lower():
            raise SystemExit(f'Python license evidence hash changed: {component}')
        text = source.read_text(encoding='utf-8', errors='replace')
        absent = [str(marker) for marker in evidence['contains'] if str(marker) not in text]
        if absent:
            raise SystemExit(
                f'Python license evidence markers changed for {component}: '
                + ', '.join(absent)
            )
        policy_paths.add(relative.as_posix())
    if policy_paths != actual_license_paths:
        raise SystemExit(
            f'Python license-file inventory changed for {component}; review is required'
        )


def verify_python_source_evidence(
    entry: dict,
    destination: Path,
    project_root: Path,
) -> list[str]:
    component = str(entry['name'])
    license_expression = str(entry['license'])
    source_required = any(
        marker in license_expression for marker in PYTHON_SOURCE_REQUIRED_MARKERS
    )
    evidence_items = entry.get('source_evidence') or []
    if source_required and not evidence_items:
        raise SystemExit(
            f'Python component requires corresponding source but none is retained: {component}'
        )
    copied: list[str] = []
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            raise SystemExit(f'Malformed Python source evidence: {component}')
        missing = sorted({'repository_path', 'source_url', 'sha256'} - evidence.keys())
        if missing:
            raise SystemExit(
                f'Python source evidence for {component} lacks: {", ".join(missing)}'
            )
        if not str(evidence['source_url']).startswith('https://'):
            raise SystemExit(f'Python source URL must use HTTPS: {component}')
        source = (project_root / str(evidence['repository_path'])).resolve()
        if project_root not in source.parents or not source.is_file():
            raise SystemExit(f'Python source evidence is missing or unsafe: {source}')
        if sha256_file(source) != str(evidence['sha256']).lower():
            raise SystemExit(f'Python source evidence hash changed: {component}')
        target = destination / safe_component_directory(component) / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination.parent)).replace('\\', '/'))
    return copied


def load_python_policy(path: Path, locked: dict[str, str]) -> dict[str, dict]:
    policy = json.loads(path.read_text(encoding='utf-8'))
    if policy.get('schema_version') != 1:
        raise SystemExit('python-components.json must use schema_version 1')
    for required in ('reviewed_on', 'approval_authority', 'components'):
        if not policy.get(required):
            raise SystemExit(f'Python policy lacks: {required}')
    entries = policy['components']
    if not isinstance(entries, list):
        raise SystemExit('Python policy components must be a list')
    by_name: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise SystemExit('Malformed Python policy component')
        name = canonical_name(str(entry.get('name') or ''))
        if not name or name in by_name:
            raise SystemExit(f'Duplicate or empty Python policy component: {name!r}')
        by_name[name] = entry
    if set(by_name) != set(locked):
        missing = sorted(set(locked) - set(by_name))
        extra = sorted(set(by_name) - set(locked))
        raise SystemExit(
            'Python policy does not exactly match the installer lock; '
            f'missing={missing}, extra={extra}'
        )
    return by_name


def verify_approval_evidence(
    entry: dict,
    destination: Path,
    project_root: Path,
) -> list[str]:
    component = str(entry['component'])
    approval = entry.get('approval')
    required = {
        'approved_on', 'approval_authority', 'basis',
        'covered_wheel_directories', 'license_evidence',
        'obligations', 'source_offer_required',
    }
    if not isinstance(approval, dict):
        raise SystemExit(f'Approved component lacks an approval record: {component}')
    missing = sorted(required - approval.keys())
    if missing:
        missing_text = ', '.join(missing)
        raise SystemExit(f'Approval for {component} lacks: {missing_text}')
    if not approval['covered_wheel_directories']:
        raise SystemExit(f'Approval has no wheel scope: {component}')
    evidence_items = approval['license_evidence']
    if not isinstance(evidence_items, list) or not evidence_items:
        raise SystemExit(f'Approval has no license evidence: {component}')
    copied: list[str] = []
    component_destination = destination / safe_component_directory(component)
    for index, evidence in enumerate(evidence_items, start=1):
        if not isinstance(evidence, dict):
            raise SystemExit(f'Malformed license evidence for {component}')
        missing = sorted({'sha256', 'contains'} - evidence.keys())
        if missing:
            missing_text = ', '.join(missing)
            raise SystemExit(f'Evidence for {component} lacks: {missing_text}')
        if 'repository_path' in evidence:
            repository_required = {'repository_path', 'source_url'}
            missing = sorted(repository_required - evidence.keys())
            if missing:
                raise SystemExit(
                    f'Repository evidence for {component} lacks: {", ".join(missing)}'
                )
            if not any(
                evidence.get(key)
                for key in ('source_commit', 'source_archive_sha512', 'retrieved_on')
            ):
                raise SystemExit(
                    f'Repository evidence for {component} lacks pinned provenance'
                )
            source = (project_root / str(evidence['repository_path'])).resolve()
            if project_root not in source.parents:
                raise SystemExit(f'Unsafe repository evidence path for {component}')
        else:
            wheel_required = {'distribution', 'path'}
            missing = sorted(wheel_required - evidence.keys())
            if missing:
                raise SystemExit(
                    f'Wheel evidence for {component} lacks: {", ".join(missing)}'
                )
            distribution = metadata.distribution(str(evidence['distribution']))
            source = Path(distribution.locate_file(str(evidence['path']))).resolve()
        if not source.is_file():
            raise SystemExit(f'License evidence is missing for {component}: {source}')
        actual_hash = sha256_file(source)
        expected_hash = str(evidence['sha256']).lower()
        if actual_hash != expected_hash:
            raise SystemExit(
                f'License evidence hash changed for {component}: '
                f'{actual_hash} != {expected_hash}'
            )
        text = source.read_text(encoding='utf-8', errors='replace')
        absent = [str(marker) for marker in evidence['contains'] if str(marker) not in text]
        if absent:
            absent_text = ', '.join(absent)
            raise SystemExit(f'Evidence markers missing for {component}: {absent_text}')
        target = component_destination / f'{index:02d}-{source.name}'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination.parent)).replace('\\', '/'))
    return copied


def verify_system_evidence(entry: dict, destination: Path, project_root: Path) -> None:
    approval = entry['approval']
    evidence_type = approval.get('system_evidence')
    if not evidence_type:
        return
    component = str(entry['component'])
    if evidence_type != 'visual_studio_2022':
        raise SystemExit(f'Unknown system evidence for {component}: {evidence_type}')
    if os.name != 'nt':
        raise SystemExit('Microsoft runtime redistribution requires a licensed Windows build host')
    vswhere = Path(os.environ.get(
        'ProgramFiles(x86)', r'C:\Program Files (x86)'
    )) / 'Microsoft Visual Studio' / 'Installer' / 'vswhere.exe'
    if not vswhere.is_file():
        raise SystemExit('Visual Studio license verification failed: vswhere.exe is missing')
    result = subprocess.run(
        [str(vswhere), '-all', '-products', '*', '-format', 'json'],
        check=True,
        capture_output=True,
        text=True,
    )
    installations = json.loads(result.stdout)
    required_fields = {
        'system_product_id', 'system_installation_version', 'system_redist_sha256',
        'entitlement_record',
    }
    missing = sorted(required_fields - approval.keys())
    if missing:
        raise SystemExit(
            f'Microsoft system evidence for {component} lacks: {", ".join(missing)}'
        )
    expected_product = str(approval['system_product_id'])
    expected_version = str(approval['system_installation_version'])
    entitlement_path = (project_root / str(approval['entitlement_record'])).resolve()
    if project_root not in entitlement_path.parents or not entitlement_path.is_file():
        raise SystemExit('Visual Studio entitlement record is missing or unsafe')
    entitlement = json.loads(entitlement_path.read_text(encoding='utf-8'))
    entitlement_required = {
        'schema_version', 'attested_by', 'attested_on', 'use_basis', 'statement',
        'product_id', 'project_license', 'project_license_path',
        'project_license_sha256', 'community_terms_url', 'redistribution_url',
    }
    entitlement_missing = sorted(entitlement_required - entitlement.keys())
    if entitlement_missing:
        raise SystemExit(
            'Visual Studio entitlement record lacks: ' + ', '.join(entitlement_missing)
        )
    if entitlement['schema_version'] != 1:
        raise SystemExit('Visual Studio entitlement record schema is not supported')
    if entitlement['use_basis'] != 'osi_approved_open_source_project':
        raise SystemExit('Visual Studio Community entitlement basis is not approved')
    if entitlement['product_id'] != expected_product:
        raise SystemExit('Visual Studio entitlement product does not match release policy')
    if entitlement['project_license'] != 'Apache-2.0':
        raise SystemExit('Visual Studio entitlement project license is not Apache-2.0')
    project_license = (project_root / str(entitlement['project_license_path'])).resolve()
    if project_root not in project_license.parents or not project_license.is_file():
        raise SystemExit('Visual Studio entitlement project license is missing or unsafe')
    if sha256_file(project_license) != str(entitlement['project_license_sha256']).lower():
        raise SystemExit('Visual Studio entitlement project license digest changed')
    if 'Apache License' not in project_license.read_text(encoding='utf-8'):
        raise SystemExit('Visual Studio entitlement project license is not recognized')
    for url_field in ('community_terms_url', 'redistribution_url'):
        if not str(entitlement[url_field]).startswith('https://'):
            raise SystemExit(f'Visual Studio entitlement {url_field} must use HTTPS')
    if 'solely to develop, test, and release' not in str(entitlement['statement']):
        raise SystemExit('Visual Studio entitlement attestation is not recognized')
    eligible = [
        item for item in installations
        if item.get('productId') == expected_product
        and item.get('isComplete')
        and str(item.get('installationVersion', '')) == expected_version
    ]
    if not eligible:
        raise SystemExit(
            'Microsoft runtime redistribution requires the exact complete Visual '
            f'Studio release host recorded by policy: {expected_product} {expected_version}'
        )
    installation = Path(str(eligible[0]['installationPath']))
    redist_pointer = installation / 'Licenses' / '1033' / 'Redist.txt'
    if not redist_pointer.is_file():
        raise SystemExit('Visual Studio 2022 REDIST pointer is missing')
    expected_redist_hash = str(approval['system_redist_sha256']).lower()
    if sha256_file(redist_pointer) != expected_redist_hash:
        raise SystemExit('Visual Studio 2022 REDIST pointer digest changed')
    redist_text = redist_pointer.read_text(encoding='utf-8', errors='replace')
    if 'https://aka.ms/vs/17/redist.txt' not in redist_text:
        raise SystemExit('Visual Studio 2022 REDIST pointer is not recognized')
    shutil.copy2(entitlement_path, destination / 'VISUAL_STUDIO_ENTITLEMENT.json')


def verify_source_evidence(
    entry: dict,
    destination: Path,
    project_root: Path,
) -> list[str]:
    component = str(entry['component'])
    approval = entry['approval']
    evidence_items = approval.get('source_evidence') or []
    if approval['source_offer_required'] and not evidence_items:
        raise SystemExit(
            f'Approval requires corresponding source but none is retained: {component}'
        )
    copied: list[str] = []
    component_destination = destination / safe_component_directory(component)
    for evidence in evidence_items:
        if not isinstance(evidence, dict):
            raise SystemExit(f'Malformed source evidence for {component}')
        required = {'repository_path', 'source_url'}
        missing = sorted(required - evidence.keys())
        if missing:
            raise SystemExit(
                f'Source evidence for {component} lacks: {", ".join(missing)}'
            )
        if not evidence.get('sha256') and not evidence.get('sha512'):
            raise SystemExit(f'Source evidence lacks a digest: {component}')
        source = (project_root / str(evidence['repository_path'])).resolve()
        if project_root not in source.parents or not source.is_file():
            raise SystemExit(f'Source evidence is missing or unsafe: {source}')
        if evidence.get('sha256') and sha256_file(source) != str(evidence['sha256']).lower():
            raise SystemExit(f'Source evidence SHA-256 changed: {component}')
        if evidence.get('sha512') and sha512_file(source) != str(evidence['sha512']).lower():
            raise SystemExit(f'Source evidence SHA-512 changed: {component}')
        target = component_destination / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied.append(str(target.relative_to(destination.parent)).replace('\\', '/'))
    return copied


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_runtime_policy(manifest_path: Path, license_path: Path, destination: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or manifest.get('status') != APPROVED_STATUS:
        raise SystemExit('Runtime component policy is not approved')
    actual_version = '.'.join(map(str, sys.version_info[:3]))
    required_version = str(manifest.get('python_version') or '')
    if actual_version != required_version:
        raise SystemExit(
            f'Build Python is {actual_version}; runtime policy requires '
            f'{required_version}'
        )
    if not license_path.is_file():
        raise SystemExit(f'Pinned combined runtime license is missing: {license_path}')
    if sha256_file(license_path) != str(manifest['combined_license']['sha256']):
        raise SystemExit('Pinned combined runtime license hash changed')
    archive_path = license_path.parent / str(manifest['archive']['file_name'])
    if not archive_path.is_file() or sha256_file(archive_path) != str(
        manifest['archive']['sha256']
    ):
        raise SystemExit('Pinned runtime archive is missing or has the wrong hash')
    runtime_root = Path(sys.base_prefix).resolve()
    marker = runtime_root.parent / 'VERIFIED-ARCHIVE-SHA256.txt'
    if not marker.is_file() or marker.read_text(encoding='utf-8').strip() != str(
        manifest['archive']['sha256']
    ):
        raise SystemExit('Build runtime lacks the verified pinned-archive marker')
    verified_files: list[dict] = []
    for entry in manifest.get('critical_files') or []:
        relative = Path(str(entry['path']))
        source = (runtime_root / relative).resolve()
        if runtime_root not in source.parents or not source.is_file():
            raise SystemExit(f'Pinned runtime file is missing or unsafe: {relative.as_posix()}')
        digest = sha256_file(source)
        if digest != str(entry['sha256']):
            raise SystemExit(f'Pinned runtime file hash mismatch: {relative.as_posix()}')
        verified_files.append({
            'path': relative.as_posix(),
            'sha256': digest,
            'component': entry['component'],
        })
    shutil.copy2(license_path, destination / 'PYTHON_RUNTIME_LICENSES.rst')
    shutil.copy2(manifest_path, destination / 'RUNTIME_COMPONENT_POLICY.json')
    return {
        'distribution': manifest['distribution'],
        'release': manifest['release'],
        'python_version': manifest['python_version'],
        'archive_url': manifest['archive']['url'],
        'archive_sha256': manifest['archive']['sha256'],
        'verified_files': verified_files,
    }


def sha512_file(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def safe_component_directory(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '-', name).strip('-') or 'component'


def verify_wheel_build_evidence(
    wheel_directory: str,
    bundle: dict,
    destination: Path,
) -> str:
    evidence = bundle.get('build_evidence')
    required = {'path', 'sha256', 'contains'}
    if not isinstance(evidence, dict) or required - evidence.keys():
        raise SystemExit(f'Wheel bundle lacks build evidence: {wheel_directory}')
    distribution = metadata.distribution(str(bundle['distribution']))
    source = Path(distribution.locate_file(str(evidence['path']))).resolve()
    if not source.is_file():
        raise SystemExit(f'Wheel build evidence is missing: {source}')
    actual_hash = sha256_file(source)
    if actual_hash != str(evidence['sha256']).lower():
        raise SystemExit(f'Wheel build evidence hash changed: {wheel_directory}')
    text = source.read_text(encoding='utf-8', errors='replace')
    absent = [str(marker) for marker in evidence['contains'] if str(marker) not in text]
    if absent:
        raise SystemExit(
            f'Wheel build evidence markers missing for {wheel_directory}: '
            + ', '.join(absent)
        )
    target = destination / f'{wheel_directory}-DELVEWHEEL.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target.relative_to(destination.parent)).replace('\\', '/')


def write_native_review_summary(path: Path, entries: list[dict], inventory: list[dict]) -> None:
    counts: dict[str, int] = {}
    notice_status = 'notice_required'
    review_status = 'review_required'
    for item in inventory:
        status = str(item['status'])
        counts[status] = counts.get(status, 0) + 1
    lines = [
        '# Native component redistribution review',
        '',
        'This report is generated from the exact pinned Windows environment.',
        'An approval applies only while its wheel scope and evidence hashes validate.',
        '',
        f'- Native DLLs inventoried: {len(inventory)}',
        f'- Approved DLLs: {counts.get(APPROVED_STATUS, 0)}',
        f'- DLLs needing notices: {counts.get(notice_status, 0)}',
        f'- DLLs needing substantive review: {counts.get(review_status, 0)}',
        '',
        '| Component | Status | DLLs | Review basis or blocking reason |',
        '| --- | --- | ---: | --- |',
    ]
    for entry in sorted(entries, key=lambda item: str(item['component']).lower()):
        component = str(entry['component'])
        matching = [item for item in inventory if item['component'] == component]
        if not matching:
            continue
        if entry['status'] == APPROVED_STATUS:
            detail = str(entry['approval']['basis'])
        else:
            detail = str(entry['blocking_reason'])
        detail = detail.replace('|', '\\|').replace('\n', ' ')
        entry_status = entry['status']
        lines.append(f'| {component} | {entry_status} | {len(matching)} | {detail} |')
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect installer license evidence and audit wheel DLL coverage")
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--python-manifest", type=Path, required=True)
    parser.add_argument("--native-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-unverified-native", action="store_true")
    parser.add_argument('--runtime-manifest', type=Path, required=True)
    parser.add_argument('--runtime-license', type=Path, required=True)
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    if args.output.exists():
        shutil.rmtree(args.output)
    args.output.mkdir(parents=True)
    runtime_record = verify_runtime_policy(
        args.runtime_manifest,
        args.runtime_license,
        args.output,
    )

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise SystemExit(f"Python license file is missing: {python_license}")
    shutil.copy2(python_license, args.output / "PYTHON_LICENSE.txt")
    for filename in ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md", "CONTENT_PROVENANCE.md", "ASSET_LICENSES.md"):
        shutil.copy2(project_root / filename, args.output / filename)
    source_instructions = project_root / 'packaging' / 'native-source' / 'README.md'
    if not source_instructions.is_file():
        raise SystemExit('Native corresponding-source instructions are missing')
    source_output = args.output / 'native-source'
    source_output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_instructions, source_output / 'README.md')
    python_source_instructions = project_root / 'packaging' / 'python-source' / 'README.md'
    if not python_source_instructions.is_file():
        raise SystemExit('Python corresponding-source instructions are missing')
    python_source_output = args.output / 'python-source'
    python_source_output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(python_source_instructions, python_source_output / 'README.md')

    locked = locked_requirements(args.requirements)
    python_policy = load_python_policy(args.python_manifest, locked)
    components: list[dict[str, object]] = []
    for name, required_version in locked.items():
        distribution = metadata.distribution(name)
        if distribution.version != required_version:
            raise SystemExit(f"{name} is {distribution.version}; installer lock requires {required_version}")
        policy_entry = python_policy[name]
        verify_python_approval(policy_entry, distribution)
        corresponding_source = verify_python_source_evidence(
            policy_entry, python_source_output, project_root
        )
        components.append({
            "name": distribution.metadata["Name"],
            "version": distribution.version,
            "license_expression": policy_entry["license"],
            "review_status": policy_entry["status"],
            "homepage": distribution.metadata.get("Home-page") or distribution.metadata.get("Project-URL") or "",
            "license_files": copy_distribution_licenses(distribution, args.output / "python"),
            "corresponding_source": corresponding_source,
        })

    native_manifest = json.loads(args.native_manifest.read_text(encoding='utf-8'))
    if native_manifest.get('schema_version') != 2:
        raise SystemExit('native-components.json must use schema_version 2')
    native_entries = native_manifest['components']
    wheel_bundles = native_manifest.get('wheel_bundles')
    if not isinstance(wheel_bundles, dict) or not wheel_bundles:
        raise SystemExit('native-components.json must declare wheel_bundles')
    default_reasons = native_manifest.get('default_blocking_reasons')
    if not isinstance(default_reasons, dict):
        raise SystemExit('native-components.json must declare default blocking reasons')
    registry_path = native_manifest.get('evidence_registry')
    evidence_registry = {'licenses': {}, 'sources': {}}
    if registry_path:
        resolved_registry = (project_root / str(registry_path)).resolve()
        if project_root not in resolved_registry.parents or not resolved_registry.is_file():
            raise SystemExit('Native evidence registry is missing or unsafe')
        evidence_registry = json.loads(resolved_registry.read_text(encoding='utf-8'))
    for entry in native_entries:
        approval = entry.get('approval')
        if not isinstance(approval, dict):
            continue
        if 'license_evidence_ids' in approval:
            try:
                approval['license_evidence'] = [
                    evidence_registry['licenses'][evidence_id]
                    for evidence_id in approval.pop('license_evidence_ids')
                ]
            except KeyError as error:
                raise SystemExit(f'Unknown license evidence id: {error.args[0]}') from error
        if 'source_evidence_ids' in approval:
            try:
                approval['source_evidence'] = [
                    evidence_registry['sources'][evidence_id]
                    for evidence_id in approval.pop('source_evidence_ids')
                ]
            except KeyError as error:
                raise SystemExit(f'Unknown source evidence id: {error.args[0]}') from error
    wheel_build_evidence: dict[str, str] = {}
    for wheel_directory, bundle in wheel_bundles.items():
        if not isinstance(bundle, dict):
            raise SystemExit(f'Malformed wheel bundle: {wheel_directory}')
        distribution = metadata.distribution(str(bundle['distribution']))
        if distribution.version != str(bundle['version']):
            raise SystemExit(
                f'{wheel_directory} uses {distribution.version}; '
                f'native manifest requires {bundle["version"]}'
            )
        wheel_build_evidence[wheel_directory] = verify_wheel_build_evidence(
            wheel_directory,
            bundle,
            args.output / 'native-build',
        )
    component_names: set[str] = set()
    approved_evidence: dict[str, list[str]] = {}
    approved_source: dict[str, list[str]] = {}
    for entry in native_entries:
        component = str(entry.get('component') or '')
        if not component or component in component_names:
            raise SystemExit(f'Duplicate or empty native component: {component!r}')
        component_names.add(component)
        status = str(entry.get('status') or '')
        if status not in REVIEW_STATUSES:
            raise SystemExit(f'Unknown review status for {component}: {status}')
        if status == APPROVED_STATUS:
            approval = entry.get('approval') or {}
            verify_system_evidence(entry, args.output, project_root)
            covered = set(map(str, approval.get('covered_wheel_directories') or []))
            unknown = sorted(covered - wheel_bundles.keys())
            if unknown:
                unknown_text = ', '.join(unknown)
                raise SystemExit(f'Approval for {component} has unknown wheels: {unknown_text}')
            assertions = approval.get('version_assertions')
            if assertions is not None:
                if not isinstance(assertions, dict) or set(assertions) != covered:
                    raise SystemExit(
                        f'Approval version assertions do not match wheel scope: {component}'
                    )
            evidence_distributions = {
                str(item.get('distribution'))
                for item in approval.get('license_evidence') or []
                if isinstance(item, dict) and item.get('distribution')
            }
            known_distributions = {
                str(wheel_bundles[wheel]['distribution']) for wheel in covered
            }
            unrelated_distributions = sorted(
                evidence_distributions - known_distributions
            )
            if unrelated_distributions:
                unrelated_text = ', '.join(unrelated_distributions)
                raise SystemExit(
                    f'Approval for {component} cites unrelated wheels: {unrelated_text}'
                )
            approved_evidence[component] = verify_approval_evidence(
                entry, args.output / 'native', project_root
            )
            approved_source[component] = verify_source_evidence(
                entry, args.output / 'native-source', project_root
            )
        else:
            reason = str(entry.get('blocking_reason') or default_reasons.get(status) or '')
            if not reason.strip():
                raise SystemExit(f'Blocked component lacks a reason: {component}')
            entry['blocking_reason'] = reason

    site_packages = Path(next(path for path in sys.path if path.lower().endswith("site-packages")))
    native_files = sorted(path for directory in site_packages.glob("*.libs") for path in directory.glob("*.dll"))
    unmatched: list[str] = []
    matched_review: set[str] = set()
    native_inventory: list[dict[str, object]] = []
    for path in native_files:
        matches = [entry for entry in native_entries if any(fnmatch.fnmatchcase(path.name, pattern) for pattern in entry["patterns"])]
        if len(matches) != 1:
            unmatched.append(path.name)
            continue
        entry = matches[0]
        native_inventory.append({
            "file": path.name,
            "wheel_directory": path.parent.name,
            "component": entry["component"],
            "license": entry["license"],
            "source": entry["source"],
            "status": entry["status"],
        })
        if entry["status"] != "approved":
            matched_review.add(entry["component"])
    for item in native_inventory:
        wheel_directory = str(item['wheel_directory'])
        bundle = wheel_bundles.get(wheel_directory)
        if not isinstance(bundle, dict):
            raise SystemExit(f'Native wheel directory is not declared: {wheel_directory}')
        distribution = metadata.distribution(str(bundle['distribution']))
        required_version = str(bundle['version'])
        if distribution.version != required_version:
            raise SystemExit(
                f'{wheel_directory} uses {distribution.version}; '
                f'native manifest requires {required_version}'
            )
        entry = next(
            candidate for candidate in native_entries
            if candidate['component'] == item['component']
        )
        if entry['status'] == APPROVED_STATUS:
            covered = set(map(str, entry['approval']['covered_wheel_directories']))
            if wheel_directory not in covered:
                component = item['component']
                raise SystemExit(f'Approval for {component} does not cover {wheel_directory}')
        binary_path = site_packages / wheel_directory / str(item['file'])
        with os.add_dll_directory(str(binary_path.parent.resolve())):
            try:
                probe = query_version(binary_path)
            except (AttributeError, OSError, RuntimeError) as error:
                probe = {'status': 'query-failed', 'error': str(error)}
        version_probe = {
            key: probe[key]
            for key in ('status', 'function', 'version', 'error')
            if key in probe
        }
        assertions = (
            entry.get('approval', {}).get('version_assertions')
            if entry['status'] == APPROVED_STATUS
            else None
        )
        if assertions is not None:
            expected_version = str(assertions[wheel_directory])
            if probe.get('status') != 'identified' or probe.get('version') != expected_version:
                component = item['component']
                raise SystemExit(
                    f'Native version assertion failed for {component} in '
                    f'{wheel_directory}: {probe.get("version")} != {expected_version}'
                )
        item.update({
            'sha256': sha256_file(binary_path),
            'size': binary_path.stat().st_size,
            'distribution': distribution.metadata['Name'],
            'distribution_version': distribution.version,
            'wheel_build_evidence': wheel_build_evidence[wheel_directory],
            'upstream_build': bundle.get('upstream_build'),
            'license_evidence': approved_evidence.get(str(item['component']), []),
            'corresponding_source': approved_source.get(str(item['component']), []),
            'blocking_reason': entry.get('blocking_reason'),
            'version_probe': version_probe,
        })
    if unmatched:
        raise SystemExit("Native DLLs missing from native-components.json: " + ", ".join(unmatched))

    report = {
        'release_runtime': runtime_record,
        "format": "Geospatial Extraction Studio installer component inventory 2",
        "native_manifest_schema": native_manifest["schema_version"],
        "python": sys.version,
        "python_components": sorted(components, key=lambda item: str(item["name"]).lower()),
        "native_components": native_inventory,
    }
    (args.output / "THIRD_PARTY_COMPONENTS.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(args.python_manifest, args.output / "PYTHON_COMPONENT_POLICY.json")
    shutil.copy2(args.native_manifest, args.output / "NATIVE_COMPONENT_POLICY.json")

    write_native_review_summary(
        args.output / 'NATIVE_REVIEW_SUMMARY.md',
        native_entries,
        native_inventory,
    )
    if matched_review and not args.allow_unverified_native:
        names = ", ".join(sorted(matched_review))
        raise SystemExit(
            "Binary release blocked: corresponding source/build provenance or redistribution terms "
            f"still require verification for: {names}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
