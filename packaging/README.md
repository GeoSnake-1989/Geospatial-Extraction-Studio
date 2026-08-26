# Windows binary installer

The supported design is a PyInstaller **onedir** application wrapped by an NSIS per-user installer. The application serves `frontend/dist` from FastAPI, so installed systems do not need Python, Node.js, Vite, or an OpenAI connection.

The same audited onedir application can be distributed without NSIS as an extract-and-run portable ZIP:

```powershell
.\packaging\build-portable.ps1
```

The portable builder requires a clean revision carrying its exact release tag. It invokes the full one-folder dependency, license, native-library, executable-provenance, and smoke-test pipeline; creates a top-level portable folder with usage instructions; verifies the archive by extracting it and matching the launcher digest; and writes adjacent SHA-256, provenance, and matching source-archive artifacts under `release/`. It never enables the engineering-build override. Application data remains under `%LOCALAPPDATA%\Geospatial Extraction Studio\data` rather than inside the extracted program folder.

Run from the repository root:

```powershell
.\packaging\build-installer.ps1
```

The release build performs these gates in order:

1. download/hash verification and fresh extraction of the approved CPython runtime;
2. production frontend build;
3. exact runtime dependency verification;
4. fail-closed Python dependency license-policy verification and collection;
5. native redistribution review gate;
6. PyInstaller onedir build;
7. fail-closed inventory of every final executable, DLL, Python extension, and
   embedded pure-Python module, plus PyInstaller bootloader/archive validation;
8. frozen-app health/UI smoke test;
9. fail-closed NSIS 3.12 executable/license/compressor verification;
10. a second clean-tree and exact `v0.4.5` tag check immediately before publication;
11. NSIS installer, SHA-256 checksum, matching tagged source archive, and
    source-bound installer provenance generation.

A normal build refuses to create `release/Geospatial-Extraction-Studio-Setup-0.4.5.exe` while any matched native component has a status other than `approved` in `native-components.json`. NSIS output is accepted only from the hash-pinned 3.12 `makensis.exe` using the
zlib compressor; the adjacent `.provenance.json` records the compiler and final
installer digests, exact source revision and tag, and matching source-archive
digest. A publication build refuses a dirty tree or a revision without the
exact release tag. `-EngineeringBuild` permits technical testing but writes
only under `build/installer/`; it must never be published. `-SkipNsis` stops
after the smoke-tested onedir build.

Application binaries are installed under `%LOCALAPPDATA%\Programs\Geospatial Extraction Studio`. User downloads, processed rasters, caches, logs, exports, and the SQLite database remain under `%LOCALAPPDATA%\Geospatial Extraction Studio\data` and are deliberately preserved by uninstall.

`runtime-components.json` pins the immutable Astral
`python-build-standalone` release archive, combined runtime license document,
CPython version, incorporated OpenSSL/libffi/SQLite versions and sources, and
the hashes of every runtime DLL expected in the finished application.
`prepare-runtime.ps1` freshly extracts that verified archive for each build;
arbitrary local Python installations are not accepted. The PyInstaller
toolchain is fully pinned in `backend/requirements-build.txt`, and
`build-components.json` hash-pins the licenses for the bootloader and runtime
hooks that contribute to the executable.

After PyInstaller, `audit_frozen_binary.py` scans the completed onedir tree.
Every `.exe`, `.dll`, and `.pyd` must resolve by exact hash to the verified
runtime, an installed approved Python distribution, or the detailed wheel
native-library inventory. It emits `FINAL_BINARY_INVENTORY.json` and copies it,
the runtime policy, combined runtime notices, and build-tool licenses into the
installed legal bundle before smoke testing. There is no engineering override
for an unrecognized final native file.

The same audit parses `EXE-00.toc`, `PYZ-00.toc`, and the actual final
executable. It requires the embedded archive inventory and PYZ bytes to match
the controlled build artifacts, matches immutable PE code sections to the
hash-pinned bootloader in `build-components.json`, and maps every PYZ module to
the verified runtime archive, application source, or an approved Python wheel
with a matching `RECORD` hash. It emits `PURE_PYTHON_INVENTORY.json` and
`EXECUTABLE_PROVENANCE.json`. Setuptools and `_distutils_hack` are intentionally
excluded from the application as build-only components.

Frontend notices are driven by the production graph returned from the locked
pnpm installation. `frontend-components.json` approves the exact graph,
declared licenses, lockfile digest, and license-file hashes. Any new, missing,
or changed runtime package blocks the frontend production build. The final
frozen-app audit rechecks the copied policy, exact license directory set, and
each installed frontend license hash and emits `FRONTEND_BUNDLE_INVENTORY.json`.

An approval is valid only for the wheel directories listed in its approval record. The collector verifies the pinned distribution version, hashes and required markers in every license-evidence file, records a SHA-256 digest for every DLL, copies approved native evidence and required corresponding source into the installed license bundle, and generates `NATIVE_REVIEW_SUMMARY.md`. A dependency update invalidates the approval until its evidence is reviewed again.

Each wheel's DELVEWHEEL build record is also hash-pinned and retained under
native-build/. Where a native library exposes a safe version API, the generated
inventory records that runtime version. An approval may define wheel-specific
version assertions; any mismatch blocks the release. Tag-specific upstream
license files retained under `packaging/native-evidence/` record their official
source URL and immutable digest in `native-evidence-registry.json`.
Corresponding-source archives and exact vcpkg port recipes are retained under
`packaging/native-source/`. Microsoft webpages are linked, not copied; the
project-authored redistribution audit records the reviewed runtime hashes.
Publication also requires the exact complete Visual Studio Community installation
and installed REDIST pointer digest recorded by release policy. The collector
also validates `visual-studio-entitlement.json`, which scopes Community use to
this Apache-2.0 open-source project.

`python-components.json` is an approval manifest, not an automatically inferred
license list. It must exactly match the installer lock. Every entry pins the
installed license-file inventory and hashes; an unknown status, version change,
new or removed notice file, or changed digest blocks publication pending review.
MPL/GPL-family license classifications additionally require verified source
evidence. Exact retained Python source and recipient instructions live under
`packaging/python-source/` and are copied into the installed legal bundle.

Before publication, replace a blocking status with `approved` only after retaining the exact controlling notice and any required corresponding source, relinking instructions, license selection, or vendor redistribution authority. Never approve a component from its DLL filename or SPDX label alone. Sign the final installer and checksum through the release signing process; this repository does not contain a private signing key.
