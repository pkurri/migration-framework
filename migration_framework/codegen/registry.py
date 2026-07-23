"""Registry mapping source/target pairs to code generators.

A generator is selected by the target connector family. If a specific pair has
no dedicated generator, SQL is the safe fallback.
"""

from __future__ import annotations

from ..config import MigrationConfig
from .base import CodeGenerator, GeneratedCode
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
}


def register_generator(name: str, generator_cls: type[CodeGenerator]) -> None:
    _GENERATORS[name] = generator_cls


def _connector_family(connector_name: str) -> str:
    """Map a connector name to a generator family."""
    lowered = connector_name.lower()
    if "databricks" in lowered or "pyspark" in lowered:
        return "pyspark"
    if "snowflake" in lowered or "snowpark" in lowered:
        return "snowpark"
    if "bigquery" in lowered or "big_query" in lowered:
        return "bigquery"
    if "redshift" in lowered:
        return "redshift"
    return lowered


def build_generator(config: MigrationConfig) -> CodeGenerator:
    family = _connector_family(config.target.connector)
    generator_cls = _GENERATORS.get(family, _GENERATORS["default"])
    return generator_cls()


def generate_for(config: MigrationConfig) -> GeneratedCode:
    return build_generator(config).generate(config)
