from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main
from app.storage import (
    StorageSafetyError,
    clear_directory_contents,
    managed_path,
    storage_summary,
)


def test_cache_cleanup_only_removes_managed_cache(tmp_path: Path):
    cache = tmp_path / "cache"
    outside = tmp_path / "keep.txt"
    (cache / "osmnx").mkdir(parents=True)
    (cache / "osmnx" / "response.json").write_bytes(b"cache-data")
    outside.write_text("keep", encoding="utf-8")

    removed = clear_directory_contents(cache)

    assert removed == {"files": 1, "bytes": 10}
    assert cache.is_dir()
    assert list(cache.iterdir()) == []
    assert outside.read_text(encoding="utf-8") == "keep"


def test_storage_summary_separates_cache_and_outputs(tmp_path: Path):
    cache = tmp_path / "cache"
    original = tmp_path / "original"
    processed = tmp_path / "processed"
    exports = tmp_path / "exports"
    for path in (cache, original, processed, exports):
        path.mkdir()
    (cache / "cache.json").write_bytes(b"123")
    (original / "source.tif").write_bytes(b"1234")
    (processed / "preview.tif").write_bytes(b"12")
    (exports / "extract.zip").write_bytes(b"12345")

    summary = storage_summary(cache, original, processed, exports)

    assert summary["cache"] == {"files": 1, "bytes": 3}
    assert summary["terrain"] == {"files": 2, "bytes": 6}
    assert summary["osm_exports"] == {"files": 1, "bytes": 5}
    assert summary["generated_bytes"] == 11
    assert summary["total_bytes"] == 14


def test_clear_cache_endpoint_preserves_completed_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache = tmp_path / "cache"
    original = tmp_path / "original"
    processed = tmp_path / "processed"
    exports = tmp_path / "exports"
    for path in (cache, original, processed, exports):
        path.mkdir()
    (cache / "response.json").write_bytes(b"cache")
    terrain = original / "terrain.tif"
    geodatabase = exports / "saved.gdb"
    terrain.write_bytes(b"terrain")
    geodatabase.mkdir()
    (geodatabase / "gdb").write_bytes(b"gdb")
    monkeypatch.setattr(main, "CACHE_DIR", cache)
    monkeypatch.setattr(main, "ORIGINAL_DIR", original)
    monkeypatch.setattr(main, "PROCESSED_DIR", processed)
    monkeypatch.setattr(main, "EXPORT_DIR", exports)
    monkeypatch.setattr(main, "osm_job_lock", asyncio.Lock())
    main.place_cache[("world", "cached place")] = []

    result = asyncio.run(main.clear_cache())

    assert result["removed"] == {"files": 1, "bytes": 5}
    assert list(cache.iterdir()) == []
    assert terrain.read_bytes() == b"terrain"
    assert (geodatabase / "gdb").read_bytes() == b"gdb"
    assert main.place_cache == {}


def test_managed_path_rejects_root_and_external_paths(tmp_path: Path):
    root = tmp_path / "managed"
    root.mkdir()
    child = root / "file.bin"
    child.write_bytes(b"x")

    assert managed_path(str(child), root) == child.resolve()
    with pytest.raises(StorageSafetyError):
        managed_path(str(root), root)
    with pytest.raises(StorageSafetyError):
        managed_path(str(tmp_path / "outside.bin"), root)


def test_osm_download_does_not_serve_archive_outside_managed_storage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    export_root = tmp_path / "managed" / "exports"
    export_root.mkdir(parents=True)
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    archive = outside_root / "osm123_county_OSM.zip"
    archive.write_bytes(b"outside-managed-storage")
    item = {
        "id": "osm123",
        "files": {
            "geodatabase": str(outside_root / "county.gdb"),
            "archive": str(archive),
        },
    }
    monkeypatch.setattr(main, "EXPORT_DIR", export_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_osm_export", lambda export_id: item if export_id == "osm123" else None)

    with pytest.raises(HTTPException) as exc_info:
        main.download_osm_export("osm123")

    assert exc_info.value.status_code == 404
    assert archive.read_bytes() == b"outside-managed-storage"


def test_dataset_delete_removes_files_and_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dataset_id = "abc123def456"
    original_root = tmp_path / "original"
    processed_root = tmp_path / "processed"
    original_root.mkdir()
    processed_root.mkdir()
    original = original_root / f"{dataset_id}_usgs_3dep.tif"
    processed = processed_root / f"{dataset_id}_preview.tif"
    original.write_bytes(b"source")
    processed.write_bytes(b"preview")
    item = {"id": dataset_id, "files": {"original": str(original), "processed": str(processed)}}
    deleted: list[str] = []
    monkeypatch.setattr(main, "ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_dataset", lambda requested_id: item if requested_id == dataset_id else None)
    monkeypatch.setattr(main, "delete_dataset_record", deleted.append)

    result = main.delete_dataset(dataset_id)

    assert result["id"] == dataset_id
    assert not original.exists()
    assert not processed.exists()
    assert deleted == [dataset_id]


def test_dataset_delete_accepts_generic_terrain_source_filename(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    dataset_id = "fed654cba321"
    original_root = tmp_path / "original"
    processed_root = tmp_path / "processed"
    original_root.mkdir()
    processed_root.mkdir()
    original = original_root / f"{dataset_id}_terrain_source.tif"
    processed = processed_root / f"{dataset_id}_preview.tif"
    original.write_bytes(b"source")
    processed.write_bytes(b"preview")
    item = {"id": dataset_id, "files": {"original": str(original), "processed": str(processed)}}
    monkeypatch.setattr(main, "ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_dataset", lambda requested_id: item if requested_id == dataset_id else None)
    monkeypatch.setattr(main, "delete_dataset_record", lambda _: None)

    main.delete_dataset(dataset_id)

    assert not original.exists()
    assert not processed.exists()


def test_dataset_delete_handles_legacy_absolute_paths_and_duplicate_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dataset_id = "123456abcdef"
    current_original = tmp_path / "current" / "original"
    current_processed = tmp_path / "current" / "processed"
    legacy_data = tmp_path / "legacy" / "data"
    legacy_original = legacy_data / "original"
    legacy_processed = legacy_data / "processed"
    for path in (current_original, current_processed, legacy_original, legacy_processed):
        path.mkdir(parents=True)

    original_name = f"{dataset_id}_usgs_3dep.tif"
    processed_name = f"{dataset_id}_preview.tif"
    copies = [
        current_original / original_name,
        current_processed / processed_name,
        legacy_original / original_name,
        legacy_processed / processed_name,
    ]
    for path in copies:
        path.write_bytes(b"data")
    item = {
        "id": dataset_id,
        "files": {
            "original": str(legacy_original / original_name),
            "processed": str(legacy_processed / processed_name),
        },
    }
    deleted: list[str] = []
    monkeypatch.setattr(main, "ORIGINAL_DIR", current_original)
    monkeypatch.setattr(main, "PROCESSED_DIR", current_processed)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", (legacy_data,))
    monkeypatch.setattr(main, "get_dataset", lambda requested_id: item if requested_id == dataset_id else None)
    monkeypatch.setattr(main, "delete_dataset_record", deleted.append)

    result = main.delete_dataset(dataset_id)

    assert result["id"] == dataset_id
    assert all(not path.exists() for path in copies)
    assert deleted == [dataset_id]


def test_osm_delete_removes_export_and_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    export_root = tmp_path / "exports"
    export_dir = export_root / "osm123"
    geodatabase = export_dir / "county.gdb"
    geodatabase.mkdir(parents=True)
    (geodatabase / "gdb").write_bytes(b"data")
    archive = export_root / "osm123_county_OSM.zip"
    archive.write_bytes(b"zip")
    item = {
        "id": "osm123",
        "files": {"geodatabase": str(geodatabase), "archive": str(archive)},
    }
    deleted: list[str] = []
    monkeypatch.setattr(main, "EXPORT_DIR", export_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_osm_export", lambda export_id: item if export_id == "osm123" else None)
    monkeypatch.setattr(main, "delete_osm_export_record", deleted.append)
    monkeypatch.setattr(main, "osm_job_lock", asyncio.Lock())

    result = asyncio.run(main.delete_osm_export("osm123"))

    assert result["id"] == "osm123"
    assert not export_dir.exists()
    assert not archive.exists()
    assert deleted == ["osm123"]


def test_osm_delete_removes_geopackage_export_and_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    export_root = tmp_path / "exports"
    export_dir = export_root / "gpkg123"
    export_dir.mkdir(parents=True)
    dataset = export_dir / "county.gpkg"
    dataset.write_bytes(b"gpkg")
    archive = export_root / "gpkg123_county_OSM.zip"
    archive.write_bytes(b"zip")
    item = {
        "id": "gpkg123",
        "output_format": "geopackage",
        "files": {"geodatabase": str(dataset), "archive": str(archive)},
    }
    deleted: list[str] = []
    monkeypatch.setattr(main, "EXPORT_DIR", export_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_osm_export", lambda export_id: item if export_id == "gpkg123" else None)
    monkeypatch.setattr(main, "delete_osm_export_record", deleted.append)
    monkeypatch.setattr(main, "osm_job_lock", asyncio.Lock())

    result = asyncio.run(main.delete_osm_export("gpkg123"))

    assert result["id"] == "gpkg123"
    assert result["message"] == "OSM dataset deleted"
    assert not export_dir.exists()
    assert not archive.exists()
    assert deleted == ["gpkg123"]


def test_osm_delete_removes_stale_history_without_touching_external_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    export_root = tmp_path / "managed" / "exports"
    export_root.mkdir(parents=True)
    external_root = tmp_path / "old-application" / "exports"
    external_geodatabase = external_root / "stale123" / "county.gdb"
    external_geodatabase.mkdir(parents=True)
    (external_geodatabase / "gdb").write_bytes(b"external")
    external_archive = external_root / "stale123_county_OSM.zip"
    external_archive.write_bytes(b"external-zip")
    item = {
        "id": "stale123",
        "files": {
            "geodatabase": str(external_geodatabase),
            "archive": str(external_archive),
        },
    }
    deleted: list[str] = []
    monkeypatch.setattr(main, "EXPORT_DIR", export_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_osm_export", lambda export_id: item if export_id == "stale123" else None)
    monkeypatch.setattr(main, "delete_osm_export_record", deleted.append)
    monkeypatch.setattr(main, "osm_job_lock", asyncio.Lock())

    result = asyncio.run(main.delete_osm_export("stale123"))

    assert result["removed_files"] is False
    assert "entry removed" in result["message"]
    assert external_geodatabase.is_dir()
    assert external_archive.is_file()
    assert deleted == ["stale123"]


def test_storage_summary_reports_naip_separately_from_terrain(tmp_path: Path):
    cache = tmp_path / "cache"
    original = tmp_path / "original"
    processed = tmp_path / "processed"
    exports = tmp_path / "exports"
    naip_original = original / "naip"
    naip_processed = processed / "naip"
    for path in (cache, original, processed, exports, naip_original, naip_processed):
        path.mkdir(parents=True, exist_ok=True)
    (original / "terrain.tif").write_bytes(b"terrain")
    (processed / "terrain-preview.tif").write_bytes(b"preview")
    (naip_original / "manifest.json").write_bytes(b"meta")
    (naip_processed / "imagery.tif").write_bytes(b"imagery")

    summary = storage_summary(
        cache,
        original,
        processed,
        exports,
        naip_original,
        naip_processed,
    )

    assert summary["terrain"] == {"files": 2, "bytes": 14}
    assert summary["imagery"] == {"files": 2, "bytes": 11}
    assert summary["generated_bytes"] == 25


def test_naip_delete_removes_only_managed_imagery_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    imagery_id = "abc123def456"
    original_root = tmp_path / "original" / "naip"
    processed_root = tmp_path / "processed" / "naip"
    original_root.mkdir(parents=True)
    processed_root.mkdir(parents=True)
    manifest = original_root / f"{imagery_id}_naip_sources.json"
    imagery = processed_root / f"{imagery_id}_naip_mosaic.tif"
    preview = processed_root / f"{imagery_id}_naip_preview.png"
    for path in (manifest, imagery, preview):
        path.write_bytes(b"data")
    item = {
        "id": imagery_id,
        "files": {
            "manifest": str(manifest),
            "imagery": str(imagery),
            "preview": str(preview),
        },
    }
    deleted: list[str] = []
    monkeypatch.setattr(main, "NAIP_ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "NAIP_PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main, "get_naip_imagery", lambda requested_id: item if requested_id == imagery_id else None)
    monkeypatch.setattr(main, "delete_naip_imagery_record", deleted.append)
    monkeypatch.setattr(main, "naip_job_lock", asyncio.Lock())

    result = asyncio.run(main.delete_naip_imagery(imagery_id))

    assert result["id"] == imagery_id
    assert result["removed_files"] is True
    assert all(not path.exists() for path in (manifest, imagery, preview))
    assert deleted == [imagery_id]
