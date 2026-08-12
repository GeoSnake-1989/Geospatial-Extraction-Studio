import pytest
from pydantic import ValidationError

from app.models import BoundingBox, ElevationSource, ExtractionRequest, OSMExtractionRequest, OSMOutputFormat
from app.models import NAIPExtractionRequest, NAIPSelectionMode


def test_valid_bounds_report_area():
    bounds = BoundingBox(west=-82.6, south=27.9, east=-82.5, north=28.0)
    assert 90 < bounds.area_km2() < 120


def test_reversed_bounds_are_rejected():
    with pytest.raises(ValidationError):
        BoundingBox(west=-82.5, south=28.0, east=-82.6, north=27.9)


def test_oversized_bounds_are_rejected():
    with pytest.raises(ValidationError, match="2,500"):
        ExtractionRequest(
            bounds={"west": -90, "south": 25, "east": -80, "north": 35},
            label="Too large",
        )


def test_only_usgs_seamless_elevation_source_is_allowed():
    request = ExtractionRequest(
        bounds={"west": -82.6, "south": 27.9, "east": -82.5, "north": 28.0},
    )

    assert request.source == ElevationSource.usgs_seamless
    with pytest.raises(ValidationError):
        ExtractionRequest(
            bounds={"west": -82.6, "south": 27.9, "east": -82.5, "north": 28.0},
            source="usgs_1m",
        )

def test_osm_feature_type_rejects_invalid_tag_key():
    with pytest.raises(ValidationError):
        OSMExtractionRequest(
            bounds={"west": -82.6, "south": 27.9, "east": -82.5, "north": 28.0},
            label="Test",
            feature_type="building key",
        )


def test_osm_named_boundary_can_use_a_larger_administrative_bbox():
    request = OSMExtractionRequest(
        bounds={"west": -82.82, "south": 27.57, "east": -82.05, "north": 28.17},
        boundary={
            "type": "Polygon",
            "coordinates": [[
                [-82.82, 27.57],
                [-82.05, 27.57],
                [-82.05, 28.17],
                [-82.82, 28.17],
                [-82.82, 27.57],
            ]],
        },
        label="Hillsborough County, Florida",
        feature_type="aerialway",
    )

    assert request.boundary is not None


def test_osm_large_rectangle_still_requires_a_named_boundary():
    with pytest.raises(ValidationError, match="named place boundary"):
        OSMExtractionRequest(
            bounds={"west": -82.82, "south": 27.57, "east": -82.05, "north": 28.17},
            label="Large rectangle",
            feature_type="building",
        )


def test_osm_output_format_defaults_to_openfilegdb_and_accepts_geopackage():
    bounds = {"west": -82.6, "south": 27.9, "east": -82.5, "north": 28.0}
    default_request = OSMExtractionRequest(
        bounds=bounds,
        label="Default format",
        feature_type="building",
    )
    geopackage_request = OSMExtractionRequest(
        bounds=bounds,
        label="GeoPackage format",
        feature_type="building",
        output_format="geopackage",
    )

    assert default_request.output_format == OSMOutputFormat.openfilegdb
    assert geopackage_request.output_format == OSMOutputFormat.geopackage
    with pytest.raises(ValidationError):
        OSMExtractionRequest(bounds=bounds, label="Invalid", feature_type="building", output_format="shapefile")


def test_naip_defaults_to_latest_complete_rgb():
    request = NAIPExtractionRequest(
        bounds={"west": -82.51, "south": 27.99, "east": -82.50, "north": 28.0},
        label="Latest Tampa imagery",
    )

    assert request.selection_mode == NAIPSelectionMode.latest_complete
    assert request.bands.value == "rgb"
    assert request.year is None


def test_naip_specific_year_requires_year_mode_and_value():
    bounds = {"west": -82.51, "south": 27.99, "east": -82.50, "north": 28.0}
    request = NAIPExtractionRequest(bounds=bounds, selection_mode="year", year=2023)

    assert request.year == 2023
    with pytest.raises(ValidationError, match="Choose an acquisition year"):
        NAIPExtractionRequest(bounds=bounds, selection_mode="year")
    with pytest.raises(ValidationError, match="only be used"):
        NAIPExtractionRequest(bounds=bounds, selection_mode="latest_complete", year=2023)


def test_naip_catalog_area_is_bounded():
    with pytest.raises(ValidationError, match="500"):
        NAIPExtractionRequest(
            bounds={"west": -83.0, "south": 27.0, "east": -82.0, "north": 28.0},
        )
