from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from importlib import metadata
from pathlib import Path


NATIVE_SUFFIXES = {'.dll', '.exe', '.pyd'}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise SystemExit(f'Expected a JSON object: {path}')
    return value


def verified_runtime(
    manifest: dict,
    runtime_license: Path,
    runtime_archive: Path,
) -> tuple[Path, dict[str, dict]]:
    if manifest.get('schema_version') != 1 or manifest.get('status') != 'approved':
        raise SystemExit('Runtime component policy is not approved')
    expected_version = str(manifest.get('python_version') or '')
    actual_version = '.'.join(map(str, sys.version_info[:3]))
    if actual_version != expected_version:
        raise SystemExit(f'Build Python is {actual_version}; runtime policy requires {expected_version}')
    expected_license_hash = str(manifest['combined_license']['sha256'])
    if not runtime_license.is_file() or sha256_file(runtime_license) != expected_license_hash:
        raise SystemExit('Pinned combined runtime license is missing or has the wrong hash')
    expected_archive_hash = str(manifest['archive']['sha256'])
    if not runtime_archive.is_file() or sha256_file(runtime_archive) != expected_archive_hash:
        raise SystemExit('Pinned runtime archive is missing or has the wrong hash')
    runtime_root = Path(sys.base_prefix).resolve()
    marker = runtime_root.parent / 'VERIFIED-ARCHIVE-SHA256.txt'
    if not marker.is_file() or marker.read_text(encoding='utf-8').strip() != expected_archive_hash:
        raise SystemExit('Build runtime lacks the verified pinned-archive marker')
    critical: dict[str, dict] = {}
    for entry in manifest.get('critical_files') or []:
        relative = Path(str(entry['path']))
        path = (runtime_root / relative).resolve()
        if runtime_root not in path.parents or not path.is_file():
            raise SystemExit(f'Pinned runtime file is missing or unsafe: {relative.as_posix()}')
        actual = sha256_file(path)
        if actual != str(entry['sha256']):
            raise SystemExit(f'Pinned runtime file hash mismatch: {relative.as_posix()}')
        critical[actual] = dict(entry)
    return runtime_root, critical


def verify_build_tools(manifest: dict, license_bundle: Path) -> dict[str, str]:
    if manifest.get('schema_version') != 1:
        raise SystemExit('Build component policy must use schema version 1')
    versions: dict[str, str] = {}
    output = license_bundle / 'build-tools'
    output.mkdir(parents=True, exist_ok=True)
    for entry in manifest.get('components') or []:
        name = str(entry['distribution'])
        distribution = metadata.distribution(name)
        version = str(entry['version'])
        if distribution.version != version:
            raise SystemExit(f'{name} is {distribution.version}; build policy requires {version}')
        source = Path(distribution.locate_file(str(entry['license_path'])))
        if not source.is_file() or sha256_file(source) != str(entry['license_sha256']):
            raise SystemExit(f'Build-tool license evidence mismatch: {name}')
        destination = output / name / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        versions[name] = version
    return versions


def add_source(mapping: dict[str, list[dict]], path: Path, record: dict) -> None:
    if path.is_file() and path.suffix.lower() in NATIVE_SUFFIXES:
        mapping.setdefault(sha256_file(path), []).append(record)


def runtime_sources(runtime_archive: Path, critical: dict[str, dict]) -> dict[str, list[dict]]:
    mapping: dict[str, list[dict]] = {}
    with tarfile.open(runtime_archive, mode='r:gz') as archive:
        for member in archive:
            member_path = Path(member.name)
            if (
                not member.isfile()
                or member_path.suffix.lower() not in NATIVE_SUFFIXES
                or not member_path.parts
                or member_path.parts[0] != 'python'
            ):
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise SystemExit(f'Unable to read pinned runtime archive member: {member.name}')
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            value = digest.hexdigest()
            component = str(
                critical.get(value, {}).get('component') or 'CPython-standalone-runtime'
            )
            mapping.setdefault(value, []).append({
                'source_kind': 'pinned-runtime-archive',
                'component': component,
                'source_path': Path(*member_path.parts[1:]).as_posix(),
            })
    return mapping


def distribution_sources(mapping: dict[str, list[dict]]) -> None:
    for distribution in metadata.distributions():
        name = distribution.metadata.get('Name') or 'unknown-distribution'
        for relative in distribution.files or []:
            path = Path(distribution.locate_file(relative))
            add_source(mapping, path, {
                'source_kind': 'python-distribution',
                'component': f'{name}@{distribution.version}',
                'source_path': str(relative).replace('\\', '/'),
            })


def native_wheel_sources(report: dict) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in report.get('native_components') or []:
        digest = str(item.get('sha256') or '')
        if digest:
            result[digest] = {
                'source_kind': 'reviewed-wheel-native-library',
                'component': str(item['component']),
                'source_path': f'{item["wheel_directory"]}/{item["file"]}',
            }
    return result


def copy_postbuild_legal_files(source: Path, installed: Path) -> None:
    installed.mkdir(parents=True, exist_ok=True)
    for relative in ('FINAL_BINARY_INVENTORY.json', 'RUNTIME_COMPONENT_POLICY.json'):
        shutil.copy2(source / relative, installed / relative)
    source_tools = source / 'build-tools'
    installed_tools = installed / 'build-tools'
    if installed_tools.exists():
        shutil.rmtree(installed_tools)
    shutil.copytree(source_tools, installed_tools)


def main() -> int:
    parser = argparse.ArgumentParser(description='Fail-closed audit of a completed PyInstaller directory')
    parser.add_argument('--application', type=Path, required=True)
    parser.add_argument('--license-bundle', type=Path, required=True)
    parser.add_argument('--installed-license-bundle', type=Path, required=True)
    parser.add_argument('--runtime-manifest', type=Path, required=True)
    parser.add_argument('--runtime-license', type=Path, required=True)
    parser.add_argument('--runtime-archive', type=Path, required=True)
    parser.add_argument('--build-manifest', type=Path, required=True)
    parser.add_argument('--native-report', type=Path, required=True)
    parser.add_argument('--expected-executable', default='GeospatialExtractionStudio.exe')
    args = parser.parse_args()

    application = args.application.resolve()
    license_bundle = args.license_bundle.resolve()
    installed_license_bundle = args.installed_license_bundle.resolve()
    if not application.is_dir() or not license_bundle.is_dir():
        raise SystemExit('Frozen application or license bundle is missing')

    runtime_manifest = load_json(args.runtime_manifest)
    _runtime_root, critical = verified_runtime(
        runtime_manifest,
        args.runtime_license,
        args.runtime_archive,
    )
    build_versions = verify_build_tools(load_json(args.build_manifest), license_bundle)
    source_map = runtime_sources(args.runtime_archive, critical)
    distribution_sources(source_map)
    wheel_sources = native_wheel_sources(load_json(args.native_report))

    expected_runtime_hashes = {
        str(entry['sha256']): str(entry['path'])
        for entry in runtime_manifest.get('critical_files') or []
        if Path(str(entry['path'])).suffix.lower() in NATIVE_SUFFIXES
    }
    seen_runtime_hashes: set[str] = set()
    inventory: list[dict] = []
    unmatched: list[str] = []
    expected_executable = application / args.expected_executable
    for path in sorted(
        candidate for candidate in application.rglob('*')
        if candidate.is_file() and candidate.suffix.lower() in NATIVE_SUFFIXES
    ):
        relative = path.relative_to(application).as_posix()
        digest = sha256_file(path)
        if path == expected_executable:
            record = {
                'source_kind': 'generated-pyinstaller-executable',
                'component': f'PyInstaller@{build_versions["pyinstaller"]}',
                'source_path': 'PyInstaller-bootloader-plus-project-archive',
            }
        elif digest in wheel_sources:
            record = wheel_sources[digest]
        elif digest in source_map:
            record = source_map[digest][0]
        else:
            unmatched.append(relative)
            continue
        if digest in expected_runtime_hashes:
            seen_runtime_hashes.add(digest)
        inventory.append({
            'path': relative,
            'sha256': digest,
            'size': path.stat().st_size,
            **record,
        })

    if not expected_executable.is_file():
        raise SystemExit(f'Expected frozen executable is missing: {args.expected_executable}')
    if unmatched:
        raise SystemExit('Unrecognized frozen native files: ' + ', '.join(unmatched))
    missing_runtime = sorted(set(expected_runtime_hashes) - seen_runtime_hashes)
    if missing_runtime:
        missing_names = ', '.join(expected_runtime_hashes[digest] for digest in missing_runtime)
        raise SystemExit('Frozen application is missing pinned runtime files: ' + missing_names)

    report = {
        'format': 'Geospatial Extraction Studio final frozen native inventory 1',
        'status': 'approved',
        'runtime_distribution': runtime_manifest['distribution'],
        'runtime_release': runtime_manifest['release'],
        'runtime_archive_sha256': runtime_manifest['archive']['sha256'],
        'native_file_count': len(inventory),
        'files': inventory,
    }
    output = license_bundle / 'FINAL_BINARY_INVENTORY.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(args.runtime_manifest, license_bundle / 'RUNTIME_COMPONENT_POLICY.json')
    copy_postbuild_legal_files(license_bundle, installed_license_bundle)
    print(f'Approved {len(inventory)} final native files; inventory: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
