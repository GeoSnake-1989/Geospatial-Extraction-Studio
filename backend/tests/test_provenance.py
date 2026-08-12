from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.provenance import file_integrity, write_source_documentation


def test_source_documentation_records_raster_integrity(tmp_path: Path):
    raster = tmp_path / "dem.tif"
    raster.write_bytes(b"sample-raster")
    evidence_path = tmp_path / "source.json"
    documentation_path = tmp_path / "SOURCE_PROVENANCE.md"

    evidence = write_source_documentation(
        evidence_path,
        documentation_path,
        title="DEM source provenance - Test area",
        evidence={
            "provider": "USGS 3DEP",
            "product": "Test DEM",
            "source_urls": ["https://example.test/source"],
            "output": file_integrity(raster),
        },
    )

    assert evidence["output"]["sha256"] == hashlib.sha256(b"sample-raster").hexdigest()
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
    documentation = documentation_path.read_text(encoding="utf-8")
    assert "USGS 3DEP" in documentation
    assert "https://example.test/source" in documentation
    assert evidence["output"]["sha256"] in documentation
