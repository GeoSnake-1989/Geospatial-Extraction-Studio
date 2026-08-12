from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app import main
from app.models import BoundingBox, JobResponse, JobState, NAIPExtractionRequest


def test_naip_job_groups_imagery_and_source_evidence(tmp_path: Path, monkeypatch):
    original_root = tmp_path / "original" / "naip"
    processed_root = tmp_path / "processed" / "naip"
    saved: list[dict] = []

    class FakeUuid:
        hex = "abc123def4567890"

    class FakeProvider:
        async def extract(
            self,
            bounds,
            selection_mode,
            year,
            bands,
            manifest_path,
            output_path,
            preview_path,
        ):
            manifest_path.write_text(
                json.dumps(
                    {
                        "provider": "USDA NAIP",
                        "catalog": "Test STAC catalog",
                        "selection_mode": selection_mode.value,
                        "requested_year": year,
                        "bounds_wgs84": bounds.model_dump(),
                        "items": [
                            {
                                "id": "tile-1",
                                "year": 2023,
                                "acquisition_datetime": "2023-06-01T12:00:00Z",
                                "gsd_m": 0.6,
                                "epsg": 26917,
                                "source_href": "https://example.test/tile-1.tif",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output_path.write_bytes(b"I" * 2048)
            preview_path.write_bytes(b"PNG")
            return {
                "provider": "USDA NAIP",
                "product": "Test aerial imagery",
                "years": [2023],
                "acquisition_start": "2023-06-01T12:00:00Z",
                "acquisition_end": "2023-06-01T12:00:00Z",
                "tile_count": 1,
                "coverage_percent": 100.0,
                "spatial": {
                    "crs": "EPSG:26917",
                    "width": 10,
                    "height": 10,
                    "pixel_count": 100,
                    "band_count": 3,
                    "resolution_m": 0.6,
                    "nodata": 0,
                },
                "preview": {"width": 10, "height": 10},
            }

    monkeypatch.setattr(main, "NAIP_ORIGINAL_DIR", original_root)
    monkeypatch.setattr(main, "NAIP_PROCESSED_DIR", processed_root)
    monkeypatch.setattr(main.uuid, "uuid4", lambda: FakeUuid())
    monkeypatch.setattr(main, "NAIPProvider", FakeProvider)
    monkeypatch.setattr(main, "save_naip_imagery", saved.append)
    monkeypatch.setattr(main, "naip_job_lock", asyncio.Lock())
    main.jobs["naip-job"] = JobResponse(
        id="naip-job",
        state=JobState.queued,
        progress=2,
        message="queued",
    )

    request = NAIPExtractionRequest(
        bounds=BoundingBox(west=-82.6, south=27.9, east=-82.59, north=27.91),
        label="Test imagery",
    )
    asyncio.run(main.run_naip_extraction("naip-job", request))

    result = main.jobs["naip-job"].result
    assert main.jobs["naip-job"].state == JobState.completed, main.jobs["naip-job"].error
    assert result is not None
    acquisition_folder = processed_root / "abc123def456"
    assert Path(result["files"]["manifest"]).parent == acquisition_folder
    assert Path(result["files"]["imagery"]).parent == acquisition_folder
    assert Path(result["files"]["preview"]).parent == acquisition_folder
    assert Path(result["files"]["documentation"]).parent == acquisition_folder
    evidence = json.loads(Path(result["files"]["manifest"]).read_text(encoding="utf-8"))
    assert evidence["items"][0]["source_href"] == "https://example.test/tile-1.tif"
    assert evidence["source_urls"] == ["https://example.test/tile-1.tif"]
    assert evidence["output"]["sha256"]
    assert saved == [result]
