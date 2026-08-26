from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.data_notices import data_license_notice_markdown
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


def test_data_license_notice_preserves_provider_terms_and_links():
    notice = data_license_notice_markdown(
        {
            "provider": "USDA NAIP",
            "product": "Test mosaic",
            "attribution": "NAIP imagery provided by USDA Farm Service Agency",
            "source_license_summary": "Public Domain",
            "collection": {
                "license": "proprietary",
                "license_links": [{"title": "Public Domain", "href": "https://example.test/license"}],
            },
            "source_urls": ["https://example.test/source"],
        }
    )

    assert "USDA NAIP" in notice
    assert "NAIP imagery provided by USDA Farm Service Agency" in notice
    assert "Public Domain" in notice
    assert "https://example.test/license" in notice
    assert "https://example.test/source" in notice