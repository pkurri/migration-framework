"""A single connector that works with any database SQLAlchemy has a dialect for.

That covers Postgres, MySQL, SQLite, SQL Server, Oracle, BigQuery, Snowflake,
and Databricks out of the box (the last three need their own small dialect
package installed - e.g. `snowflake-sqlalchemy`, `databricks-sqlalchemy` -
but need zero code changes here). This is what makes the framework
tool-agnostic on the "which database" axis: one connector, any SQL engine,
just a different connection string.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from sqlalchemy import MetaData, Table, create_engine, insert, inspect, select, text
from sqlalchemy.engine import Engine

from .base import ColumnInfo, Connector, TableSchema

_TYPE_MAP: dict[str, str] = {
    "INTEGER": "integer",
    "SMALLINT": "integer",
    "BIGINT": "integer",
    "NUMERIC": "float",
    "DECIMAL": "float",
    "FLOAT": "float",
    "REAL": "float",
    "DOUBLE": "float",
    "DOUBLE_PRECISION": "float",
    "BOOLEAN": "boolean",
    "DATE": "date",
    "DATETIME": "timestamp",
    "TIMESTAMP": "timestamp",
    "VARCHAR": "string",
    "NVARCHAR": "string",
    "CHAR": "string",
    "TEXT": "string",
    "CLOB": "string",
    "STRING": "string",
}


def _canonical_type(sa_type: Any) -> str:
    name = type(sa_type).__name__.upper()
    return _TYPE_MAP.get(name, "other")


class SQLAlchemyConnector(Connector):
    """Wraps any SQLAlchemy-compatible database behind one connector."""

    def __init__(self, connection_url: str, schema: str | None = None, **engine_kwargs: Any):
        self.connection_url = connection_url
        self.db_schema = schema
        self._engine: Engine = create_engine(connection_url, **engine_kwargs)
        self._metadata = MetaData()

    def _reflect(self, table: str) -> Table:
        return Table(table, self._metadata, autoload_with=self._engine, schema=self.db_schema)

    def get_schema(self, table: str, sample_size: int = 50) -> TableSchema:
        inspector = inspect(self._engine)
        raw_columns = inspector.get_columns(table, schema=self.db_schema)
        columns = [
            ColumnInfo(
                name=col["name"],
                canonical_type=_canonical_type(col["type"]),
                native_type=str(col["type"]),
                nullable=col.get("nullable", True),
            )
            for col in raw_columns
        ]

        sample_rows: list[dict[str, Any]] = []
        if sample_size > 0:
            sa_table = self._reflect(table)
            with self._engine.connect() as conn:
                result = conn.execute(select(sa_table).limit(sample_size))
                sample_rows = [dict(row) for row in result.mappings()]

        return TableSchema(name=table, columns=columns, sample_rows=sample_rows)

    def read_rows(self, table: str, columns: Iterable[str] | None = None) -> Iterator[dict[str, Any]]:
        sa_table = self._reflect(table)
        cols = [sa_table.c[c] for c in columns] if columns else [sa_table]
        with self._engine.connect() as conn:
            result = conn.execute(select(*cols) if columns else select(sa_table))
            for row in result.mappings():
                yield dict(row)

    def write_rows(self, table: str, rows: Iterable[dict[str, Any]], mode: str = "append") -> int:
        rows = list(rows)
        if not rows:
            return 0
        sa_table = self._reflect(table)
        with self._engine.begin() as conn:
            if mode == "overwrite":
                conn.execute(sa_table.delete())
            conn.execute(insert(sa_table), rows)
        return len(rows)

    def row_count(self, table: str) -> int:
        sa_table = self._reflect(table)
        with self._engine.connect() as conn:
            return conn.execute(select(text("count(*)")).select_from(sa_table)).scalar_one()

    def execute(self, sql: str) -> None:
        """Escape hatch for pre-actions (`USE DATABASE ...`, session setup, etc.)."""
        with self._engine.begin() as conn:
            conn.execute(text(sql))
