from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app import main
from app.models import BoundingBox, ExtractionRequest, JobResponse, JobState
from app.providers.base import DownloadedAsset


def test_elevation_job_groups_dem_and_source_evidence(
    tmp_path: Path, monkeypatch,
):
    original_root = tmp_path / "original"
    processed_root = tmp_path / "processed"
    saved: list[dict] = []

    class FakeUuid:
        hex = "abc123def4567890"

    class FakeProvider:
        async def extract(self, bounds, output_path, width, height):
            output_path.write_bytes(b"D" * 2048)
            return DownloadedAsset(
                path=output_path,
                source_url="https://download.example.test/dem.tif",
                provider_name="USGS 3DEP",
                product_name="Test DEM",
                acquisition_note="Test acquisition",
                provider_metadata={
                    "service": "https://service.example.test/ImageServer",
                    "retrieval_method": "test",
                    "license": "public domain",
                },
            )

    def fake_preview(source_path, output_path, preview_size):
        output_path.write_bytes(b"preview")
        return {
            "spatial": {
                "crs": "EPSG:4326",
                "horizontal_units": "degrees",
                "vertical_units": "meters",
                "vertical_datum": "Not declared",
                "nodata": -9999,
                "source_width": 10,
                "source_height": 10,
            }
        }

    monkeypatch.setattr(main, "ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main.uuid, "uuid4", lambda: FakeUuid())
    monkeypatch.setattr(main, "USGS3DEPProvider", FakeProvider)
    monkeypatch.setattr(main, "build_preview", fake_preview)
    monkeypatch.setattr(main, "save_dataset", saved.append)
    main.jobs["terrain-job"] = JobResponse(
        id="terrain-job",
        state=JobState.queued,
        progress=2,
        message="queued",
    )

    request = ExtractionRequest(
        bounds=BoundingBox(west=-82.6, south=27.9, east=-82.59, north=27.91),
        label="Test area",
    )
    asyncio.run(main.run_extraction("terrain-job", request))

    result = main.jobs["terrain-job"].result
    assert main.jobs["terrain-job"].state == JobState.completed, (
        main.jobs["terrain-job"].error
    )
    assert result is not None
    acquisition_folder = original_root / "terrain" / "abc123def456"
    assert Path(result["files"]["original"]).parent == acquisition_folder
    assert Path(result["files"]["source_evidence"]).parent == acquisition_folder
    assert Path(result["files"]["documentation"]).parent == acquisition_folder
    evidence = json.loads(Path(result["files"]["source_evidence"]).read_text(encoding="utf-8"))
    assert evidence["data_type"] == "Digital Elevation Model (DEM)"
    assert evidence["output"]["sha256"]
    assert "original_download" not in result["files"]
    assert "processed_download" not in result["files"]
    assert saved == [result]


def test_naip_cleanup_removes_new_folder_and_legacy_files(tmp_path: Path, monkeypatch):
    imagery_id = "abc123def456"
    original_root = tmp_path / "original" / "naip"
    processed_root = tmp_path / "processed" / "naip"
    imagery_folder = processed_root / imagery_id
    imagery_folder.mkdir(parents=True)
    original_root.mkdir(parents=True)
    manifest = imagery_folder / f"{imagery_id}_naip_sources.json"
    imagery = imagery_folder / f"{imagery_id}_naip_mosaic.tif"
    preview = imagery_folder / f"{imagery_id}_naip_preview.png"
    documentation = imagery_folder / "SOURCE_PROVENANCE.md"
    for path in (manifest, imagery, preview, documentation):
        path.write_bytes(b"data")
    legacy_manifest = original_root / manifest.name
    legacy_manifest.write_bytes(b"legacy")
    item = {
        "id": imagery_id,
        "files": {
            "manifest": str(manifest),
            "imagery": str(imagery),
            "preview": str(preview),
            "documentation": str(documentation),
        },
    }
    monkeypatch.setattr(main, "NAIP_ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "NAIP_PROCESSED_DIR", processed_root)

    paths = main.naip_cleanup_paths(item)
    for path in paths:
        main.remove_path(path)

    assert not imagery_folder.exists()
    assert not legacy_manifest.exists()
