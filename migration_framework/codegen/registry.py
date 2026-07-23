"""Registry mapping source/target pairs to code generators.

A generator is selected by the target connector family. If a specific pair has
no dedicated generator, SQL is the safe fallback.
"""

from __future__ import annotations

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode
from .cross_generator import CrossWarehouseGenerator
from .pyspark_generator import PySparkGenerator
from .snowpark_generator import SnowparkGenerator
from .sql_generator import SQLGenerator

_GENERATORS: dict[str, type[CodeGenerator]] = {
    "databricks": PySparkGenerator,
    "pyspark": PySparkGenerator,
    "snowflake": SnowparkGenerator,
    "snowpark": SnowparkGenerator,
    "bigquery": SQLGenerator,
    "redshift": SQLGenerator,
    "sqlalchemy": SQLGenerator,
    "sql": SQLGenerator,
    "default": SQLGenerator,
    "cross": CrossWarehouseGenerator,
}


def register_generator(name: str, generator_cls: type[CodeGenerator]) -> None:
    _GENERATORS[name] = generator_cls


def _connector_family(connector_name: str) -> str:
    """Map a connector name to a generator family."""
    lowered = connector_name.lower()
    if "databricks" in lowered or "pyspark" in lowered:
        return "databricks"
    if "snowflake" in lowered or "snowpark" in lowered:
        return "snowflake"
    if any(name in lowered for name in ("sqlalchemy", "bigquery", "redshift", "sql")):
        return "sql"
    return lowered


def build_generator(config: MigrationConfig, config_path: str | None = None) -> CodeGenerator:
    source_family = _connector_family(config.source.connector)
    target_family = _connector_family(config.target.connector)

    # Unknown target families fall back to the generic SQL generator.
    if target_family not in ("databricks", "snowflake", "sql"):
        generator = SQLGenerator()
        generator.source_connector = config.source.connector
        generator.target_connector = config.target.connector
        return generator

    # Databricks targets always get a PySpark script: it can read Delta for
    # Databricks sources or JDBC for SQL/Snowflake sources.
    if target_family == "databricks":
        generator = PySparkGenerator()
        generator.source_connector = config.source.connector
        generator.target_connector = config.target.connector
        return generator

    # Same-family Snowflake migration uses Snowpark.
    if target_family == "snowflake" and source_family == "snowflake":
        generator = SnowparkGenerator()
        generator.source_connector = config.source.connector
        generator.target_connector = config.target.connector
        return generator

    # Same-family SQL migration uses SQL.
    if target_family == "sql" and source_family == "sql":
        generator = SQLGenerator()
        generator.source_connector = config.source.connector
        generator.target_connector = config.target.connector
        return generator

    # Every other cross-warehouse pair emits a Python script that runs the
    # migration engine with the native connectors.
    return CrossWarehouseGenerator(config_path=config_path)


def generate_for(config: MigrationConfig, config_path: str | None = None) -> GeneratedCode:
    return build_generator(config, config_path=config_path).generate(config)
