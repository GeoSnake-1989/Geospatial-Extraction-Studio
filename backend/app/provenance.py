from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def file_integrity(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def write_source_documentation(
    json_path: Path,
    markdown_path: Path,
    *,
    title: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Write matching machine- and human-readable evidence for a raster output."""
    payload = {
        "schema": "geospatial-extraction-studio/source-evidence/v1",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **evidence,
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    provider = str(payload.get("provider", "Not declared"))
    product = str(payload.get("product", "Not declared"))
    output = payload.get("output", {})
    source_urls = payload.get("source_urls", [])
    if isinstance(source_urls, str):
        source_urls = [source_urls]

    lines = [
        f"# {title}",
        "",
        "This file is the source-evidence record created with the raster in this folder.",
        "The adjacent JSON file contains the same evidence in machine-readable form.",
        "",
        "## Dataset",
        "",
        f"- Provider: {provider}",
        f"- Product: {product}",
        f"- Evidence recorded (UTC): {payload['recorded_at_utc']}",
        f"- Raster file: {output.get('filename', 'Not declared')}",
        f"- Raster size (bytes): {output.get('bytes', 'Not declared')}",
        f"- Raster SHA-256: `{output.get('sha256', 'Not declared')}`",
        "",
        "## Source URLs",
        "",
    ]
    if source_urls:
        lines.extend(f"- {url}" for url in source_urls)
    else:
        lines.append("- Not declared")
    lines.extend(
        [
            "",
            "## Complete evidence record",
            "",
            "```json",
            json.dumps(payload, indent=2),
            "```",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return payload
