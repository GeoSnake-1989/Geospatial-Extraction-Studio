from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.enums import Resampling


def _first_tag(tags: dict[str, str], names: tuple[str, ...]) -> str | None:
    lowered = {key.lower(): value for key, value in tags.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def build_preview(source_path: Path, processed_path: Path, max_size: int = 128) -> dict[str, Any]:
    with rasterio.open(source_path) as source:
        scale = min(1.0, max_size / max(source.width, source.height))
        width = max(2, int(round(source.width * scale)))
        height = max(2, int(round(source.height * scale)))
        values = source.read(
            1,
            out_shape=(height, width),
            masked=True,
            resampling=Resampling.bilinear,
        ).astype("float32")
        valid = values.compressed()
        if valid.size == 0:
            raise ValueError("The selected area contains no valid elevation cells")

        minimum = float(np.min(valid))
        maximum = float(np.max(valid))
        mean = float(np.mean(valid))
        valid_mask = ~np.ma.getmaskarray(values)
        filled = values.filled(mean).astype("float32")
        transform = source.transform * source.transform.scale(
            source.width / width, source.height / height
        )

        profile = source.profile.copy()
        profile.update(
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            transform=transform,
            compress="deflate",
            nodata=-9999.0,
        )
        with rasterio.open(processed_path, "w", **profile) as target:
            target.write(np.where(values.mask, -9999.0, filled), 1)
            target.update_tags(DERIVATIVE="Decimated interactive preview", SOURCE=str(source_path.name))

        tags = source.tags()
        bounds = source.bounds
        crs = source.crs.to_string() if source.crs else "Not declared"
        horizontal_units = "Not declared"
        if source.crs:
            try:
                horizontal_units = source.crs.linear_units or "degrees"
            except Exception:
                horizontal_units = "degrees" if source.crs.is_geographic else "Not declared"

    return {
        "grid": {
            "rows": height,
            "columns": width,
            "values": np.round(filled, 3).tolist(),
            "valid_mask": valid_mask.tolist(),
            "nodata_cells": int(np.count_nonzero(~valid_mask)),
        },
        "statistics": {
            "minimum": round(minimum, 3),
            "maximum": round(maximum, 3),
            "mean": round(mean, 3),
            "relief": round(maximum - minimum, 3),
        },
        "spatial": {
            "crs": crs,
            "horizontal_units": horizontal_units,
            "bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
            "source_width": source.width,
            "source_height": source.height,
            "preview_width": width,
            "preview_height": height,
            "nodata": source.nodata,
            "vertical_units": _first_tag(tags, ("vertical_units", "z_unit", "unit")) or "Not declared in GeoTIFF",
            "vertical_datum": _first_tag(tags, ("vertical_datum", "vdatum", "vertical_crs")) or "Not declared in GeoTIFF",
        },
    }
