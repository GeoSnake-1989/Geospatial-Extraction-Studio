"""Read version strings exposed by native DLLs bundled in the Python wheels."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

try:
    import pefile
except ImportError:
    pefile = None


STRING_QUERIES = {
    "freexl-": ("freexl_version", ()),
    "gdal-": ("GDALVersionInfo", (b"--version",)),
    "geos_c-": ("GEOSversion", ()),
    "json-c-": ("json_c_version", ()),
    "libcurl-": ("curl_version", ()),
    "libexpat-": ("XML_ExpatVersion", ()),
    "liblzma-": ("lzma_version_string", ()),
    "libpng16-": ("png_get_libpng_ver", (None,)),
    "libcrypto-": ("OpenSSL_version", (0,)),
    "netcdf-": ("nc_inq_libvers", ()),
    "openjp2-": ("opj_version", ()),
    "spatialite-": ("spatialite_version", ()),
    "sqlite3-": ("sqlite3_libversion", ()),
    "tiff-": ("TIFFGetVersion", ()),
    "z-": ("zlibVersion", ()),
    "zlib1-": ("zlibVersion", ()),
    "zstd-": ("ZSTD_versionString", ()),
}


def query_version(dll_path: Path) -> dict[str, str]:
    name = dll_path.name.lower()
    matching = next(
        (spec for prefix, spec in STRING_QUERIES.items() if name.startswith(prefix)),
        None,
    )
    if matching is None and name.startswith("hdf5-"):
        return query_hdf5(dll_path)
    if matching is None and name.startswith("libpq-"):
        return query_libpq(dll_path)
    if matching is None and name.startswith("iconv-"):
        return query_iconv(dll_path)
    if matching is None and name.startswith(("libwebp-", "libsharpyuv-")):
        return query_packed_version(dll_path)
    if matching is None and name.startswith("pcre2-"):
        return query_pcre2(dll_path)
    if matching is None and name.startswith("libxml2-"):
        return query_exported_pointer(dll_path, "xmlParserVersion")
    if matching is None and name.startswith("proj_"):
        return query_proj(dll_path)
    if matching is None and name.startswith("qhull_r-"):
        return query_exported_string(dll_path, "qh_version")
    if matching is None and name.startswith("minizip-"):
        return query_exported_string(dll_path, "unz_copyright")
    if matching is None:
        return {
            "status": "no-runtime-query",
            "candidate_exports": candidate_version_exports(dll_path),
        }

    function_name, arguments = matching
    library = ctypes.CDLL(str(dll_path))
    function = getattr(library, function_name)
    function.restype = ctypes.c_char_p
    value = function(*arguments)
    return {
        "status": "identified",
        "function": function_name,
        "version": value.decode("utf-8", errors="replace") if value else "",
    }


def candidate_version_exports(dll_path: Path) -> list[str]:
    if pefile is None:
        return []
    image = pefile.PE(str(dll_path), fast_load=True)
    image.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]]
    )
    names = []
    for symbol in getattr(image, "DIRECTORY_ENTRY_EXPORT", ()).symbols:
        if not symbol.name:
            continue
        name = symbol.name.decode("ascii", errors="replace")
        if any(token in name.lower() for token in ("version", "release", "copyright")):
            names.append(name)
    return sorted(names)


def query_iconv(dll_path: Path) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    value = ctypes.c_int.in_dll(library, "_libiconv_version").value
    return {
        "status": "identified",
        "function": "_libiconv_version",
        "version": f"{value >> 8}.{value & 0xFF}",
    }


def query_packed_version(dll_path: Path) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    function_name = (
        "SharpYuvGetVersion"
        if dll_path.name.lower().startswith("libsharpyuv-")
        else "WebPGetDecoderVersion"
    )
    value = getattr(library, function_name)()
    version = f"{value >> 16}.{(value >> 8) & 0xFF}.{value & 0xFF}"
    return {"status": "identified", "function": function_name, "version": version}


def query_pcre2(dll_path: Path) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    buffer = ctypes.create_string_buffer(64)
    result = library.pcre2_config_8(11, buffer)
    if result < 0:
        raise RuntimeError("pcre2_config_8 failed")
    return {
        "status": "identified",
        "function": "pcre2_config_8",
        "version": buffer.value.decode("ascii", errors="replace"),
    }


def query_exported_string(dll_path: Path, symbol: str) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    value = ctypes.string_at(ctypes.addressof(ctypes.c_char.in_dll(library, symbol)))
    return {
        "status": "identified",
        "function": symbol,
        "version": value.decode("utf-8", errors="replace"),
    }


def query_exported_pointer(dll_path: Path, symbol: str) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    value = ctypes.c_char_p.in_dll(library, symbol).value or b""
    return {
        "status": "identified",
        "function": symbol,
        "version": value.decode("utf-8", errors="replace"),
    }


def query_proj(dll_path: Path) -> dict[str, str]:
    class ProjInfo(ctypes.Structure):
        _fields_ = [
            ("major", ctypes.c_int),
            ("minor", ctypes.c_int),
            ("patch", ctypes.c_int),
            ("release", ctypes.c_char_p),
            ("version", ctypes.c_char_p),
            ("searchpath", ctypes.c_char_p),
            ("paths", ctypes.POINTER(ctypes.c_char_p)),
            ("path_count", ctypes.c_size_t),
        ]

    library = ctypes.CDLL(str(dll_path))
    library.proj_info.restype = ProjInfo
    info = library.proj_info()
    return {
        "status": "identified",
        "function": "proj_info",
        "version": f"{info.major}.{info.minor}.{info.patch}",
    }


def query_hdf5(dll_path: Path) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    major, minor, release = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
    result = library.H5get_libversion(
        ctypes.byref(major), ctypes.byref(minor), ctypes.byref(release)
    )
    if result < 0:
        raise RuntimeError("H5get_libversion failed")
    return {
        "status": "identified",
        "function": "H5get_libversion",
        "version": f"{major.value}.{minor.value}.{release.value}",
    }


def query_libpq(dll_path: Path) -> dict[str, str]:
    library = ctypes.CDLL(str(dll_path))
    value = library.PQlibVersion()
    return {
        "status": "identified",
        "function": "PQlibVersion",
        "version": str(value),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="+", type=Path)
    args = parser.parse_args()
    results = []
    for directory in args.directories:
        with __import__("os").add_dll_directory(str(directory.resolve())):
            for dll_path in sorted(directory.glob("*.dll")):
                record = {"directory": directory.name, "dll": dll_path.name}
                try:
                    record.update(query_version(dll_path))
                except (AttributeError, OSError, RuntimeError) as error:
                    record.update(status="query-failed", error=str(error))
                results.append(record)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
