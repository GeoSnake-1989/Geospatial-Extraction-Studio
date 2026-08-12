# Python corresponding-source availability

This directory retains exact source distributions required by the licenses of
Python components included in the Windows binary installer. The release
collector verifies their hashes and copies them into the installed legal bundle.

## Certifi 2026.6.17

Certifi and its Mozilla-derived CA bundle are distributed under MPL-2.0. The
application distributes the upstream package without source modifications.
Recipients can obtain the exact Source Code Form used for this release here:

- retained file: `certifi/certifi-2026.6.17.tar.gz`
- PyPI source distribution: https://files.pythonhosted.org/packages/c9/c7/424b75da314c1045981bd9777432fad05a9e0c69daa4ed7e308bbaffe405/certifi-2026.6.17.tar.gz
- upstream repository: https://github.com/certifi/python-certifi
- SHA-256: `024c88eeec92ca068db80f02b8b07c9cef7b9fe261d1d535abfd5abd6f6af432`
- governing license: Mozilla Public License 2.0

The MPL-2.0 license notice is included both in the source distribution and in
the installed dependency-license bundle. Extract the retained archive with any
standard `tar.gz` tool to inspect, modify, or rebuild its contents.
