import asyncio

import httpx

from app import main


def test_world_place_search_preserves_administrative_boundary(monkeypatch):
    captured_url = None
    original_async_client = httpx.AsyncClient
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [-82.82, 27.57],
            [-82.05, 27.57],
            [-82.05, 28.17],
            [-82.82, 28.17],
            [-82.82, 27.57],
        ]],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = request.url
        return httpx.Response(
            200,
            json=[{
                "display_name": "Hillsborough County, Florida, United States",
                "lat": "27.99",
                "lon": "-82.31",
                "boundingbox": ["27.57", "28.17", "-82.82", "-82.05"],
                "type": "administrative",
                "geojson": boundary,
            }],
            request=request,
        )

    def client_factory(*args, **kwargs):
        return original_async_client(
            *args,
            transport=httpx.MockTransport(handler),
            **kwargs,
        )

    async def no_wait():
        return None

    monkeypatch.setattr(main.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(main.place_request_limiter, "wait", no_wait)
    main.place_cache.clear()

    results = asyncio.run(main.search_places("Hillsborough County", "world"))

    assert captured_url is not None
    assert captured_url.params["polygon_geojson"] == "1"
    assert captured_url.params["polygon_threshold"] == "0.0001"
    assert results[0].bounds.west == -82.82
    assert results[0].bounds.east == -82.05
    assert results[0].boundary == boundary
    assert results[0].boundary_area_km2 is not None
    assert results[0].boundary_area_km2 > 4_000
