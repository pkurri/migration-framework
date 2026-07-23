"""Generate a PySpark load script from a MigrationConfig."""

from __future__ import annotations

import textwrap

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode


class PySparkGenerator(CodeGenerator):
    """Generate PySpark code for loading a source table into a target."""

    def generate(self, config: MigrationConfig) -> GeneratedCode:
        source = config.source
        target = config.target
        filename = f"{config.job_name}_pyspark.py"

        selects: list[str] = []
        for m in config.columns:
            expr: str
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

        import_expr = self._import_expr(config)
        select_block = self._indent(",\n                ".join(selects), 16)
        audit_block = self._audit_code(config)
        audit_lines = "\n\n" + audit_block if audit_block else ""

        body = textwrap.dedent(f"""\
            {import_expr}

            spark = SparkSession.builder.appName("{config.job_name}").getOrCreate()

            df = (
                spark.read
                .format("jdbc")
                .option("url", "<SOURCE_URL>")
                .option("dbtable", "{source.table}")
                .load()
            )

            projected = df.select(
                {select_block}
            )
            {audit_lines}

            (
                projected.write
                .mode("{target.mode}")
                .format("jdbc")
                .option("url", "<TARGET_URL>")
                .option("dbtable", "{target.table}")
                .save()
            )
            """)

        return GeneratedCode(path=f"generated/{filename}", language="pyspark", body=body)

    def _indent(self, text: str, width: int) -> str:
        return "\n".join(" " * width + line for line in text.splitlines())

    def _import_expr(self, config: MigrationConfig) -> str:
        imports = ["SparkSession"]
        funcs = ["col", "lit", "coalesce", "trim", "when"]
        has_date = any(m.cast in ("date", "timestamp") for m in config.columns)
        has_ts = any(a.generator in ("batch_id", "now") for a in config.audit_columns)
        if has_date:
            funcs.extend(["to_date", "to_timestamp"])
        if has_ts:
            funcs.append("current_timestamp")
        func_line = ", ".join(funcs)
        lines = [
            "from pyspark.sql import " + ", ".join(imports),
            f"from pyspark.sql.functions import {func_line}",
        ]
        if any(a.generator == "batch_id" for a in config.audit_columns):
            lines.append("from datetime import datetime")
        return "\n".join(lines)

    def _derived_expr(self, derived: dict) -> str:
        from ..conditions import Condition

        branches: list[str] = []
        for rule in derived.get("when", []):
            cond = Condition.parse(rule["condition"])
            sql = cond.to_sql()
            branches.append(f"when({sql}, lit({self._repr(rule['then'])}))")
        otherwise = derived.get("otherwise")
        chain = ".".join(branches)
        if otherwise is not None:
            return f"{chain}.otherwise(lit({self._repr(otherwise)}))"
        return f"{chain}.otherwise(lit(None))"

    def _cast_expr(self, expr: str, cast: str) -> str:
        mapping = {
            "date": "to_date",
            "timestamp": "to_timestamp",
            "int": "cast('int')",
            "integer": "cast('int')",
            "float": "cast('double')",
            "bool": "cast('boolean')",
            "boolean": "cast('boolean')",
            "string": "cast('string')",
            "str": "cast('string')",
        }
        if cast in ("date", "timestamp"):
            return f"{mapping[cast]}({expr})"
        if cast.startswith("cast"):
            return f"{expr}.{cast}"
        return f"{expr}.cast('{mapping.get(cast, cast)}')"

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
                expr = "lit(datetime.now().strftime('%Y%m%d'))"
            elif a.generator == "now":
                expr = "current_timestamp()"
            else:
                expr = "lit(None)"
            lines.append(f"projected = projected.withColumn('{a.name}', {expr})")
        return "\n".join(lines)
