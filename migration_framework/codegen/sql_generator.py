"""Generate a plain SQL INSERT/SELECT load script from a MigrationConfig."""

from __future__ import annotations

import textwrap

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode


class SQLGenerator(CodeGenerator):
    """Generate a plain SQL SELECT/INSERT statement for the migration."""

    def generate(self, config: MigrationConfig) -> GeneratedCode:
        source = config.source
        target = config.target
        filename = f"{config.job_name}.sql"

        selects: list[str] = []
        for m in config.columns:
            if m.derived is not None:
                expr = self._derived_expr(m.derived)
            elif m.source:
                expr = m.source
                if m.trim:
                    expr = f"TRIM({expr})"
                if m.cast:
                    expr = self._cast_expr(expr, m.cast)
                if m.default is not None:
                    expr = f"COALESCE({expr}, {self._sql_literal(m.default)})"
            else:
                expr = "NULL"
            selects.append(f"{expr} AS {m.target}")

        audit_selects = []
        for a in config.audit_columns:
            if a.generator == "batch_id":
                audit_selects.append(f"CAST(CURRENT_DATE AS VARCHAR) AS {a.name}")
            elif a.generator == "now":
                audit_selects.append(f"CURRENT_TIMESTAMP AS {a.name}")
            else:
                audit_selects.append(f"NULL AS {a.name}")

        all_selects = selects + audit_selects
        body = textwrap.dedent(f"""\
            -- {config.job_name}
            -- source: {source.connector}:{source.table}
            -- target: {target.connector}:{target.table}

            INSERT INTO {target.table} (
                {", ".join(
                    m.target for m in config.columns
                ) + (", " + ", ".join(a.name for a in config.audit_columns) if config.audit_columns else "")}
            )
            SELECT
                {",\n                ".join(all_selects)}
            FROM {source.table};
            """)

        return GeneratedCode(path=f"generated/{filename}", language="sql", body=body)

    def _derived_expr(self, derived: dict) -> str:
        from ..conditions import Condition

        cases: list[str] = []
        for rule in derived.get("when", []):
            cond = Condition.parse(rule["condition"])
            sql = cond.to_sql()
            cases.append(f"WHEN {sql} THEN {self._sql_literal(rule['then'])}")
        otherwise = derived.get("otherwise")
        else_clause = f"\n        ELSE {self._sql_literal(otherwise)}" if otherwise is not None else ""
        return f"CASE\n        {chr(10).join(cases)}{else_clause}\n    END"

    def _cast_expr(self, expr: str, cast: str) -> str:
        mapping = {
            "date": "DATE",
            "timestamp": "TIMESTAMP",
            "int": "INTEGER",
            "integer": "INTEGER",
            "float": "DOUBLE",
            "bool": "BOOLEAN",
            "boolean": "BOOLEAN",
            "string": "VARCHAR",
            "str": "VARCHAR",
        }
        return f"CAST({expr} AS {mapping.get(cast, cast.upper())})"

    def _sql_literal(self, value) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, str):
            escaped = value.replace("'", "''")
            return f"'{escaped}'"
        return str(value)
