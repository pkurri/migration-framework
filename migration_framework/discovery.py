"""Step 1 of any migration: look at both tables before assuming anything."""

from __future__ import annotations

from typing import Any

from .connectors.base import TableSchema
from .registry import build_connector


def read_schema(connector_name: str, connection: dict[str, Any], table: str, sample_size: int = 50) -> TableSchema:
    connector = build_connector(connector_name, connection)
    return connector.get_schema(table, sample_size=sample_size)


def discover_pair(
    source_connector: str,
    source_connection: dict[str, Any],
    source_table: str,
    target_connector: str,
    target_connection: dict[str, Any],
    target_table: str,
    sample_size: int = 50,
) -> tuple[TableSchema, TableSchema]:
    """Read both sides of a migration. This is the only thing that touches the
    real systems before a mapping is proposed - everything after this is
    reasoning over what got read here."""
    source_schema = read_schema(source_connector, source_connection, source_table, sample_size)
    target_schema = read_schema(target_connector, target_connection, target_table, sample_size)
    return source_schema, target_schema
