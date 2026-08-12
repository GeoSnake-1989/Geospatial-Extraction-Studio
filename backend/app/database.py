from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from .config import DB_PATH


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                provider TEXT NOT NULL,
                created_at TEXT NOT NULL,
                original_path TEXT NOT NULL,
                processed_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS osm_exports (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                archive_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS naip_imagery (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                imagery_path TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )


def save_dataset(dataset: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO datasets
            (id, label, provider, created_at, original_path, processed_path, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dataset["id"],
                dataset["label"],
                dataset["provider"],
                datetime.now(UTC).isoformat(),
                dataset["files"]["original"],
                dataset["files"]["processed"],
                json.dumps(dataset),
            ),
        )


def list_datasets(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT metadata_json FROM datasets ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row["metadata_json"]) for row in rows]


def get_dataset(dataset_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM datasets WHERE id = ?", (dataset_id,)
        ).fetchone()
    return json.loads(row["metadata_json"]) if row else None


def delete_dataset(dataset_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))


def save_osm_export(export: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO osm_exports
            (id, label, created_at, archive_path, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                export["id"],
                export["label"],
                datetime.now(UTC).isoformat(),
                export["files"]["archive"],
                json.dumps(export),
            ),
        )


def list_osm_exports(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT metadata_json FROM osm_exports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row["metadata_json"]) for row in rows]


def get_osm_export(export_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM osm_exports WHERE id = ?", (export_id,)
        ).fetchone()
    return json.loads(row["metadata_json"]) if row else None


def delete_osm_export(export_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM osm_exports WHERE id = ?", (export_id,))


def save_naip_imagery(imagery: dict[str, Any]) -> None:
    with connect() as connection:
        connection.execute(
            """
            INSERT OR REPLACE INTO naip_imagery
            (id, label, created_at, imagery_path, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                imagery["id"],
                imagery["label"],
                datetime.now(UTC).isoformat(),
                imagery["files"]["imagery"],
                json.dumps(imagery),
            ),
        )


def list_naip_imagery(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT metadata_json FROM naip_imagery ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [json.loads(row["metadata_json"]) for row in rows]


def get_naip_imagery(imagery_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT metadata_json FROM naip_imagery WHERE id = ?", (imagery_id,)
        ).fetchone()
    return json.loads(row["metadata_json"]) if row else None


def delete_naip_imagery(imagery_id: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM naip_imagery WHERE id = ?", (imagery_id,))
