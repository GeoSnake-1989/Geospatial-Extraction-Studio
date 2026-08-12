from __future__ import annotations

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from app.models import BoundingBox, NAIPSelectionMode
from app.providers.naip import NAIPItem, NAIPProvider, NAIPProviderError


def make_item(
    item_id: str,
    year: int,
    bounds: tuple[float, float, float, float],
    acquisition_date: str,
    gsd: float = 1.0,
) -> NAIPItem:
    return NAIPItem(
        id=item_id,
        year=year,
        acquisition_datetime=f"{acquisition_date}T16:00:00Z",
        gsd_m=gsd,
        epsg=26917,
        href=f"https://example.test/{item_id}.tif",
        bbox=bounds,
        geometry=None,
    )


def test_latest_complete_uses_newest_single_year_with_full_coverage():
    bounds = BoundingBox(west=0, south=0, east=2, north=1)
    items = [
        make_item("new-left", 2023, (0, 0, 1, 1), "2023-06-01", 0.3),
        make_item("old-left", 2021, (0, 0, 1, 1), "2021-05-01", 0.6),
        make_item("old-right", 2021, (1, 0, 2, 1), "2021-05-02", 0.6),
    ]

    selected = NAIPProvider().select_items(
        bounds,
        items,
        NAIPSelectionMode.latest_complete,
        None,
    )

    assert {item.id for item in selected} == {"old-left", "old-right"}


def test_stac_item_preserves_license_provider_and_asset_provenance():
    feature = {
        "id": "tile-2023",
        "bbox": [0, 0, 1, 1],
        "geometry": None,
        "license": "PDDL-1.0",
        "providers": [{"name": "USDA Farm Service Agency", "roles": ["producer"]}],
        "links": [
            {"rel": "self", "href": "https://example.test/items/tile-2023"},
            {
                "rel": "license",
                "href": "https://example.test/licenses/pddl",
                "title": "PDDL terms",
            },
        ],
        "properties": {
            "datetime": "2023-06-01T16:00:00Z",
            "naip:year": 2023,
            "gsd": 1.0,
            "proj:epsg": 26917,
        },
        "assets": {
            "image": {
                "href": "https://example.test/tile-2023.tif",
                "title": "NAIP RGB image",
                "type": "image/tiff; application=geotiff",
                "roles": ["data"],
            }
        },
    }

    item = NAIPItem.from_feature(feature)

    assert item.stac_license == "PDDL-1.0"
    assert item.stac_providers == ({"name": "USDA Farm Service Agency", "roles": ["producer"]},)
    assert item.asset_metadata == {
        "title": "NAIP RGB image",
        "type": "image/tiff; application=geotiff",
        "roles": ["data"],
    }
    assert item.stac_item_url == "https://example.test/items/tile-2023"
    assert item.stac_license_links == (
        {
            "href": "https://example.test/licenses/pddl",
            "title": "PDDL terms",
        },
    )


def test_collection_metadata_preserves_declaration_links_and_providers():
    metadata = NAIPProvider.collection_metadata_from_payload(
        {
            "id": "naip",
            "title": "NAIP imagery",
            "license": "proprietary",
            "providers": [{"name": "USDA Farm Service Agency", "roles": ["producer"]}],
            "links": [
                {"rel": "self", "href": "https://example.test/collections/naip"},
                {
                    "rel": "license",
                    "href": "https://example.test/public-domain-policy",
                    "title": "Public Domain",
                },
            ],
        }
    )

    assert metadata == {
        "id": "naip",
        "title": "NAIP imagery",
        "license": "proprietary",
        "license_links": [
            {
                "href": "https://example.test/public-domain-policy",
                "title": "Public Domain",
            }
        ],
        "providers": [{"name": "USDA Farm Service Agency", "roles": ["producer"]}],
        "source_url": "https://example.test/collections/naip",
    }


def test_license_summary_explains_legacy_non_spdx_collection_value():
    provider = NAIPProvider()
    provider.collection_metadata = {
        "license": "proprietary",
        "license_links": [
            {
                "href": "https://example.test/public-domain-policy",
                "title": "Public Domain",
            }
        ],
    }

    summary = provider.source_license_summary(
        [make_item("tile-2023", 2023, (0, 0, 1, 1), "2023-06-01")]
    )

    assert summary == (
        "Linked license terms: Public Domain: https://example.test/public-domain-policy "
        "(catalog uses legacy STAC 'proprietary' for non-SPDX terms)"
    )


def test_legacy_non_spdx_collection_value_requires_linked_terms():
    with pytest.raises(ValueError, match="requires a linked license text"):
        NAIPProvider.validate_collection_license_metadata(
            {"license": "proprietary", "license_links": []}
        )


def test_matching_asset_license_takes_precedence_over_collection_license():
    item = NAIPItem(
        id="tile-2023",
        year=2023,
        acquisition_datetime="2023-06-01T16:00:00Z",
        gsd_m=1.0,
        epsg=26917,
        href="https://example.test/tile-2023.tif",
        bbox=(0, 0, 1, 1),
        geometry=None,
        stac_license="PDDL-1.0",
        asset_metadata={"license": "PDDL-1.0"},
    )
    provider = NAIPProvider()
    provider.collection_metadata = {"license": "proprietary"}

    assert provider.source_license_summary([item]) == "Source asset/item declarations: PDDL-1.0"


def test_selected_item_legacy_license_requires_item_level_link():
    provider = NAIPProvider()
    provider.collection_metadata = {
        "license": "proprietary",
        "license_links": [{"href": "https://example.test/collection-terms"}],
    }
    item = make_item("tile-2023", 2023, (0, 0, 1, 1), "2023-06-01")
    item = NAIPItem(**{**item.__dict__, "stac_license": "proprietary"})

    with pytest.raises(NAIPProviderError, match="same-record linked license text"):
        provider.validate_selected_item_licenses([item])


def test_selected_item_legacy_license_accepts_item_level_link():
    provider = NAIPProvider()
    provider.collection_metadata = {
        "license": "proprietary",
        "license_links": [{"href": "https://example.test/collection-terms"}],
    }
    item = make_item("tile-2023", 2023, (0, 0, 1, 1), "2023-06-01")
    item = NAIPItem(
        **{
            **item.__dict__,
            "stac_license": "proprietary",
            "stac_license_links": (
                {"href": "https://example.test/item-terms", "title": "Item terms"},
            ),
        }
    )

    provider.validate_selected_item_licenses([item])
    assert provider.source_license_summary([item]) == (
        "Source asset/item declarations: proprietary "
        "(linked terms: Item terms: https://example.test/item-terms)"
    )


def test_conflicting_asset_and_item_licenses_block_selected_item():
    provider = NAIPProvider()
    provider.collection_metadata = {
        "license": "proprietary",
        "license_links": [{"href": "https://example.test/collection-terms"}],
    }
    item = make_item("tile-2023", 2023, (0, 0, 1, 1), "2023-06-01")
    item = NAIPItem(
        **{
            **item.__dict__,
            "stac_license": "PDDL-1.0",
            "asset_metadata": {"license": "CC-BY-4.0"},
        }
    )

    with pytest.raises(NAIPProviderError, match="conflicting asset and item"):
        provider.validate_selected_item_licenses([item])


def test_latest_per_tile_fills_each_part_from_newest_available_item():
    bounds = BoundingBox(west=0, south=0, east=2, north=1)
    items = [
        make_item("new-left", 2023, (0, 0, 1, 1), "2023-06-01", 0.3),
        make_item("old-left", 2021, (0, 0, 1, 1), "2021-05-01", 0.6),
        make_item("old-right", 2021, (1, 0, 2, 1), "2021-05-02", 0.6),
    ]

    selected = NAIPProvider().select_items(
        bounds,
        items,
        NAIPSelectionMode.latest_per_tile,
        None,
    )

    assert [item.id for item in selected] == ["new-left", "old-right"]
    assert NAIPProvider.coverage(bounds, selected) == 1.0


def test_availability_summary_reports_complete_years_and_pixel_guardrail():
    bounds = BoundingBox(west=-82.51, south=27.99, east=-82.50, north=28.0)
    items = [
        make_item("tile-2023", 2023, (-82.52, 27.98, -82.49, 28.01), "2023-01-11", 0.3),
        make_item("tile-2021", 2021, (-82.52, 27.98, -82.49, 28.01), "2021-02-10", 0.6),
    ]
    provider = NAIPProvider(max_output_pixels=123_456)
    provider.collection_metadata = {
        "license": "proprietary",
        "license_links": [{"href": "https://example.test/public-domain-policy"}],
    }

    summary = provider.summarize(bounds, items)

    assert summary["latest_complete_year"] == 2023
    assert summary["years"][0]["coverage_percent"] == 100.0
    assert summary["years"][0]["gsd_m"] == 0.3
    assert summary["max_output_pixels"] == 123_456


def test_specific_year_rejects_partial_coverage():
    bounds = BoundingBox(west=0, south=0, east=2, north=1)
    items = [make_item("partial", 2023, (0, 0, 1, 1), "2023-06-01", 0.3)]

    with pytest.raises(NAIPProviderError, match="does not completely cover"):
        NAIPProvider().select_items(bounds, items, NAIPSelectionMode.year, 2023)


def test_rgb_preview_is_bounded_and_preserves_nodata_as_black(tmp_path):
    imagery_path = tmp_path / "imagery.tif"
    preview_path = tmp_path / "preview.png"
    data = np.zeros((4, 600, 1200), dtype=np.uint8)
    data[0, :, 50:] = 180
    data[1, :, 50:] = 120
    data[2, :, 50:] = 60
    data[3, :, 50:] = 220
    with rasterio.open(
        imagery_path,
        "w",
        driver="GTiff",
        width=1200,
        height=600,
        count=4,
        dtype="uint8",
        crs="EPSG:26917",
        transform=from_origin(350000, 3100000, 0.3, 0.3),
        nodata=0,
    ) as dataset:
        dataset.write(data)

    result = NAIPProvider()._write_preview(imagery_path, preview_path)

    assert result == {"width": 1024, "height": 512}
    assert preview_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
