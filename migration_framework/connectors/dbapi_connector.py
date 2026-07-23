"""Native DB-API 2.0 connectors for Snowflake and Databricks SQL warehouses.

These use the official Python drivers (`snowflake-connector-python` and
`databricks-sql-connector`) instead of SQLAlchemy dialects.  They are kept
as optional dependencies so the core framework does not require them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Iterator

from .base import ColumnInfo, Connector, TableSchema


class NativeDBAPIConnector(Connector, ABC):
    """Shared logic for DB-API 2.0 native connectors."""

    _module: Any
    _paramstyle: str
    _quote: str = '"'

    def __init__(self, **connection_kwargs: Any):
        self._connection_kwargs = connection_kwargs
        self._connection: Any | None = None

    def _connect(self) -> Any:
        if self._connection is None:
            self._connection = self._module.connect(**self._connection_kwargs)
        return self._connection

    @abstractmethod
    def _column_from_desc(self, row: tuple[Any, ...]) -> ColumnInfo | None:
        """Convert a DESCRIBE TABLE row into a ColumnInfo."""

    def _canonical_type(self, native_type: str) -> str:
        """Map a native type name to one of the framework canonical types."""
        name = native_type.upper().split("(")[0].split("<")[0].strip()
        mapping: dict[str, str] = {
            "STRING": "string",
            "VARCHAR": "string",
            "CHAR": "string",
            "TEXT": "string",
            "NVARCHAR": "string",
            "INT": "integer",
            "INTEGER": "integer",
            "BIGINT": "integer",
            "SMALLINT": "integer",
            "TINYINT": "integer",
            "NUMBER": "integer",
            "NUMERIC": "float",
            "DECIMAL": "float",
            "FLOAT": "float",
            "DOUBLE": "float",
            "REAL": "float",
            "BOOLEAN": "boolean",
            "BOOL": "boolean",
            "DATE": "date",
            "TIMESTAMP": "timestamp",
            "TIMESTAMP_LTZ": "timestamp",
            "TIMESTAMP_NTZ": "timestamp",
            "TIMESTAMP_TZ": "timestamp",
            "DATETIME": "timestamp",
        }
        return mapping.get(name, "other")

    def _quote_id(self, name: str) -> str:
        return f"{self._quote}{name}{self._quote}"

    def _placeholders(self, keys: list[str]) -> str:
        """Return the value-placeholder string for an INSERT."""
        if self._paramstyle == "named":
            return ", ".join(f":{k}" for k in keys)
        if self._paramstyle == "qmark":
            return ", ".join(["?"] * len(keys))
        if self._paramstyle == "numeric":
            return ", ".join(f":{i + 1}" for i in range(len(keys)))
        # pyformat / format use %(name)s.
        return ", ".join(f"%({k})s" for k in keys)

    def _row_params(self, row: dict[str, Any], keys: list[str]) -> Any:
        if self._paramstyle in ("named", "pyformat", "format"):
            return {k: row[k] for k in keys}
        # qmark / numeric
        return tuple(row[k] for k in keys)

    def get_schema(self, table: str, sample_size: int = 50) -> TableSchema:
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(f"DESCRIBE TABLE {table}")
            desc_rows = cur.fetchall()
            columns: list[ColumnInfo] = []
            for row in desc_rows:
                col = self._column_from_desc(row)
                if col is not None:
                    columns.append(col)

            sample_rows: list[dict[str, Any]] = []
            if sample_size > 0 and columns:
                col_list = ", ".join(self._quote_id(c.name) for c in columns)
                cur.execute(f"SELECT {col_list} FROM {table} LIMIT {sample_size}")
                keys = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    sample_rows.append(dict(zip(keys, row)))
        finally:
            cur.close()

        return TableSchema(name=table, columns=columns, sample_rows=sample_rows)

    def read_rows(
        self, table: str, columns: Iterable[str] | None = None
    ) -> Iterator[dict[str, Any]]:
        conn = self._connect()
        cur = conn.cursor()
        try:
            if columns:
                col_list = ", ".join(self._quote_id(c) for c in columns)
            else:
                col_list = "*"
            cur.execute(f"SELECT {col_list} FROM {table}")
            keys = [d[0] for d in cur.description]
            for row in cur.fetchall():
                yield dict(zip(keys, row))
        finally:
            cur.close()

    def write_rows(
        self, table: str, rows: Iterable[dict[str, Any]], mode: str = "append"
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        conn = self._connect()
        cur = conn.cursor()
        try:
            if mode == "overwrite":
                cur.execute(f"DELETE FROM {table}")

            keys = list(rows[0].keys())
            cols = ", ".join(self._quote_id(k) for k in keys)
            placeholders = self._placeholders(keys)
            sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
            params = [self._row_params(r, keys) for r in rows]
            cur.executemany(sql, params)
        finally:
            cur.close()
        conn.commit()
        return len(rows)

    def row_count(self, table: str) -> int:
        conn = self._connect()
        cur = conn.cursor()
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            return cur.fetchone()[0]
        finally:
            cur.close()


class SnowflakeConnector(NativeDBAPIConnector):
    """Native connector for Snowflake using `snowflake-connector-python`."""

    def __init__(self, **connection_kwargs: Any):
        import snowflake.connector

        self._module = snowflake.connector
        self._paramstyle = snowflake.connector.paramstyle
        super().__init__(**connection_kwargs)

    def _column_from_desc(self, row: tuple[Any, ...]) -> ColumnInfo | None:
        # Snowflake DESC TABLE columns: name, type, kind, null?, default, ...
        if len(row) < 2:
            return None
        name = row[0]
        native_type = row[1]
        nullable = True
        if len(row) > 3:
            nullable = str(row[3]).upper() in ("Y", "YES", "TRUE")
        return ColumnInfo(
            name=name,
            canonical_type=self._canonical_type(native_type),
            native_type=str(native_type),
            nullable=nullable,
        )


class DatabricksConnector(NativeDBAPIConnector):
    """Native connector for Databricks using `databricks-sql-connector`."""

    def __init__(self, **connection_kwargs: Any):
        import databricks.sql

        self._module = databricks.sql
        self._paramstyle = databricks.sql.paramstyle
        super().__init__(**connection_kwargs)

    def _column_from_desc(self, row: tuple[Any, ...]) -> ColumnInfo | None:
        # Databricks DESC TABLE columns: col_name, data_type, comment
        if len(row) < 2:
            return None
        name = row[0]
        native_type = row[1]
        return ColumnInfo(
            name=name,
            canonical_type=self._canonical_type(native_type),
            native_type=str(native_type),
            nullable=True,
        )
