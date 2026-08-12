# Windows binary installer

The supported design is a PyInstaller **onedir** application wrapped by an NSIS per-user installer. The application serves `frontend/dist` from FastAPI, so installed systems do not need Python, Node.js, Vite, or an OpenAI connection.

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
7. fail-closed inventory of every final executable, DLL, and Python extension;
8. frozen-app health/UI smoke test;
9. NSIS installer and SHA-256 checksum generation.

A normal build refuses to create `release/Geospatial-Extraction-Studio-Setup-0.4.0.exe` while any matched native component has a status other than `approved` in `native-components.json`. `-EngineeringBuild` permits technical testing but writes only under `build/installer/`; it must never be published. `-SkipNsis` stops after the smoke-tested onedir build.

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
Publication also requires the exact complete Visual Studio 2022 installation
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
