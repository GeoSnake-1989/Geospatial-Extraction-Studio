from __future__ import annotations

from enum import Enum
from math import cos, radians
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class BoundingBox(BaseModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def validate_order(self) -> "BoundingBox":
        if self.west >= self.east or self.south >= self.north:
            raise ValueError("Bounding box edges must be ordered west/south/east/north")
        return self

    def area_km2(self) -> float:
        center_lat = (self.south + self.north) / 2
        width = (self.east - self.west) * 111.320 * cos(radians(center_lat))
        height = (self.north - self.south) * 110.574
        return abs(width * height)

    def as_arcgis_bbox(self) -> str:
        return f"{self.west},{self.south},{self.east},{self.north}"


class PreviewSize(int, Enum):
    compact = 64
    balanced = 96
    detailed = 128


class ElevationSource(str, Enum):
    usgs_seamless = "usgs_seamless"


class OSMOutputFormat(str, Enum):
    openfilegdb = "openfilegdb"
    geopackage = "geopackage"


class NAIPSelectionMode(str, Enum):
    latest_complete = "latest_complete"
    latest_per_tile = "latest_per_tile"
    year = "year"


class NAIPBands(str, Enum):
    rgb = "rgb"
    rgbnir = "rgbnir"

class ExtractionRequest(BaseModel):
    bounds: BoundingBox
    preview_size: PreviewSize = PreviewSize.balanced
    source: ElevationSource = ElevationSource.usgs_seamless
    label: str = Field(default="Selected area", min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_elevation_area(self) -> "ExtractionRequest":
        if self.bounds.area_km2() > 2_500:
            raise ValueError("Selected area is too large; choose an area smaller than 2,500 km²")
        return self


class OSMExtractionRequest(BaseModel):
    bounds: BoundingBox
    label: str = Field(default="Selected area", min_length=1, max_length=120)
    feature_type: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9_:.-]+$",
        description="OpenStreetMap tag key, such as building or amenity",
    )
    feature_subtype: str | None = Field(default=None, max_length=120)
    boundary: dict[str, Any] | None = None
    output_format: OSMOutputFormat = OSMOutputFormat.openfilegdb
    target_export_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )

    @field_validator("boundary")
    @classmethod
    def validate_boundary_geojson(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if value.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError("Boundary must be a GeoJSON Polygon or MultiPolygon")
        if not isinstance(value.get("coordinates"), list) or not value["coordinates"]:
            raise ValueError("Boundary coordinates are missing")
        return value

    @model_validator(mode="after")
    def validate_rectangle_area(self) -> "OSMExtractionRequest":
        if self.boundary is None and self.bounds.area_km2() > 2_500:
            raise ValueError(
                "Rectangle selections must be smaller than 2,500 km²; select a named place boundary for a larger administrative area"
            )
        return self


class NAIPExtractionRequest(BaseModel):
    bounds: BoundingBox
    label: str = Field(default="Selected area", min_length=1, max_length=120)
    selection_mode: NAIPSelectionMode = NAIPSelectionMode.latest_complete
    year: int | None = Field(default=None, ge=2003, le=2100)
    bands: NAIPBands = NAIPBands.rgb

    @model_validator(mode="after")
    def validate_naip_request(self) -> "NAIPExtractionRequest":
        if self.bounds.area_km2() > 500:
            raise ValueError("NAIP catalog selections must be smaller than 500 km?")
        if self.selection_mode == NAIPSelectionMode.year and self.year is None:
            raise ValueError("Choose an acquisition year for the selected NAIP date mode")
        if self.selection_mode != NAIPSelectionMode.year and self.year is not None:
            raise ValueError("An acquisition year can only be used with the year selection mode")
        return self


class JobState(str, Enum):
    queued = "queued"
    downloading = "downloading"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class JobResponse(BaseModel):
    id: str
    state: JobState
    progress: int = Field(ge=0, le=100)
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None


class PlaceResult(BaseModel):
    name: str
    latitude: float
    longitude: float
    bounds: BoundingBox
    kind: str | None = None
    boundary: dict[str, Any] | None = None
    boundary_area_km2: float | None = None
