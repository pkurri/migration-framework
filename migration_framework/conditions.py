"""A tiny, safe expression language for derived-column rules.

Config files are data, not code, so a rule like::

    hdr.PO_VERSION in ('E', 'B')

is parsed by hand into a small AST and evaluated against a row - never
passed to ``eval()``. Only a few shapes are supported on purpose; anything
else raises a clear error at config-load time instead of silently doing the
wrong thing at run time.

Supported forms:
    column == 'value'
    column != 'value'
    column in ('a', 'b', 'c')
    column not in ('a', 'b', 'c')
    column is null
    column is not null
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_IN_RE = re.compile(r"^\s*([\w.]+)\s+(not\s+in|in)\s*\((.*)\)\s*$", re.IGNORECASE)
_EQ_RE = re.compile(r"^\s*([\w.]+)\s*(==|!=)\s*(.+?)\s*$")
_NULL_RE = re.compile(r"^\s*([\w.]+)\s+is\s+(not\s+)?null\s*$", re.IGNORECASE)


class ConditionError(ValueError):
    pass


def _strip_alias(column_ref: str) -> str:
    """`hdr.PO_VERSION` and `PO_VERSION` both refer to the row key `PO_VERSION`."""
    return column_ref.split(".")[-1]


def _parse_literal(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith(("'", '"')) and raw.endswith(("'", '"')) and len(raw) >= 2:
        return raw[1:-1]
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _split_list(raw: str) -> list[Any]:
    parts = [p.strip() for p in raw.split(",") if p.strip() != ""]
    return [_parse_literal(p) for p in parts]


@dataclass
class Condition:
    """A parsed condition. Call `.evaluate(row)` to test it against a row dict."""

    raw: str
    column: str
    op: str  # "eq", "ne", "in", "not_in", "is_null", "is_not_null"
    value: Any = None

    def _sql_literal(self, value: Any) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        return str(value)

    def to_sql(self, column_ref: str | None = None) -> str:
        """Render the condition as a SQL expression for code generators."""
        col = column_ref or self.column
        if self.op == "eq":
            return f"{col} = {self._sql_literal(self.value)}"
        if self.op == "ne":
            return f"{col} <> {self._sql_literal(self.value)}"
        if self.op == "in":
            values = ", ".join(self._sql_literal(v) for v in self.value)
            return f"{col} IN ({values})"
        if self.op == "not_in":
            values = ", ".join(self._sql_literal(v) for v in self.value)
            return f"{col} NOT IN ({values})"
        if self.op == "is_null":
            return f"{col} IS NULL"
        if self.op == "is_not_null":
            return f"{col} IS NOT NULL"
        raise ConditionError(f"Unhandled operator {self.op!r} in condition {self.raw!r}")

    def evaluate(self, row: dict[str, Any]) -> bool:
        actual = row.get(self.column)
        if self.op == "eq":
            return actual == self.value
        if self.op == "ne":
            return actual != self.value
        if self.op == "in":
            return actual in self.value
        if self.op == "not_in":
            return actual not in self.value
        if self.op == "is_null":
            return actual is None
        if self.op == "is_not_null":
            return actual is not None
        raise ConditionError(f"Unhandled operator {self.op!r} in condition {self.raw!r}")

    @classmethod
    def parse(cls, expression: str) -> "Condition":
        expr = expression.strip()

        m = _NULL_RE.match(expr)
        if m:
            column = _strip_alias(m.group(1))
            negated = bool(m.group(2))
            return cls(raw=expr, column=column, op="is_not_null" if negated else "is_null")

        m = _IN_RE.match(expr)
        if m:
            column = _strip_alias(m.group(1))
            negated = m.group(2).strip().lower().startswith("not")
            values = _split_list(m.group(3))
            return cls(raw=expr, column=column, op="not_in" if negated else "in", value=values)

        m = _EQ_RE.match(expr)
        if m:
            column = _strip_alias(m.group(1))
            op = "eq" if m.group(2) == "==" else "ne"
            value = _parse_literal(m.group(3))
            return cls(raw=expr, column=column, op=op, value=value)

        raise ConditionError(
            f"Can't parse condition {expression!r}. Supported forms: "
            "'col == value', 'col != value', 'col in (a, b)', 'col not in (a, b)', "
            "'col is null', 'col is not null'."
        )
