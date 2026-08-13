# Microsoft Visual C++ Runtime redistribution audit

This is a project-authored release record. It does not reproduce Microsoft
webpage content or Microsoft software-license terms. Follow the linked official
terms; they remain controlling.

## Review record

- Reviewed: 2026-08-12
- Visual Studio product observed on the release host: Visual Studio Community
  2026 (`Microsoft.VisualStudio.Product.Community`)
- Observed installation version: `18.1.11312.151`
- Installed REDIST pointer SHA-256:
  `2d69e3b0ac782d5513b503bafdf269a93c4fec0f1f8efac82bfbfa4b6296aef5`
- Official Visual Studio 2026 redistribution list:
  https://learn.microsoft.com/visualstudio/releases/2026/redistribution
- Official Visual Studio Community 2026 license terms:
  https://visualstudio.microsoft.com/license-terms/vs2026-ga-community/
- Stable installed REDIST reference:
  https://aka.ms/vs/18/redistribution

## Release conclusion and limitations

The official redistribution list states that a person with a validly licensed
copy of an eligible Visual Studio edition may distribute the listed files
with their program in unmodified form, subject to that edition's license terms.
The release collector therefore fails unless it finds the exact complete Visual
Studio product/version above and the exact installed REDIST pointer digest.

The release also requires `packaging/visual-studio-entitlement.json`. That
project-authored record limits the approved Community use to developing,
testing, and releasing this Apache-2.0 open-source project, identifies the
release account, and pins the project-license digest. It does not authorize a
proprietary derivative or unrelated project.

This automated check establishes the installed product and release evidence; it
does not decide whether an organization satisfies every eligibility or license
condition. The release operator remains responsible for that determination.
The runtime bytes are inventoried and hashed on every release, and a dependency
or hash change invalidates this review.

## Runtime files covered by this review

| Wheel directory | Installed filename | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `numpy.libs` | `msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` | 575056 | `a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde` |
| `pandas.libs` | `msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` | 575056 | `a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde` |
| `pyogrio.libs` | `msvcp140-a4c2229bdc2a2a630acdc095b4d86008.dll` | 575056 | `a4c2229bdc2a2a630acdc095b4d86008e5c3e3bc7773174354f3da4f5beb9cde` |
| `pyproj.libs` | `msvcp140-0f885b509a685d2bbfa652fed26b5fb3.dll` | 557728 | `0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9` |
| `rasterio.libs` | `msvcp140-2a7008da6f9aae43c7a434835dcaf31e.dll` | 557640 | `2a7008da6f9aae43c7a434835dcaf31e2470d891be33471f5012859210eed268` |
| `shapely.libs` | `msvcp140-90bc62d4947a5878f1dc1057312f3be2.dll` | 557704 | `90bc62d4947a5878f1dc1057312f3be2137eb376039f4afda2f64c06353f2198` |
