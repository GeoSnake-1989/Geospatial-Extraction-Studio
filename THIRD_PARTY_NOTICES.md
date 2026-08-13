# Geospatial Extraction Studio third-party notices

Geospatial Extraction Studio includes or depends on third-party software and data. Those
components are not covered by Geospatial Extraction Studio's Apache License 2.0. This file
records the principal runtime components in the current build; the license
files shipped with every installed package remain controlling.

When packaging Geospatial Extraction Studio, include this file and preserve all `LICENSE`,
`NOTICE`, `COPYING`, and `*.dist-info/licenses/` files from dependencies that
are included in the package. Recheck this inventory whenever dependencies are
updated. Content authorship and AI-assistance records are described in
`CONTENT_PROVENANCE.md`.

The official source release excludes local virtual environments,
`node_modules`, package caches, generated data, runtime databases, logs, build
output, and research PDFs. If a distributor chooses to ship dependency
binaries or an installer, that distributor assumes the additional license,
notice, source-availability, and relinking obligations applicable to that
packaging method.

## Frontend runtime components

| Component | Version | License | Copyright or attribution |
| --- | --- | --- | --- |
| Leaflet | 1.9.4 | BSD-2-Clause | Copyright (c) 2010-2023 Volodymyr Agafonkin; Copyright (c) 2010-2011 CloudMade |
| Lucide React / Lucide Icons | 1.24.0 | ISC | Copyright (c) 2026 Lucide Icons and Contributors |
| Feather-derived Lucide icons | included with Lucide | MIT | Copyright (c) 2013-present Cole Bemis |
| React | 19.2.7 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates |
| React DOM | 19.2.7 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates |
| Scheduler | 0.27.0 | MIT | Copyright (c) Meta Platforms, Inc. and affiliates |
| three.js | 0.185.1 | MIT | Copyright (c) 2010-2026 three.js authors |
| Vite build runtime | 8.1.4 | MIT and bundled component licenses | Copyright (c) 2019-present, VoidZero Inc. and Vite contributors |


## Backend runtime components

The backend's direct dependencies are listed below. Their transitive
dependencies and native libraries are recorded in the installed environment's
package metadata and license directories and must be retained in any packaged
environment.

| Component | Current installed version | License |
| --- | --- | --- |
| FastAPI | 0.139.0 | MIT |
| Uvicorn | 0.51.0 | BSD-3-Clause |
| HTTPX | 0.28.1 | BSD-3-Clause |
| Requests | 2.34.2 | Apache-2.0 |
| NumPy | 2.5.1 | BSD-3-Clause and bundled component licenses |
| Rasterio | 1.5.0 | BSD-3-Clause and bundled native-library licenses |
| Pydantic | 2.13.4 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| OSMnx | 2.1.0 | MIT |
| GeoPandas | 1.1.4 | BSD-3-Clause |
| Pyogrio | 0.13.0 | MIT |

Important transitive and native runtime components in the current Windows
environment include:

| Component | Current installed version | License / distribution note |
| --- | --- | --- |
| Shapely | 2.1.2 | BSD-3-Clause; its wheel includes the GEOS library |
| GEOS | bundled with Shapely | LGPL-2.1 |
| PyProj / PROJ | 3.7.2 / bundled | MIT and bundled data/component licenses |
| Certifi | 2026.6.17 | MPL-2.0 |
| pandas | 3.0.3 | BSD-3-Clause |
| NetworkX | 3.6.1 | BSD-3-Clause |
| OpenBLAS and LAPACK | bundled with NumPy | BSD-family licenses |
| GCC runtime portions | bundled with NumPy | GPL-3.0-or-later with GCC Runtime Library Exception 3.1 |

A source checkout that installs dependencies from their normal package indexes
receives these license files with the packages. A redistributed virtual
environment, standalone executable, or installer must preserve the controlling
package and native-library license files. In particular, retain Shapely's
`LICENSE_GEOS`, Certifi's MPL-2.0 text, NumPy's complete bundled-component
notice, and the license directories supplied with Rasterio, GDAL, PROJ, and
Pyogrio. Do not flatten or remove `*.dist-info/licenses/` directories.

Certifi's exact 2026.6.17 Source Code Form is retained at
`packaging/python-source/certifi/certifi-2026.6.17.tar.gz`, hash-pinned in
`packaging/python-components.json`, and copied into the installed legal bundle.
Recipients are informed how to obtain, inspect, modify, and rebuild that
MPL-2.0 source in `python-source/README.md`.

GEOS is dynamically loaded from the Shapely wheel in the current Windows
environment. A distributor must comply with LGPL-2.1 requirements applicable
to that packaging method, including providing the license and required library
source or a valid source offer, preserving the user's ability to replace or
relink the LGPL library, and not forbidding reverse engineering for debugging
modifications to that library. Obtain packaging-specific legal advice before
shipping a monolithic or statically linked build.

### Binary-installer release gate

The binary build uses `backend/requirements-installer.lock.txt`,
`packaging/python-components.json`, `packaging/native-components.json`, and
`packaging/collect_licenses.py` to generate an installed license bundle and
machine-readable component inventory. Every Python package must match an exact
approved version, canonical license classification, complete license-file
inventory, and evidence hash. The build also fails when a wheel DLL is not
mapped exactly once. Each DLL record includes its SHA-256 digest, byte size,
originating wheel directory, pinned Python distribution, license classification,
and review status. The engineering override is not a legal approval and cannot
write to `release/`.

The CPython runtime is not taken from an ambient developer installation. The
publication build uses the immutable Astral `python-build-standalone` 20260303
archive for CPython 3.12.13 and verifies its complete archive digest. The
installed legal bundle includes the exact combined runtime notices from that
release. Those notices cover CPython and incorporated libraries, including
libffi 3.4.6 (MIT), OpenSSL 3.5.5 (Apache-2.0), SQLite 3.50.4 (public-domain
dedication), and other standard-library components. The exact controlling
versions, upstream source URLs, source hashes, critical binary hashes, and
Visual C++ runtime evidence are recorded in `packaging/runtime-components.json`.

PyInstaller 6.22.0 contributes its bootloader to the generated application and
is licensed under GPL-2.0-or-later with the PyInstaller bootloader exception;
the exception permits distribution of the combined executable under this
application's license. PyInstaller runtime hooks are Apache-2.0, and the
contributed hooks package is Apache-2.0 or GPL-2.0-or-later. Their exact license
files are hash-pinned in `packaging/build-components.json` and copied into the
installed legal bundle.

NSIS 3.12 contributes the installer and uninstaller stubs. This release uses
only the zlib compressor; NSIS and that compression module are covered by the
zlib/libpng license. The exact `makensis.exe` version and SHA-256, selected
compressor, retained license notice, and final installer digest are fail-closed
and recorded in the adjacent installer provenance report.
The final release audit also reads the actual PyInstaller PYZ and executable
archives. Every compiled Python module must map to this application, the pinned
CPython archive, or one of the 38 approved runtime distributions with a matching
wheel `RECORD` hash. Build-only Setuptools and `_distutils_hack` modules are
explicitly excluded from the frozen application. The selected PyInstaller
bootloader and its immutable executable code sections are hash-verified, and
the exact outer archive and embedded PYZ inventories are retained with the
installed notices.

PCRE2 10.47 is recorded as BSD-3-Clause WITH PCRE2-exception, with its optional
JIT portions separately covered by BSD-2-Clause; the complete upstream PCRE2
and SLJIT licenses and binary-library exception are retained.

The current pinned wheel build inventories 73 DLLs across 33 component families. All
73 have evidence-backed approval for their exact wheel scope. Exact upstream
open-source notices are hash-pinned in `packaging/native-evidence`; GEOS, GNU libiconv,
FreeXL, and SpatiaLite corresponding-source archives and pinned build recipes
are retained under `packaging/native-source` and copied into the installed
license bundle. The retained Microsoft vcpkg recipe snapshots are MIT-licensed;
their license is hash-pinned and included with both source and installed legal
bundles. Rasterio's `szip` DLL is identified by its pinned vcpkg recipe
as libaec's BSD-licensed SZIP compatibility library. XZ's own versioned
licensing record identifies the bundled `liblzma` DLLs as 0BSD.

Microsoft webpage copies are not redistributed. A project-authored audit record
links to the controlling Microsoft terms and records the reviewed runtime hashes.
Microsoft runtime approval is valid only on a release host where the collector
finds the exact complete Visual Studio Community installation and installed REDIST
pointer digest recorded by policy. A separate entitlement record limits the
Community-edition basis to developing, testing, and releasing this Apache-2.0
open-source project; it does not authorize proprietary or unrelated work. Keep
LGPL libraries as separate,
replaceable DLLs and distribute the retained corresponding source. A wheel,
dependency, build-layout, or evidence-hash change invalidates the applicable
approval. Do not convert this application to a one-file or statically linked
distribution without a new review.

## Map data and services

Geospatial Extraction Studio displays OpenStreetMap data, uses the public Nominatim service for
user-triggered place searches, and uses configured Overpass endpoints for
explicitly requested feature extracts.

- Map data copyright OpenStreetMap contributors.
- OpenStreetMap data is available under the Open Database License 1.0:
  https://www.openstreetmap.org/copyright
- Attribution guidelines:
  https://osmfoundation.org/wiki/Licence/Attribution_Guidelines
- Standard tile service policy:
  https://operations.osmfoundation.org/policies/tiles/

A custom tile provider is accepted only when its tile URL, visible attribution,
and direct license/terms URL are configured together. Incomplete configuration
or a non-HTTP(S) URL stops application startup. Provider-specific token,
branding, caching, access, and usage restrictions remain controlling and must
be reviewed before enabling that provider.
- Public Nominatim usage policy:
  https://operations.osmfoundation.org/policies/nominatim/
- Overpass API status and instance information:
  https://wiki.openstreetmap.org/wiki/Overpass_API

The OpenStreetMap data license does not grant rights to third-party trademarks
or to use the public tile and geocoding servers outside their usage policies.
Geospatial Extraction Studio's Apache License 2.0 does not apply to downloaded or exported OSM data.
An exported OSM geodatabase is made available under ODbL 1.0 and must retain
its accompanying attribution and license notice.

## NAIP imagery data and hosted access

National Agriculture Imagery Program (NAIP) imagery is produced by the U.S.
Department of Agriculture Farm Service Agency. U.S. government-authored data
is generally public domain in the United States unless an individual product
record states otherwise. Third-party content and use outside the United States
can have different status. Credit the USDA Farm Service Agency and retain each
export's generated source manifest, including collection, item, provider,
asset, license-link, and source-record metadata.

The configured STAC catalog's metadata controls the application's license
record. Asset-level declarations take precedence over item-level declarations
only when both do not conflict; item declarations otherwise take precedence
over collection-level declarations. The STAC specification uses `other`
for non-SPDX terms and deprecates the older `proprietary` and `various` values;
when one of those values appears with a license link, the linked terms describe
the license. The application preserves raw declarations and links and refuses
extraction when asset/item declarations conflict or a legacy non-SPDX
asset/item value lacks a same-record license link.

As reviewed for this release, the Planetary Computer NAIP collection uses the
deprecated STAC value `license: proprietary` together with a license link titled
"Public Domain." This is legacy catalog syntax, not by itself a claim that NAIP
is closed data. The linked USDA policy says most FSA website information is
public domain, and the USDA Ag Data Commons NAIP record identifies the dataset
as U.S. Public Domain. Retain the source records and verify item- or asset-level
exceptions before redistribution.

Geospatial Extraction Studio discovers and reads NAIP assets through the
Microsoft Planetary Computer STAC and data-access APIs. Microsoft hosts a copy
of upstream NAIP imagery; its service availability, access tokens, throttling,
and terms remain separate from this application's Apache License 2.0. “Latest”
means the newest acquisition published in the configured STAC catalog.

- USDA NAIP program: https://naip-usdaonline.hub.arcgis.com/
- USDA Ag Data Commons NAIP record (U.S. Public Domain): https://agdatacommons.nal.usda.gov/articles/dataset/NAIP_Digital_Ortho_Photo_Image_Geospatial_Data_Presentation_Form_remote-sensing_image/24664908
- Microsoft Planetary Computer documentation: https://planetarycomputer.microsoft.com/docs/
- Planetary Computer STAC API: https://planetarycomputer.microsoft.com/api/stac/v1/
- Planetary Computer NAIP collection metadata: https://planetarycomputer.microsoft.com/api/stac/v1/collections/naip
- NAIP public-data catalog information: https://registry.opendata.aws/naip/

Geospatial Extraction Studio's Apache License 2.0 does not apply to downloaded
NAIP imagery, catalog metadata, hosted services, or third-party marks.

## Elevation data

USGS-authored 3D Elevation Program (3DEP) products are generally public-domain
U.S. government works in the United States unless a product record states
otherwise. Copyright status can differ for third-party material and outside
the United States. Geospatial Extraction Studio retains the provider, source URL, product name, and
attribution in each dataset record.

- Credit: U.S. Geological Survey, The National Map, 3D Elevation Program.
- Program and data-use information: https://www.usgs.gov/3d-elevation-program

The names USDA, NAIP, Microsoft Planetary Computer, USGS, The National Map, 3DEP, OpenStreetMap, and the names of the
software projects above are used descriptively and do not imply endorsement.

## Common license texts

The exact license text delivered with each package is controlling. The common
permissive terms used by the frontend runtime packages are reproduced below
for distribution convenience.

### MIT License

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The applicable copyright notice above and this permission notice shall be
included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

### BSD 2-Clause License

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the applicable copyright
   notice above, this list of conditions, and the following disclaimer.
2. Redistributions in binary form must reproduce the applicable copyright
   notice above, this list of conditions, and the following disclaimer in the
   documentation and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

### ISC License

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the applicable
copyright notice above and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.

The Apache License 2.0 and Mozilla Public License 2.0 texts must be preserved
from the applicable package license directories when those packages are
included in a distribution:

- https://www.apache.org/licenses/LICENSE-2.0
- https://www.mozilla.org/MPL/2.0/
