"""Generate a Snowpark load script from a MigrationConfig."""

from __future__ import annotations

import textwrap

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode


class SnowparkGenerator(CodeGenerator):
    """Generate Snowpark Python code for loading a source table into Snowflake."""

    def generate(self, config: MigrationConfig) -> GeneratedCode:
        source = config.source
        target = config.target
        filename = f"{config.job_name}_snowpark.py"

        selects: list[str] = []
        for m in config.columns:
            if m.derived is not None:
                expr = self._derived_expr(m.derived)
            elif m.source:
                expr = f"col('{m.source}')"
                if m.trim:
                    expr = f"trim({expr})"
                if m.cast:
                    expr = self._cast_expr(expr, m.cast)
                if m.default is not None:
                    expr = f"coalesce({expr}, lit({self._repr(m.default)}))"
            else:
                expr = "lit(None)"
            selects.append(f"{expr}.alias('{m.target}')")

        body = textwrap.dedent(f"""\
            import snowflake.snowpark.functions as F
            from snowflake.snowpark import Session

            session = Session.builder.getOrCreate()

            df = session.table("{source.table}")

            projected = df.select(
                {",\n                ".join(selects)}
            )

            {self._audit_code(config)}

            projected.write.mode("{target.mode}").save_as_table("{target.table}")
            """)

        return GeneratedCode(path=f"generated/{filename}", language="snowpark", body=body)

    def _derived_expr(self, derived: dict) -> str:
        from ..conditions import Condition

        branches: list[str] = []
        for rule in derived.get("when", []):
            cond = Condition.parse(rule["condition"])
            sql = cond.to_sql()
            branches.append(f"F.when({sql}, F.lit({self._repr(rule['then'])}))")
        otherwise = derived.get("otherwise")
        chain = ".".join(branches)
        if otherwise is not None:
            return f"{chain}.otherwise(F.lit({self._repr(otherwise)}))"
        return f"{chain}.otherwise(F.lit(None))"

    def _cast_expr(self, expr: str, cast: str) -> str:
        mapping = {
            "date": "F.to_date",
            "timestamp": "F.to_timestamp",
            "int": "F.to_int",
            "integer": "F.to_int",
            "float": "F.to_double",
            "bool": "F.to_boolean",
            "boolean": "F.to_boolean",
            "string": "F.to_varchar",
            "str": "F.to_varchar",
        }
        if cast in ("date", "timestamp"):
            return f"{mapping[cast]}({expr})"
        return f"{mapping.get(cast, 'F.to_varchar')}({expr})"

    def _repr(self, value) -> str:
        if isinstance(value, str):
            return repr(value)
        if value is None:
            return "None"
        return repr(value)

    def _audit_code(self, config: MigrationConfig) -> str:
        if not config.audit_columns:
            return ""
        lines = []
        for a in config.audit_columns:
            if a.generator == "batch_id":
                expr = "F.lit(datetime.now().strftime('%Y%m%d'))"
            elif a.generator == "now":
                expr = "F.current_timestamp()"
            else:
                expr = "F.lit(None)"
            lines.append(f"projected = projected.with_column('{a.name}', {expr})")
        return "\n".join(lines)
