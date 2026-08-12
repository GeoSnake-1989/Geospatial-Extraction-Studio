# Native corresponding source and rebuild material

This directory retains the source archives and pinned build-recipe snapshots
referenced by `packaging/native-evidence-registry.json`. Their recorded digests
are checked by the installer license collector. Do not modify or recompress
these artifacts.

The generated installer notice bundle copies the relevant files into its own
`native-source/` directory. In particular, corresponding source is retained for
the LGPL-covered GEOS and libiconv libraries and for the MPL-covered FreeXL and
SpatiaLite libraries shipped as separate DLLs by the pinned Windows wheels.

## Rebuild and replace an LGPL library

1. Find the installed DLL and its wheel origin, version, hash, and upstream
   build reference in `THIRD_PARTY_COMPONENTS.json`.
2. Use the matching source archive and pinned recipe snapshot in this directory
   to build an ABI-compatible Windows DLL. Follow the upstream build instructions
   and license terms in the included source.
3. Stop Geospatial Extraction Studio. Back up the installed DLL, then replace it
   with the compatible build using the same filename recorded in the inventory.
   GEOS C and C++ DLLs must be rebuilt and replaced as a matching pair.
4. Restart the application and verify the affected raster/vector workflow. A
   replacement with a different ABI or exported-symbol set is not expected to
   load and is not supported as an application defect.

The application uses a one-directory installation layout: these native
libraries remain independent files and are not statically linked into the
application executable. No signing or integrity mechanism prevents a recipient
from replacing an installed DLL.

For the authoritative license text, source URL, retained filename, and digest,
consult `native-evidence-registry.json` and `THIRD_PARTY_NOTICES.md`.
