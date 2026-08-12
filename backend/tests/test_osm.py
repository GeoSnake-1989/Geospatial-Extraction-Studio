from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

import geopandas as gpd
import pyogrio
import pytest
from shapely.geometry import LineString, Point
from shapely.geometry import shape

from app.models import BoundingBox
from app.osm import _download_features, build_osm_map_preview, extract_osm_features


@pytest.mark.skipif(
    "w" not in pyogrio.list_drivers().get("OpenFileGDB", ""),
    reason="OpenFileGDB write support is unavailable",
)
def test_osm_export_creates_geodatabase_attribution_and_zip(tmp_path: Path):
    features = gpd.GeoDataFrame(
        {
            "name": ["library", "path"],
            "objectid": [7, 8],
            "addr:street": ["Main Street", None],
        },
        geometry=[
            Point(-82.55, 27.96),
            LineString([(-82.56, 27.95), (-82.54, 27.97)]),
        ],
        crs="EPSG:4326",
    )
    bounds = BoundingBox(west=-82.6, south=27.9, east=-82.5, north=28.0)

    with patch("app.osm._download_features", return_value=features):
        result = extract_osm_features(
            bounds,
            "Tampa test",
            "amenity",
            None,
            tmp_path,
            "export123",
        )

    geodatabase = Path(result["files"]["geodatabase"])
    notice = Path(result["files"]["attribution"])
    archive = Path(result["files"]["archive"])
    assert geodatabase.is_dir()
    assert notice.is_file()
    assert archive.is_file()
    assert result["feature_count"] == 2
    assert set(result["feature_classes"]) == {
        "main_amenity_linestring",
        "main_amenity_point",
    }
    notice_text = notice.read_text(encoding="utf-8")
    assert "© OpenStreetMap contributors" in notice_text
    assert "This geodatabase is made available under" in notice_text
    with ZipFile(archive) as package:
        names = package.namelist()
        assert any(name.endswith("_OSM_ATTRIBUTION.txt") for name in names)
        assert any("Tampa_test.gdb/" in name for name in names)

    exported = pyogrio.read_dataframe(geodatabase, layer="main_amenity_point")
    assert pyogrio.read_info(geodatabase, layer="main_amenity_point")["fid_column"] == "OBJECTID"
    assert "osm_objectid" in exported.columns
    assert "addr_street" in exported.columns
    assert exported["osm_objectid"].iloc[0] == 7

    preview = build_osm_map_preview(geodatabase, result["feature_classes"])
    assert preview["type"] == "FeatureCollection"
    assert preview["crs"] == "EPSG:4326"
    assert preview["feature_count"] == 2
    assert preview["displayed_feature_count"] == 2
    assert preview["truncated"] is False
    assert {feature["properties"]["_layer"] for feature in preview["features"]} == {
        "main_amenity_linestring",
        "main_amenity_point",
    }

    limited_preview = build_osm_map_preview(geodatabase, result["feature_classes"], max_features=1)
    assert limited_preview["displayed_feature_count"] == 1
    assert limited_preview["truncated"] is True


def test_osm_export_reports_empty_query(tmp_path: Path):
    empty = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    bounds = BoundingBox(west=-82.6, south=27.9, east=-82.5, north=28.0)

    with patch("app.osm._download_features", return_value=empty):
        with pytest.raises(RuntimeError, match="No features were found"):
            extract_osm_features(
                bounds,
                "Empty test",
                "building",
                None,
                tmp_path,
                "empty123",
            )

    assert not (tmp_path / "empty123").exists()


def test_named_place_boundary_uses_polygon_query():
    features = gpd.GeoDataFrame(
        {"name": ["lift"]},
        geometry=[Point(-82.5, 27.9)],
        crs="EPSG:4326",
    )
    bounds = BoundingBox(west=-82.82, south=27.57, east=-82.05, north=28.17)
    boundary = shape({
        "type": "Polygon",
        "coordinates": [[
            [-82.82, 27.57],
            [-82.05, 27.57],
            [-82.05, 28.17],
            [-82.82, 28.17],
            [-82.82, 27.57],
        ]],
    })

    with patch("app.osm.ox.features_from_polygon", return_value=features) as polygon_query:
        result = _download_features(bounds, {"aerialway": True}, boundary)

    assert result is features
    polygon_query.assert_called_once_with(boundary, {"aerialway": True})


@pytest.mark.skipif(
    "w" not in pyogrio.list_drivers().get("OpenFileGDB", ""),
    reason="OpenFileGDB write support is unavailable",
)
def test_osm_export_adds_layers_atomically_to_existing_geodatabase(tmp_path: Path):
    bounds = BoundingBox(west=-82.6, south=27.9, east=-82.5, north=28.0)
    amenities = gpd.GeoDataFrame(
        {"name": ["library"]},
        geometry=[Point(-82.55, 27.96)],
        crs="EPSG:4326",
    )
    roads = gpd.GeoDataFrame(
        {"name": ["Main Street"]},
        geometry=[LineString([(-82.56, 27.95), (-82.54, 27.97)])],
        crs="EPSG:4326",
    )

    with patch("app.osm._download_features", return_value=amenities):
        first = extract_osm_features(
            bounds,
            "Hillsborough project",
            "amenity",
            None,
            tmp_path,
            "shared123",
        )
    with patch("app.osm._download_features", return_value=roads):
        expanded = extract_osm_features(
            bounds,
            "Ignored replacement label",
            "highway",
            "residential",
            tmp_path,
            "shared123",
            existing_export=first,
        )

    geodatabase = Path(expanded["files"]["geodatabase"])
    layers = {str(layer[0]) for layer in pyogrio.list_layers(geodatabase)}
    assert layers == {"main_amenity_point", "main_highway_residential_linestring"}
    assert expanded["label"] == "Hillsborough project"
    assert expanded["feature_count"] == 2
    assert expanded["last_extraction_count"] == 1
    assert len(expanded["extractions"]) == 2
    notice = Path(expanded["files"]["attribution"]).read_text(encoding="utf-8")
    assert "OSM tag selection: amenity" in notice
    assert "OSM tag selection: highway=residential" in notice

    archive = Path(expanded["files"]["archive"])
    archive_before_collision = archive.read_bytes()
    with patch("app.osm._download_features", return_value=roads):
        with pytest.raises(RuntimeError, match="already contains"):
            extract_osm_features(
                bounds,
                "Hillsborough project",
                "highway",
                "residential",
                tmp_path,
                "shared123",
                existing_export=expanded,
            )

    assert archive.read_bytes() == archive_before_collision
    assert {str(layer[0]) for layer in pyogrio.list_layers(geodatabase)} == layers


@pytest.mark.skipif(
    "w" not in pyogrio.list_drivers().get("GPKG", ""),
    reason="GeoPackage write support is unavailable",
)
def test_osm_export_creates_and_extends_geopackage(tmp_path: Path):
    bounds = BoundingBox(west=-82.6, south=27.9, east=-82.5, north=28.0)
    amenities = gpd.GeoDataFrame(
        {
            "name": ["library"],
            "objectid": [7],
            "addr:street": ["Main Street"],
        },
        geometry=[Point(-82.55, 27.96)],
        crs="EPSG:4326",
    )
    roads = gpd.GeoDataFrame(
        {"name": ["Main Street"]},
        geometry=[LineString([(-82.56, 27.95), (-82.54, 27.97)])],
        crs="EPSG:4326",
    )

    with patch("app.osm._download_features", return_value=amenities):
        first = extract_osm_features(
            bounds,
            "Tampa GeoPackage",
            "amenity",
            None,
            tmp_path,
            "gpkg123",
            output_format="geopackage",
        )

    dataset = Path(first["files"]["geodatabase"])
    assert first["output_format"] == "geopackage"
    assert dataset.suffix == ".gpkg"
    assert dataset.is_file()
    assert {str(layer[0]) for layer in pyogrio.list_layers(dataset)} == {"amenity_point"}
    assert pyogrio.read_info(dataset, layer="amenity_point")["fid_column"] == "OBJECTID"
    with ZipFile(Path(first["files"]["archive"])) as package:
        assert any(name.endswith("Tampa_GeoPackage.gpkg") for name in package.namelist())
        assert any(name.endswith("_OSM_ATTRIBUTION.txt") for name in package.namelist())

    with patch("app.osm._download_features", return_value=roads):
        expanded = extract_osm_features(
            bounds,
            "Ignored replacement label",
            "highway",
            "residential",
            tmp_path,
            "gpkg123",
            existing_export=first,
            output_format="geopackage",
        )

    assert expanded["output_format"] == "geopackage"
    assert expanded["feature_count"] == 2
    assert {str(layer[0]) for layer in pyogrio.list_layers(dataset)} == {
        "amenity_point",
        "highway_residential_linestring",
    }
    exported = pyogrio.read_dataframe(dataset, layer="amenity_point")
    assert "osm_objectid" in exported.columns
    assert "addr_street" in exported.columns
    assert "addr:street" not in exported.columns
    preview = build_osm_map_preview(dataset, expanded["feature_classes"])
    assert preview["feature_count"] == 2

    with pytest.raises(RuntimeError, match="existing output format"):
        extract_osm_features(
            bounds,
            "Tampa GeoPackage",
            "building",
            None,
            tmp_path,
            "gpkg123",
            existing_export=expanded,
            output_format="openfilegdb",
        )
