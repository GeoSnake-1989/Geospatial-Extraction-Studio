from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_bounds

from app.raster import build_preview


def test_build_preview_handles_nodata(tmp_path: Path):
    source = tmp_path / "source.tif"
    processed = tmp_path / "preview.tif"
    values = np.arange(400, dtype="float32").reshape(20, 20)
    values[0, 0] = -9999
    profile = {
        "driver": "GTiff",
        "width": 20,
        "height": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_bounds(-82.6, 27.9, -82.5, 28.0, 20, 20),
        "nodata": -9999,
    }
    with rasterio.open(source, "w", **profile) as dataset:
        dataset.write(values, 1)

    result = build_preview(source, processed, max_size=10)

    assert processed.exists()
    assert result["grid"]["rows"] == 10
    assert result["grid"]["columns"] == 10
    assert result["spatial"]["source_width"] == 20
    assert result["spatial"]["source_height"] == 20
    assert result["spatial"]["preview_width"] == 10
    assert result["spatial"]["preview_height"] == 10
    assert result["statistics"]["maximum"] > result["statistics"]["minimum"]
    assert result["spatial"]["crs"] == "EPSG:4326"
    assert len(result["grid"]["valid_mask"]) == 10
    assert all(len(row) == 10 for row in result["grid"]["valid_mask"])


def test_build_preview_exposes_nodata_mask_without_losing_valid_statistics(tmp_path: Path):
    source = tmp_path / "source-with-gap.tif"
    processed = tmp_path / "preview-with-gap.tif"
    values = np.tile(np.arange(20, dtype="float32"), (20, 1))
    values[:, :10] = -9999
    profile = {
        "driver": "GTiff",
        "width": 20,
        "height": 20,
        "count": 1,
        "dtype": "float32",
        "crs": "EPSG:4326",
        "transform": from_bounds(-82.6, 27.9, -82.5, 28.0, 20, 20),
        "nodata": -9999,
    }
    with rasterio.open(source, "w", **profile) as dataset:
        dataset.write(values, 1)

    result = build_preview(source, processed, max_size=10)

    valid_mask = np.asarray(result["grid"]["valid_mask"], dtype=bool)
    assert result["grid"]["nodata_cells"] == int(np.count_nonzero(~valid_mask))
    assert result["grid"]["nodata_cells"] > 0
    assert np.all(~valid_mask[:, :4])
    assert result["statistics"]["minimum"] >= 9
    with rasterio.open(processed) as dataset:
        assert int(np.count_nonzero(dataset.read(1) == dataset.nodata)) == result["grid"]["nodata_cells"]
