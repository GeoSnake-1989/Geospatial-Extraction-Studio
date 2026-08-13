from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import json
import shutil
import sys
import tarfile
from importlib import metadata
from pathlib import Path

import pefile
from PyInstaller.archive.readers import CArchiveReader


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


def canonical_name(value: str) -> str:
    return value.lower().replace('_', '-').replace('.', '-')


def load_toc(path: Path) -> tuple | list:
    try:
        value = ast.literal_eval(path.read_text(encoding='utf-8'))
    except (OSError, SyntaxError, ValueError) as error:
        raise SystemExit(f'Invalid PyInstaller TOC: {path}: {error}') from error
    if not isinstance(value, (tuple, list)):
        raise SystemExit(f'Unexpected PyInstaller TOC structure: {path}')
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


def verify_build_tools(manifest: dict, manifest_path: Path, license_bundle: Path) -> dict[str, str]:
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
    project_root = manifest_path.resolve().parent.parent
    for entry in manifest.get('external_components') or []:
        name = str(entry['name'])
        source = (project_root / str(entry['license_path'])).resolve()
        if project_root not in source.parents or not source.is_file():
            raise SystemExit(f'External build-tool evidence is missing or unsafe: {name}')
        if sha256_file(source) != str(entry['license_sha256']):
            raise SystemExit(f'External build-tool license evidence mismatch: {name}')
        destination = output / name / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        versions[name] = str(entry['version'])
    return versions


def distribution_source_index() -> dict[Path, tuple[metadata.Distribution, object]]:
    result: dict[Path, tuple[metadata.Distribution, object]] = {}
    for distribution in metadata.distributions():
        for relative in distribution.files or []:
            path = Path(distribution.locate_file(relative)).resolve()
            result.setdefault(path, (distribution, relative))
    return result


def verify_record_hash(path: Path, relative: object) -> str:
    file_hash = getattr(relative, 'hash', None)
    if file_hash is None or file_hash.mode != 'sha256':
        raise SystemExit(f'Frozen Python source lacks a SHA-256 RECORD entry: {path}')
    expected = base64.urlsafe_b64decode(file_hash.value + '=' * (-len(file_hash.value) % 4)).hex()
    actual = sha256_file(path)
    if actual != expected:
        raise SystemExit(f'Frozen Python source changed from its installed RECORD: {path}')
    return actual


def archive_member_hashes(runtime_archive: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with tarfile.open(runtime_archive, mode='r:gz') as archive:
        for member in archive:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise SystemExit(f'Unable to read pinned runtime archive member: {member.name}')
            digest = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
            result[Path(member.name).as_posix()] = digest.hexdigest()
    return result


def pure_python_inventory(
    pyz_toc_path: Path,
    embedded_pyz: object,
    runtime_root: Path,
    runtime_archive: Path,
    native_report: dict,
    project_root: Path,
) -> list[dict]:
    toc = load_toc(pyz_toc_path)
    if len(toc) != 2 or not isinstance(toc[1], list):
        raise SystemExit('Unexpected PYZ TOC structure')
    rows = toc[1]
    expected_names = [str(row[0]) for row in rows]
    actual_names = list(embedded_pyz.toc)
    if actual_names != expected_names:
        raise SystemExit('Embedded PYZ module inventory differs from the controlled PYZ TOC')

    approved = {
        canonical_name(str(item['name'])): str(item['version'])
        for item in native_report.get('python_components') or []
        if item.get('review_status') == 'approved'
    }
    source_index = distribution_source_index()
    runtime_hashes = archive_member_hashes(runtime_archive)
    package_owners = metadata.packages_distributions()
    inventory: list[dict] = []
    for row in rows:
        if len(row) != 3 or str(row[2]) != 'PYMODULE':
            raise SystemExit(f'Unexpected PYZ TOC entry: {row!r}')
        module = str(row[0])
        source_value = str(row[1])
        record = {'module': module}
        if source_value == '-':
            candidates = package_owners.get(module.split('.', 1)[0], [])
            owners = [name for name in candidates if canonical_name(name) in approved]
            if len(owners) != 1:
                raise SystemExit(f'Unapproved or ambiguous namespace module in PYZ: {module}')
            record.update({
                'source_kind': 'approved-python-namespace',
                'component': f'{owners[0]}@{approved[canonical_name(owners[0])]}',
                'source_path': '-',
            })
        else:
            embedded_bytes = embedded_pyz.extract(module, raw=True)
            if not isinstance(embedded_bytes, bytes):
                raise SystemExit(f'Unable to extract embedded PYZ module: {module}')
            record['embedded_sha256'] = hashlib.sha256(embedded_bytes).hexdigest()
            source = Path(source_value).resolve()
            if source == runtime_root or runtime_root in source.parents:
                relative = source.relative_to(runtime_root).as_posix()
                archive_name = f'python/{relative}'
                expected = runtime_hashes.get(archive_name)
                actual = sha256_file(source)
                if expected is None or actual != expected:
                    raise SystemExit(f'Frozen stdlib source differs from pinned runtime archive: {relative}')
                record.update({
                    'source_kind': 'pinned-runtime-source',
                    'component': 'CPython-standalone-runtime',
                    'source_path': relative,
                    'source_sha256': actual,
                })
            elif source in source_index:
                distribution, relative = source_index[source]
                name = str(distribution.metadata.get('Name') or distribution.name)
                normalized = canonical_name(name)
                if normalized not in approved or distribution.version != approved[normalized]:
                    raise SystemExit(
                        f'Unapproved Python distribution in embedded PYZ: '
                        f'{name}@{distribution.version} ({module})'
                    )
                record.update({
                    'source_kind': 'approved-python-distribution',
                    'component': f'{name}@{distribution.version}',
                    'source_path': str(relative).replace('\\', '/'),
                    'source_sha256': verify_record_hash(source, relative),
                })
            elif source == project_root / 'backend' / 'app' or (
                project_root / 'backend' / 'app'
            ) in source.parents:
                record.update({
                    'source_kind': 'application-source',
                    'component': 'Geospatial Extraction Studio',
                    'source_path': source.relative_to(project_root).as_posix(),
                    'source_sha256': sha256_file(source),
                })
            else:
                raise SystemExit(f'Unrecognized Python source in embedded PYZ: {module}: {source}')
        inventory.append(record)
    return inventory


def pe_section_hashes(path: Path) -> dict[str, str]:
    executable = pefile.PE(str(path), fast_load=False)
    return {
        section.Name.rstrip(b'\0').decode('ascii', errors='strict'): hashlib.sha256(
            section.get_data()
        ).hexdigest()
        for section in executable.sections
    }


def executable_provenance(
    executable: Path,
    exe_toc_path: Path,
    pyz_toc_path: Path,
    build_manifest: dict,
    build_versions: dict[str, str],
    project_root: Path,
    runtime_root: Path,
) -> tuple[dict, object]:
    toc = load_toc(exe_toc_path)
    if len(toc) < 21 or not isinstance(toc[15], list) or not isinstance(toc[20], list):
        raise SystemExit('Unexpected EXE TOC structure')
    bootloader_entries = toc[20]
    if len(bootloader_entries) != 1 or len(bootloader_entries[0]) != 3:
        raise SystemExit('Expected exactly one PyInstaller bootloader')
    bootloader = Path(str(bootloader_entries[0][1])).resolve()
    pinned_bootloaders = {
        str(entry['path']).replace('\\', '/'): str(entry['sha256'])
        for entry in build_manifest.get('pyinstaller_bootloaders') or []
    }
    distribution = metadata.distribution('pyinstaller')
    bootloader_relative = str(bootloader.relative_to(Path(distribution.locate_file('')).resolve())).replace(
        '\\', '/'
    )
    expected_bootloader_hash = pinned_bootloaders.get(bootloader_relative)
    if expected_bootloader_hash is None or sha256_file(bootloader) != expected_bootloader_hash:
        raise SystemExit('PyInstaller bootloader is not the hash-pinned approved executable')

    bootloader_sections = pe_section_hashes(bootloader)
    executable_sections = pe_section_hashes(executable)
    immutable_sections = sorted(set(bootloader_sections) - {'.rdata', '.rsrc'})
    if not immutable_sections or any(
        executable_sections.get(name) != bootloader_sections[name]
        for name in immutable_sections
    ):
        raise SystemExit('Generated executable does not retain the pinned bootloader code sections')

    expected_entries: list[str] = []
    entry_inventory: list[dict] = []
    pyinstaller_prefix = Path(distribution.locate_file('PyInstaller')).resolve()
    hooks_prefix = Path(
        metadata.distribution('pyinstaller-hooks-contrib').locate_file(
            '_pyinstaller_hooks_contrib'
        )
    ).resolve()
    for name, source_value, kind in toc[15]:
        if kind == 'OPTION':
            continue
        embedded_name = 'PYZ.pyz' if kind == 'PYZ' else str(name)
        expected_entries.append(embedded_name)
        source = Path(str(source_value)).resolve()
        if kind == 'PYZ':
            component = 'controlled-pure-python-archive'
        elif str(name) == 'struct':
            component = 'CPython-standalone-runtime'
        elif str(name).startswith('pyimod') or str(name) == 'pyiboot01_bootstrap':
            component = f'PyInstaller@{build_versions["pyinstaller"]}'
        elif source == pyinstaller_prefix or pyinstaller_prefix in source.parents:
            component = f'PyInstaller@{build_versions["pyinstaller"]}'
        elif source == hooks_prefix or hooks_prefix in source.parents:
            component = (
                'pyinstaller-hooks-contrib@'
                f'{build_versions["pyinstaller-hooks-contrib"]}'
            )
        elif source == runtime_root or runtime_root in source.parents:
            component = 'CPython-standalone-runtime'
        elif source == project_root / 'backend' / 'app' or (
            project_root / 'backend' / 'app'
        ) in source.parents:
            component = 'Geospatial Extraction Studio'
        else:
            raise SystemExit(f'Unapproved executable archive source: {name}: {source}')
        entry_inventory.append({
            'name': embedded_name,
            'type': str(kind),
            'component': component,
            'source_path': str(source_value).replace('\\', '/'),
        })

    archive = CArchiveReader(str(executable))
    actual_entries = list(archive.toc)
    expected_archive_order = [name for name in expected_entries if name != 'PYZ.pyz'] + [
        name for name in expected_entries if name == 'PYZ.pyz'
    ]
    if actual_entries != expected_archive_order:
        raise SystemExit('Executable embedded archive differs from the controlled EXE TOC')
    embedded_pyz_bytes = archive.extract('PYZ.pyz')
    pyz_toc = load_toc(pyz_toc_path)
    pyz_path = Path(str(pyz_toc[0])).resolve()
    if not isinstance(embedded_pyz_bytes, bytes) or embedded_pyz_bytes != pyz_path.read_bytes():
        raise SystemExit('Executable embedded PYZ differs from the controlled build artifact')
    embedded_pyz = archive.open_embedded_archive('PYZ.pyz')
    return ({
        'status': 'approved',
        'executable_sha256': sha256_file(executable),
        'bootloader': {
            'path': bootloader_relative,
            'sha256': expected_bootloader_hash,
            'immutable_section_sha256': {
                name: bootloader_sections[name] for name in immutable_sections
            },
        },
        'embedded_pyz_sha256': hashlib.sha256(embedded_pyz_bytes).hexdigest(),
        'embedded_entries': entry_inventory,
    }, embedded_pyz)


def verify_frontend_bundle(application: Path, manifest_path: Path, license_bundle: Path) -> dict:
    manifest = load_json(manifest_path)
    if manifest.get('schema_version') != 1 or manifest.get('status') != 'approved':
        raise SystemExit('Frontend component policy is not approved')
    frontend_root = application / '_internal' / 'frontend' / 'dist'
    installed_policy = frontend_root / 'FRONTEND_COMPONENT_POLICY.json'
    if not installed_policy.is_file() or sha256_file(installed_policy) != sha256_file(manifest_path):
        raise SystemExit('Frozen frontend component policy is missing or changed')
    licenses_root = frontend_root / 'third-party-licenses' / 'frontend'
    entries = list(manifest.get('components') or []) + list(manifest.get('build_components') or [])
    expected_names = {str(entry['name']) for entry in entries}
    actual_names = {
        path.name for path in licenses_root.iterdir() if path.is_dir()
    } if licenses_root.is_dir() else set()
    if actual_names != expected_names:
        raise SystemExit('Frozen frontend license directories differ from approved policy')
    for asset in (frontend_root / 'assets').glob('*.js'):
        bundled = asset.read_text(encoding='utf-8', errors='replace')
        if 'modulepreload' in bundled and 'MutationObserver' in bundled:
            raise SystemExit('Vite module-preload polyfill remains in the frozen frontend bundle')
    records: list[dict] = []
    for entry in entries:
        relative = Path(str(entry['name'])) / str(entry['license_file'])
        license_path = licenses_root / relative
        actual = sha256_file(license_path) if license_path.is_file() else ''
        if actual != str(entry['license_sha256']):
            raise SystemExit(f'Frozen frontend license mismatch: {entry["name"]}')
        records.append({
            'name': entry['name'],
            'version': entry['version'],
            'license': entry['license'],
            'license_path': relative.as_posix(),
            'license_sha256': actual,
        })
    shutil.copy2(manifest_path, license_bundle / 'FRONTEND_COMPONENT_POLICY.json')
    return {
        'status': 'approved',
        'lockfile_sha256': manifest['lockfile_sha256'],
        'components': records,
        'module_preload_polyfill': 'disabled-and-absent',
    }


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
    for relative in (
        'FINAL_BINARY_INVENTORY.json',
        'PURE_PYTHON_INVENTORY.json',
        'EXECUTABLE_PROVENANCE.json',
        'FRONTEND_BUNDLE_INVENTORY.json',
        'FRONTEND_COMPONENT_POLICY.json',
        'RUNTIME_COMPONENT_POLICY.json',
    ):
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
    parser.add_argument('--pyz-toc', type=Path, required=True)
    parser.add_argument('--exe-toc', type=Path, required=True)
    parser.add_argument('--frontend-manifest', type=Path, required=True)
    parser.add_argument('--expected-executable', default='GeospatialExtractionStudio.exe')
    args = parser.parse_args()

    application = args.application.resolve()
    license_bundle = args.license_bundle.resolve()
    installed_license_bundle = args.installed_license_bundle.resolve()
    if not application.is_dir() or not license_bundle.is_dir():
        raise SystemExit('Frozen application or license bundle is missing')

    runtime_manifest = load_json(args.runtime_manifest)
    runtime_root, critical = verified_runtime(
        runtime_manifest,
        args.runtime_license,
        args.runtime_archive,
    )
    build_manifest = load_json(args.build_manifest)
    build_versions = verify_build_tools(build_manifest, args.build_manifest, license_bundle)
    native_report = load_json(args.native_report)
    expected_executable = application / args.expected_executable
    executable_report, embedded_pyz = executable_provenance(
        expected_executable,
        args.exe_toc,
        args.pyz_toc,
        build_manifest,
        build_versions,
        Path(__file__).resolve().parents[1],
        runtime_root,
    )
    pure_inventory = pure_python_inventory(
        args.pyz_toc,
        embedded_pyz,
        runtime_root,
        args.runtime_archive,
        native_report,
        Path(__file__).resolve().parents[1],
    )
    frontend_report = verify_frontend_bundle(
        application,
        args.frontend_manifest,
        license_bundle,
    )
    source_map = runtime_sources(args.runtime_archive, critical)
    distribution_sources(source_map)
    wheel_sources = native_wheel_sources(native_report)

    expected_runtime_hashes = {
        str(entry['sha256']): str(entry['path'])
        for entry in runtime_manifest.get('critical_files') or []
        if Path(str(entry['path'])).suffix.lower() in NATIVE_SUFFIXES
    }
    seen_runtime_hashes: set[str] = set()
    inventory: list[dict] = []
    unmatched: list[str] = []
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
    pure_output = license_bundle / 'PURE_PYTHON_INVENTORY.json'
    pure_output.write_text(json.dumps({
        'format': 'Geospatial Extraction Studio frozen Python inventory 1',
        'status': 'approved',
        'module_count': len(pure_inventory),
        'modules': pure_inventory,
    }, indent=2) + '\n', encoding='utf-8')
    executable_output = license_bundle / 'EXECUTABLE_PROVENANCE.json'
    executable_output.write_text(json.dumps(executable_report, indent=2) + '\n', encoding='utf-8')
    frontend_output = license_bundle / 'FRONTEND_BUNDLE_INVENTORY.json'
    frontend_output.write_text(json.dumps(frontend_report, indent=2) + '\n', encoding='utf-8')
    shutil.copy2(args.runtime_manifest, license_bundle / 'RUNTIME_COMPONENT_POLICY.json')
    copy_postbuild_legal_files(license_bundle, installed_license_bundle)
    print(
        f'Approved {len(inventory)} final native files and {len(pure_inventory)} '
        f'frozen Python modules; inventories: {output}, {pure_output}'
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
