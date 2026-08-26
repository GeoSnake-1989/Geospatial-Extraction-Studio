from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from .data_notices import NOTICE_FILENAME, data_license_notice_markdown


def safe_package_component(value: str, fallback: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    cleaned = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", ascii_value)
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip(" ._")
    return (cleaned or fallback)[:100].rstrip(" ._")


def source_evidence_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "geospatial-extraction-studio/source-evidence/v1",
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        **evidence,
    }


def source_evidence_markdown(title: str, payload: dict[str, Any]) -> str:
    provider = str(payload.get("provider", "Not declared"))
    product = str(payload.get("product", "Not declared"))
    output = payload.get("output", {})
    source_urls = payload.get("source_urls", [])
    if isinstance(source_urls, str):
        source_urls = [source_urls]

    lines = [
        f"# {title}",
        "",
        "This source-evidence record is packaged with the raster it documents.",
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
    lines.extend(f"- {url}" for url in source_urls)
    if not source_urls:
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
    return "\n".join(lines)


def build_raster_package(
    archive_path: Path,
    *,
    folder_name: str,
    raster_path: Path,
    raster_filename: str,
    title: str,
    evidence: dict[str, Any],
) -> Path:
    payload = source_evidence_payload(evidence)
    markdown = source_evidence_markdown(title, payload)
    notice = data_license_notice_markdown(payload)
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = archive_path.with_suffix(f"{archive_path.suffix}.part")
    partial_path.unlink(missing_ok=True)
    try:
        with ZipFile(partial_path, "w", allowZip64=True) as archive:
            archive.write(
                raster_path,
                f"{folder_name}/{raster_filename}",
                compress_type=ZIP_STORED,
            )
            archive.writestr(
                f"{folder_name}/SOURCE_PROVENANCE.json",
                json.dumps(payload, indent=2),
                compress_type=ZIP_DEFLATED,
            )
            archive.writestr(
                f"{folder_name}/SOURCE_PROVENANCE.md",
                markdown,
                compress_type=ZIP_DEFLATED,
            )
            archive.writestr(
                f"{folder_name}/{NOTICE_FILENAME}",
                notice,
                compress_type=ZIP_DEFLATED,
            )
        partial_path.replace(archive_path)
        return archive_path
    finally:
        partial_path.unlink(missing_ok=True)
