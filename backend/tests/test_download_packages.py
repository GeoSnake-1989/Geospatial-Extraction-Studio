from __future__ import annotations

import asyncio
import json
from pathlib import Path
from zipfile import ZipFile

from fastapi import HTTPException

from app import main


def _finish_response(response) -> None:
    assert response.background is not None
    asyncio.run(response.background())


def test_dem_package_contains_raster_and_source_proof_for_legacy_history(
    tmp_path: Path, monkeypatch
):
    dataset_id = "abc123def456"
    original_root = tmp_path / "original"
    processed_root = tmp_path / "processed"
    cache_root = tmp_path / "cache"
    original_root.mkdir()
    processed_root.mkdir()
    raster = original_root / f"{dataset_id}_terrain_source.tif"
    raster.write_bytes(b"dem-raster")
    item = {
        "id": dataset_id,
        "label": "Colorado National Monument",
        "provider": "USGS 3DEP",
        "product": "USGS 3DEP Bare Earth DEM dynamic extract",
        "bounds": {"west": -108.6, "south": 39.0, "east": -108.5, "north": 39.1},
        "area_km2": 3.1,
        "provenance": {
            "service": "https://example.test/ImageServer",
            "source_url": "https://example.test/dem.tif",
            "license": "public domain",
        },
        "preview": {"spatial": {"crs": "EPSG:4326", "nodata": -9999}},
        "files": {
            "original": str(raster),
            "processed": str(processed_root / f"{dataset_id}_preview.tif"),
        },
    }
    monkeypatch.setattr(main, "ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main, "CACHE_DIR", cache_root)
    monkeypatch.setattr(main, "LEGACY_DATA_ROOTS", ())
    monkeypatch.setattr(main, "get_dataset", lambda requested_id: item)

    response = main.download_dataset(dataset_id, "package")
    archive_path = Path(response.path)
    assert response.filename == "Colorado_National_Monument_DEM.zip"
    with ZipFile(archive_path) as archive:
        folder = "Colorado_National_Monument_DEM"
        assert set(archive.namelist()) == {
            f"{folder}/{folder}.tif",
            f"{folder}/SOURCE_PROVENANCE.json",
            f"{folder}/SOURCE_PROVENANCE.md",
            f"{folder}/DATA_LICENSE_NOTICE.md",
        }
        assert archive.read(f"{folder}/{folder}.tif") == b"dem-raster"
        evidence = json.loads(archive.read(f"{folder}/SOURCE_PROVENANCE.json"))
        assert evidence["source_urls"] == [
            "https://example.test/ImageServer",
            "https://example.test/dem.tif",
        ]
        assert evidence["output"]["filename"] == f"{folder}.tif"
        assert evidence["output"]["sha256"]
        notice = archive.read(f"{folder}/DATA_LICENSE_NOTICE.md").decode("utf-8")
        assert "Data license and attribution notice" in notice
        assert item["provider"] in notice
    _finish_response(response)
    assert not archive_path.exists()


def test_aerial_package_contains_raster_and_source_proof_for_legacy_history(
    tmp_path: Path, monkeypatch
):
    imagery_id = "fed654cba321"
    original_root = tmp_path / "original" / "naip"
    processed_root = tmp_path / "processed" / "naip"
    cache_root = tmp_path / "cache"
    original_root.mkdir(parents=True)
    processed_root.mkdir(parents=True)
    manifest = original_root / f"{imagery_id}_naip_sources.json"
    raster = processed_root / f"{imagery_id}_naip_mosaic.tif"
    preview = processed_root / f"{imagery_id}_naip_preview.png"
    manifest.write_text(
        json.dumps(
            {
                "provider": "USDA NAIP",
                "items": [
                    {
                        "id": "tile-1",
                        "year": 2023,
                        "source_href": "https://example.test/naip.tif",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    raster.write_bytes(b"aerial-raster")
    preview.write_bytes(b"png")
    item = {
        "id": imagery_id,
        "label": "Grand Junction 2023",
        "provider": "USDA NAIP",
        "product": "NAIP AOI GeoTIFF mosaic",
        "area_km2": 3.1,
        "bands": "rgb",
        "spatial": {"crs": "EPSG:26912", "nodata": 0},
        "files": {
            "manifest": str(manifest),
            "imagery": str(raster),
            "preview": str(preview),
        },
    }
    monkeypatch.setattr(main, "NAIP_ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "NAIP_PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main, "CACHE_DIR", cache_root)
    monkeypatch.setattr(main, "get_naip_imagery", lambda requested_id: item)

    response = main.download_naip_imagery(imagery_id, "package")
    archive_path = Path(response.path)
    assert response.filename == "Grand_Junction_2023_Aerial_Imagery.zip"
    with ZipFile(archive_path) as archive:
        folder = "Grand_Junction_2023_Aerial_Imagery"
        assert set(archive.namelist()) == {
            f"{folder}/{folder}.tif",
            f"{folder}/SOURCE_PROVENANCE.json",
            f"{folder}/SOURCE_PROVENANCE.md",
            f"{folder}/DATA_LICENSE_NOTICE.md",
        }
        assert archive.read(f"{folder}/{folder}.tif") == b"aerial-raster"
        evidence = json.loads(archive.read(f"{folder}/SOURCE_PROVENANCE.json"))
        assert evidence["items"][0]["source_href"] == "https://example.test/naip.tif"
        assert evidence["output"]["filename"] == f"{folder}.tif"
        assert evidence["output"]["sha256"]
        notice = archive.read(f"{folder}/DATA_LICENSE_NOTICE.md").decode("utf-8")
        assert "Data license and attribution notice" in notice
        assert item["provider"] in notice
    _finish_response(response)
    assert not archive_path.exists()


def test_individual_raster_downloads_are_retired_to_preserve_notices(monkeypatch):
    item = {"id": "abc123def456", "files": {}}
    monkeypatch.setattr(main, "get_dataset", lambda requested_id: item)
    monkeypatch.setattr(main, "get_naip_imagery", lambda requested_id: item)

    for download in (
        lambda: main.download_dataset("abc123def456", "original"),
        lambda: main.download_dataset("abc123def456", "processed"),
        lambda: main.download_naip_imagery("abc123def456", "imagery"),
    ):
        try:
            download()
        except HTTPException as exc:
            assert exc.status_code == 410
            assert "package" in str(exc.detail).lower()
        else:
            raise AssertionError("Individual raster download must be retired")