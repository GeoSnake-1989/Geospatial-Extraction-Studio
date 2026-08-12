from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


class StorageSafetyError(ValueError):
    pass


def directory_stats(path: Path) -> dict[str, int]:
    files = 0
    size = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                files += 1
                size += item.stat().st_size
    return {"files": files, "bytes": size}


def clear_directory_contents(path: Path) -> dict[str, int]:
    before = directory_stats(path)
    path.mkdir(parents=True, exist_ok=True)
    for item in path.iterdir():
        if item.is_symlink() or item.is_file():
            item.unlink(missing_ok=True)
        elif item.is_dir():
            shutil.rmtree(item)
    return before


def managed_path(path_value: str, root: Path) -> Path:
    path = Path(path_value).resolve()
    managed_root = root.resolve()
    if path == managed_root or not path.is_relative_to(managed_root):
        raise StorageSafetyError(
            "Refusing to remove a path outside Geospatial Extraction Studio managed storage"
        )
    return path


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path)


def storage_summary(
    cache: Path,
    original: Path,
    processed: Path,
    exports: Path,
    naip_original: Path | None = None,
    naip_processed: Path | None = None,
) -> dict[str, Any]:
    cache_stats = directory_stats(cache)
    original_stats = directory_stats(original)
    processed_stats = directory_stats(processed)
    export_stats = directory_stats(exports)
    naip_original_stats = directory_stats(naip_original) if naip_original else {"files": 0, "bytes": 0}
    naip_processed_stats = directory_stats(naip_processed) if naip_processed else {"files": 0, "bytes": 0}
    imagery_stats = {
        "files": naip_original_stats["files"] + naip_processed_stats["files"],
        "bytes": naip_original_stats["bytes"] + naip_processed_stats["bytes"],
    }
    terrain_bytes = original_stats["bytes"] + processed_stats["bytes"] - imagery_stats["bytes"]
    terrain_files = original_stats["files"] + processed_stats["files"] - imagery_stats["files"]
    generated_bytes = terrain_bytes + imagery_stats["bytes"] + export_stats["bytes"]
    return {
        "cache": cache_stats,
        "terrain": {
            "files": terrain_files,
            "bytes": terrain_bytes,
        },
        "imagery": imagery_stats,
        "osm_exports": export_stats,
        "generated_bytes": generated_bytes,
        "total_bytes": cache_stats["bytes"] + generated_bytes,
    }
