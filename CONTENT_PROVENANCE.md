# Geospatial Extraction Studio content provenance

This record describes authorship and third-party boundaries for the Apache-2.0
release of Geospatial Extraction Studio. It is not a substitute for contribution agreements or a
copyright registration.

## Application source and documentation

Geospatial Extraction Studio was developed with assistance from OpenAI Codex and ChatGPT. Jacob
Horwitz directed the work, selected and arranged the application's features,
reviewed outputs, tested behavior, and accepted or modified source and
documentation.

Jacob Horwitz owns the protectable rights in the original project material he
contributed and licenses that material in this release under the Apache License
2.0. This repository is owner-maintained and does not accept external
contributions. The license does not claim exclusive rights in public-domain
material, third-party material, facts, ideas, or material that applicable law
does not protect.

The copyright notice identifies Jacob Horwitz as the project owner. A
distributor must retain records needed to establish the origin and licensing
of every item included in a release.

## Excluded research documents

The two AI-assisted research PDFs previously stored at the project root are
not part of the Geospatial Extraction Studio distribution. They are intentionally excluded from
source archives, build artifacts, and the Geospatial Extraction Studio license grant.

## Brand artwork

The source artwork at `frontend/public/geospatial-extraction-studio-logo.png`
was generated with ChatGPT Image, supplied by the project owner, and selected
for use as Geospatial Extraction Studio branding on August 6, 2026. The active
`frontend/public/geospatial-extraction-studio-logo-green.png` presentation
variant recolors only the connected outer and backdrop regions to match the
application's dark-green palette.

Jacob Horwitz, the owner of the Geospatial Extraction Studio project and
canonical repository, confirmed control of the supplied files and authorized
their public release on August 7, 2026. The project makes no copyright claim
or copyright-license assertion for either logo file. The files are retained
solely as Geospatial Extraction Studio source-identifying branding; the
project's Apache License 2.0 grant does not grant trademark permission. A
public distribution of a modified version must replace the project name and
logos with its own branding.

## Runtime data and third-party components

OpenStreetMap data, USGS data, USDA NAIP data, hosted catalog services, software dependencies, native libraries, names,
marks, and other third-party material are not licensed under Geospatial Extraction Studio's Apache
License 2.0. Their controlling terms and required credits are documented in
`THIRD_PARTY_NOTICES.md`, provider metadata, package license files, and
generated export notices.

## Release record

For every external release, retain:

- the exact source revision and dependency lockfiles;
- `LICENSE`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, and this file;
- `ASSET_LICENSES.md`;
- a clean source archive containing `SOURCE-REVISION.txt` and only files tracked
  by that revision; the archive excludes `.venv`, `node_modules`, package
  caches, build output, generated data, runtime databases, logs, temporary
  files, and the excluded PDFs;
- all dependency `LICENSE`, `NOTICE`, `COPYING`, and
  `*.dist-info/licenses/` files if dependency binaries are distributed;
- the reviewed Python component policy, required Python corresponding source,
  source-availability instructions, and Visual Studio entitlement record;
- the approved immutable CPython runtime manifest, combined runtime notices,
  frontend and PyInstaller build-component policies, final frozen native and
  pure-Python inventories, and executable-provenance report;
- the configured tile provider's attribution and usage terms; and
- records showing the origin and review of material newly added to the release;
  and
- an owner review confirming that no unapproved third-party contribution is
  included in the release.

Before publishing through GitHub, create the repository locally and inspect
both `git status --short` and `git status --short --ignored`. A `.gitignore`
file controls normal Git staging; it is not a substitute for reviewing a
browser upload, copied directory, or release archive.
