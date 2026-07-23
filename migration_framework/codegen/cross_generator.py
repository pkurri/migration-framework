"""Generate a standalone Python load script for cross-warehouse migrations.

When the source and target live in different systems (e.g. Databricks ->
Snowflake, Snowflake -> SQL, etc.) a single SQL/Spark/Snowpark statement is
usually not enough.  This generator emits a Python script that imports the
migration framework and uses the engine to read from the source connector and
write to the target connector, so the same tool-agnostic logic handles every
combination.
"""

from __future__ import annotations

import textwrap

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode


class CrossWarehouseGenerator(CodeGenerator):
    """Generate a Python script that runs a MigrationConfig through the engine."""

    def __init__(self, config_path: str | None = None) -> None:
        self.config_path = config_path or "<CONFIG_PATH>"

    def generate(self, config: MigrationConfig) -> GeneratedCode:
        filename = f"{config.job_name}_cross.py"
        body = textwrap.dedent(f'''\
            """Cross-warehouse load script for {config.job_name}.

            Generated for {config.source.connector}:{config.source.table} ->
            {config.target.connector}:{config.target.table}.
            """

            import sys

            from migration_framework.config import MigrationConfig
            from migration_framework.engine import run_migration

            config_path = sys.argv[1] if len(sys.argv) > 1 else "{self.config_path}"
            config = MigrationConfig.load(config_path)
            result = run_migration(config)
            print(
                f"wrote {{result.rows_written}} rows to {{config.target.table}} "
                f"({{result.target_row_count_before}} -> {{result.target_row_count_after}})"
            )
            ''')
        return GeneratedCode(path=f"generated/{filename}", language="python", body=body)
