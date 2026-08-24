import asyncio

import httpx

from app import main


def test_world_place_search_accepts_international_places_and_preserves_administrative_boundary(monkeypatch):
    captured_url = None
    original_async_client = httpx.AsyncClient
    boundary = {
        "type": "Polygon",
        "coordinates": [[
            [-0.1138, 51.5069],
            [-0.0729, 51.5069],
            [-0.0729, 51.5236],
            [-0.1138, 51.5236],
            [-0.1138, 51.5069],
        ]],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = request.url
        return httpx.Response(
            200,
            json=[{
                "display_name": "City of London, Greater London, England, United Kingdom",
                "lat": "51.5156",
                "lon": "-0.0910",
                "boundingbox": ["51.5069", "51.5236", "-0.1138", "-0.0729"],
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

    results = asyncio.run(main.search_places("City of London", "world"))

    assert captured_url is not None
    assert "countrycodes" not in captured_url.params
    assert captured_url.params["polygon_geojson"] == "1"
    assert captured_url.params["polygon_threshold"] == "0.0001"
    assert results[0].bounds.west == -0.1138
    assert results[0].bounds.east == -0.0729
    assert results[0].boundary == boundary
    assert results[0].boundary_area_km2 is not None
    assert results[0].boundary_area_km2 > 5
