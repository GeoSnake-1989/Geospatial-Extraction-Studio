from __future__ import annotations

import asyncio
from math import ceil, cos, radians, sqrt
from pathlib import Path
from typing import Final

import httpx

from ..models import BoundingBox
from .base import DownloadedAsset


class ProviderError(RuntimeError):
    pass


TARGET_GROUND_SPACING_METERS: Final = 10.0
MAX_EXPORT_DIMENSION: Final = 8_000
MAX_EXPORT_PIXELS: Final = 25_000_000


def source_grid_dimensions(bounds: BoundingBox) -> tuple[int, int]:
    """Build an approximately square 10 m source grid within service limits."""
    center_latitude = (bounds.south + bounds.north) / 2
    width_meters = abs(bounds.east - bounds.west) * 111_320 * cos(radians(center_latitude))
    height_meters = abs(bounds.north - bounds.south) * 110_574
    width = max(2, ceil(width_meters / TARGET_GROUND_SPACING_METERS))
    height = max(2, ceil(height_meters / TARGET_GROUND_SPACING_METERS))

    scale = min(
        1.0,
        MAX_EXPORT_DIMENSION / max(width, height),
        sqrt(MAX_EXPORT_PIXELS / (width * height)),
    )
    if scale < 1.0:
        width = max(2, int(width * scale))
        height = max(2, int(height * scale))
    return width, height


class USGS3DEPProvider:
    """Extracts bounded float32 GeoTIFFs from the public USGS 3DEP ImageServer."""

    retryable_statuses: Final = {408, 429, 500, 502, 503, 504}
    retry_delays: Final = (0.0, 1.5, 3.0, 6.0)

    service_url = (
        "https://elevation.nationalmap.gov/arcgis/rest/services/"
        "3DEPElevation/ImageServer"
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        stream: bool = False,
        attempts: int | None = None,
    ) -> httpx.Response:
        delays = self.retry_delays[:attempts]
        last_error: Exception | None = None
        for attempt, delay in enumerate(delays):
            if delay:
                await asyncio.sleep(delay)
            try:
                request = client.build_request(
                    "POST" if data is not None else "GET",
                    url,
                    params=params,
                    data=data,
                )
                response = await client.send(request, stream=stream)
                if response.status_code not in self.retryable_statuses:
                    response.raise_for_status()
                    return response
                last_error = httpx.HTTPStatusError(
                    f"USGS returned HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                await response.aclose()
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                last_error = exc
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                if status is not None and status not in self.retryable_statuses:
                    raise
            if attempt == len(delays) - 1:
                break

        status = (
            last_error.response.status_code
            if isinstance(last_error, httpx.HTTPStatusError)
            else None
        )
        suffix = f" (HTTP {status})" if status else ""
        raise ProviderError(
            "The USGS elevation service is temporarily unavailable after automatic retries"
            f"{suffix}. Please try the extraction again in a few minutes."
        ) from last_error

    async def _download_response(self, response: httpx.Response, output_path: Path) -> None:
        partial_path = output_path.with_suffix(f"{output_path.suffix}.part")
        partial_path.unlink(missing_ok=True)
        try:
            with partial_path.open("wb") as file_handle:
                async for chunk in response.aiter_bytes():
                    file_handle.write(chunk)
            if partial_path.stat().st_size < 1_024:
                raise ProviderError("The downloaded elevation file was unexpectedly small")
            partial_path.replace(output_path)
        finally:
            partial_path.unlink(missing_ok=True)
            await response.aclose()

    async def extract(
        self, bounds: BoundingBox, output_path: Path, width: int, height: int
    ) -> DownloadedAsset:
        params = {
            "bbox": bounds.as_arcgis_bbox(),
            "bboxSR": "4326",
            "imageSR": "4326",
            "size": f"{width},{height}",
            "format": "tiff",
            "pixelType": "F32",
            "noData": "-9999",
            "interpolation": "RSP_BilinearInterpolation",
            "returnSquarePixels": "false",
            "f": "json",
        }
        timeout = httpx.Timeout(150.0, connect=20.0)
        headers = {
            "User-Agent": "GeospatialExtractionStudio/0.3 (local terrain and OSM extractor)"
        }

        export_url = f"{self.service_url}/exportImage"
        href = ""
        retrieval_method = "ArcGIS JSON export URL"
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
            transport=self.transport,
        ) as client:
            try:
                # Alternate GET and POST. Both are supported by ArcGIS REST, and the
                # POST path avoids long gateway query strings when the upstream is busy.
                response: httpx.Response | None = None
                last_error: Exception | None = None
                for attempt, delay in enumerate(self.retry_delays):
                    if delay:
                        await asyncio.sleep(delay)
                    try:
                        if attempt % 2:
                            response = await self._request_with_retry(
                                client, export_url, data=params, attempts=1
                            )
                        else:
                            response = await self._request_with_retry(
                                client, export_url, params=params, attempts=1
                            )
                        break
                    except ProviderError as exc:
                        last_error = exc
                if response is None:
                    raise last_error or ProviderError("USGS extraction failed")

                payload = response.json()
                await response.aclose()
                if "error" in payload:
                    detail = payload["error"].get("message", "USGS extraction failed")
                    raise ProviderError(detail)
                href = payload.get("href", "")
                if not href:
                    raise ProviderError("USGS did not return a GeoTIFF download URL")
                download = await self._request_with_retry(client, href, stream=True)
                await self._download_response(download, output_path)
            except (ProviderError, ValueError, httpx.DecodingError) as json_error:
                # ArcGIS can return a gateway error while preparing the JSON wrapper.
                # Requesting the image body directly is a supported secondary path.
                direct_params = {**params, "f": "image"}
                try:
                    download = await self._request_with_retry(
                        client,
                        export_url,
                        params=direct_params,
                        stream=True,
                        attempts=3,
                    )
                    await self._download_response(download, output_path)
                    href = str(download.request.url)
                    retrieval_method = "Direct ArcGIS image response fallback"
                except Exception as direct_error:
                    if isinstance(direct_error, ProviderError):
                        raise direct_error from json_error
                    raise ProviderError(
                        "USGS could not prepare this elevation extract. Please try again shortly."
                    ) from direct_error

        return DownloadedAsset(
            path=output_path,
            source_url=href,
            provider_name="USGS 3DEP",
            product_name="USGS 3DEP Bare Earth DEM dynamic extract",
            acquisition_note="Downloaded as a bounded float32 GeoTIFF from the USGS dynamic elevation service",
            provider_metadata={
                "source_id": "usgs_seamless",
                "service": self.service_url,
                "license": "U.S. Geological Survey data; public domain unless otherwise noted",
                "attribution": "USGS National Map 3D Elevation Program (3DEP)",
                "horizontal_crs_request": "EPSG:4326",
                "vertical_units": "meters (service elevation pixels)",
                "vertical_datum": "Source-dependent; not declared globally by the service",
                "requested_ground_spacing": "Approximately 10 meters, subject to export size caps",
                "requested_grid": f"{width} x {height} cells",
                "redistribution": "Allowed for USGS public-domain data; retain source attribution",
                "retrieval_method": retrieval_method,
            },
        )
