from __future__ import annotations

from typing import Any


NOTICE_FILENAME = "DATA_LICENSE_NOTICE.md"


def _text_values(*values: object) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _license_links(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    links: list[str] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("href"):
            continue
        label = str(item.get("title") or "License terms")
        links.append(f"{label}: {item['href']}")
    return links


def data_license_notice_markdown(evidence: dict[str, Any]) -> str:
    """Render a portable, human-readable notice for a downloaded dataset."""
    source = evidence.get("source")
    source = source if isinstance(source, dict) else {}
    collection = evidence.get("collection")
    collection = collection if isinstance(collection, dict) else {}

    attribution = _text_values(evidence.get("attribution"), source.get("attribution"))
    license_declarations = _text_values(
        evidence.get("source_license_summary"),
        evidence.get("license"),
        source.get("license"),
        collection.get("license"),
    )
    reuse_terms = _text_values(evidence.get("license_note"), source.get("redistribution"))
    license_links = _license_links(collection.get("license_links"))
    source_urls = evidence.get("source_urls") or []
    if isinstance(source_urls, str):
        source_urls = [source_urls]

    lines = [
        "# Data license and attribution notice",
        "",
        "Keep this notice with the accompanying dataset when copying or redistributing it.",
        "The application license does not relicense provider data.",
        "",
        "## Dataset",
        "",
        f"- Provider: {evidence.get('provider') or 'Not declared'}",
        f"- Product: {evidence.get('product') or 'Not declared'}",
        "",
        "## Required attribution",
        "",
    ]
    lines.extend(f"- {value}" for value in dict.fromkeys(attribution))
    if not attribution:
        lines.append("- No provider-specific attribution was declared in the source record.")
    lines.extend(["", "## License and reuse terms", ""])
    lines.extend(f"- {value}" for value in dict.fromkeys(license_declarations))
    lines.extend(f"- {value}" for value in dict.fromkeys(reuse_terms))
    lines.extend(f"- {value}" for value in dict.fromkeys(license_links))
    if not license_declarations and not reuse_terms and not license_links:
        lines.append("- No license or reuse terms were declared in the source record.")
    lines.extend(["", "## Source records", ""])
    lines.extend(f"- {url}" for url in dict.fromkeys(str(url) for url in source_urls if url))
    if not source_urls:
        lines.append("- Not declared")
    lines.extend(
        [
            "",
            "The adjacent `SOURCE_PROVENANCE.json` is the complete machine-readable source record.",
            "",
        ]
    )
    return "\n".join(lines)