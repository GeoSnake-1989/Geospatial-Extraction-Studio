import asyncio
from pathlib import Path

import httpx

from app.models import BoundingBox
from app.providers.usgs import (
    MAX_EXPORT_DIMENSION,
    MAX_EXPORT_PIXELS,
    USGS3DEPProvider,
    source_grid_dimensions,
)


def test_source_grid_uses_approximately_ten_meter_cells():
    bounds = BoundingBox(west=-82.61, south=27.91, east=-82.49, north=28.01)

    width, height = source_grid_dimensions(bounds)

    assert 1_175 <= width <= 1_185
    assert 1_100 <= height <= 1_110
    assert width > 128
    assert height > 128


def test_source_grid_stays_within_export_limits():
    bounds = BoundingBox(west=-108.9, south=38.8, east=-108.2, north=39.45)

    width, height = source_grid_dimensions(bounds)

    assert max(width, height) <= MAX_EXPORT_DIMENSION
    assert width * height <= MAX_EXPORT_PIXELS


def test_provider_retries_gateway_error_then_downloads(tmp_path: Path, monkeypatch):
    calls = {"export": 0}

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("app.providers.usgs.asyncio.sleep", no_wait)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "download.example.test":
            return httpx.Response(200, content=b"I" * 2048, request=request)
        calls["export"] += 1
        if calls["export"] < 3:
            return httpx.Response(502, text="Bad Gateway", request=request)
        return httpx.Response(
            200,
            json={"href": "https://download.example.test/terrain.tif"},
            request=request,
        )

    async def run():
        provider = USGS3DEPProvider(transport=httpx.MockTransport(handler))
        output = tmp_path / "terrain.tif"
        asset = await provider.extract(
            BoundingBox(west=-108.75, south=38.98, east=-108.62, north=39.12),
            output,
            96,
            96,
        )
        return output, asset

    output, asset = asyncio.run(run())

    assert calls["export"] == 3
    assert output.stat().st_size == 2048
    assert asset.provider_metadata["retrieval_method"] == "ArcGIS JSON export URL"


def test_provider_uses_direct_image_fallback(tmp_path: Path, monkeypatch):
    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr("app.providers.usgs.asyncio.sleep", no_wait)

    def handler(request: httpx.Request) -> httpx.Response:
        is_direct = request.url.params.get("f") == "image"
        if is_direct:
            return httpx.Response(200, content=b"T" * 2048, request=request)
        return httpx.Response(502, text="Bad Gateway", request=request)

    async def run():
        provider = USGS3DEPProvider(transport=httpx.MockTransport(handler))
        output = tmp_path / "terrain.tif"
        asset = await provider.extract(
            BoundingBox(west=-108.75, south=38.98, east=-108.62, north=39.12),
            output,
            64,
            64,
        )
        return output, asset

    output, asset = asyncio.run(run())

    assert output.stat().st_size == 2048
    assert asset.provider_metadata["retrieval_method"] == "Direct ArcGIS image response fallback"
