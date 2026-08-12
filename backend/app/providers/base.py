from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..models import BoundingBox


@dataclass(frozen=True)
class DownloadedAsset:
    path: Path
    source_url: str
    provider_name: str
    product_name: str
    acquisition_note: str
    provider_metadata: dict[str, str]


class ElevationProvider(Protocol):
    async def extract(
        self, bounds: BoundingBox, output_path: Path, width: int, height: int
    ) -> DownloadedAsset: ...
