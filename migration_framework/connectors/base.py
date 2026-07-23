"""Connector interface that every source/target system implements.

Anything that can answer these four questions can be migrated to or from:
what columns does this table have, what do a few of its rows look like,
give me all its rows, and take these rows and store them.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator


@dataclass
class ColumnInfo:
    name: str
    canonical_type: str  # one of: string, integer, float, boolean, date, timestamp, other
    native_type: str  # the type name as reported by the underlying system
    nullable: bool = True


@dataclass
class TableSchema:
    name: str
    columns: list[ColumnInfo]
    sample_rows: list[dict[str, Any]] = field(default_factory=list)

    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


class Connector(ABC):
    """One implementation per system (a database, a warehouse, a file format, ...).

    A new source or target only needs a new Connector subclass - nothing else
    in the framework (discovery, mapping, the engine, the CLI) knows or cares
    which system it's talking to.
    """

    @abstractmethod
    def get_schema(self, table: str, sample_size: int = 50) -> TableSchema:
        """Return the table's columns/types plus a small sample of real rows."""

    @abstractmethod
    def read_rows(self, table: str, columns: Iterable[str] | None = None) -> Iterator[dict[str, Any]]:
        """Yield every row of `table` as a dict, optionally limited to `columns`."""

    @abstractmethod
    def write_rows(self, table: str, rows: Iterable[dict[str, Any]], mode: str = "append") -> int:
        """Write `rows` into `table`. Returns the number of rows written."""

    @abstractmethod
    def row_count(self, table: str) -> int:
        """Return the current row count of `table`, for reconciliation."""
