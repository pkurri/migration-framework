from migration_framework.codegen import build_generator, generate_for
from migration_framework.codegen.cross_generator import CrossWarehouseGenerator
from migration_framework.codegen.pyspark_generator import PySparkGenerator
from migration_framework.codegen.snowpark_generator import SnowparkGenerator
from migration_framework.codegen.sql_generator import SQLGenerator
from migration_framework.config import MigrationConfig, SourceSpec, TargetSpec


def _config(source_connector: str, target_connector: str) -> MigrationConfig:
    return MigrationConfig(
        job_name="demo",
        source=SourceSpec(connector=source_connector, connection={}, table="bronze.orders"),
        target=TargetSpec(connector=target_connector, connection={}, table="silver.orders"),
        columns=[],
    )


def test_same_snowflake_uses_snowpark():
    gen = build_generator(_config("snowflake", "snowflake"))
    assert isinstance(gen, SnowparkGenerator)


def test_same_databricks_uses_pyspark():
    gen = build_generator(_config("databricks", "databricks"))
    assert isinstance(gen, PySparkGenerator)


def test_same_sqlalchemy_uses_sql():
    gen = build_generator(_config("sqlalchemy", "sqlalchemy"))
    assert isinstance(gen, SQLGenerator)


def test_cross_combinations_use_cross_generator():
    for src, tgt in [
        ("databricks", "snowflake"),
        ("sqlalchemy", "snowflake"),
        ("snowflake", "sqlalchemy"),
    ]:
        gen = build_generator(_config(src, tgt))
        assert isinstance(gen, CrossWarehouseGenerator), f"{src}->{tgt} should be cross"


def test_snowflake_to_databricks_uses_pyspark():
    gen = build_generator(_config("snowflake", "databricks"))
    assert isinstance(gen, PySparkGenerator)


def test_cross_generator_emits_python_engine_script():
    config = _config("databricks", "snowflake")
    generated = generate_for(config, config_path="demo.yaml")
    assert generated.language == "python"
    assert "run_migration" in generated.body
    assert "MigrationConfig.load" in generated.body
    assert "demo.yaml" in generated.body


def test_pyspark_generator_uses_delta_for_databricks_source():
    gen = build_generator(_config("databricks", "databricks"))
    generated = gen.generate(_config("databricks", "databricks"))
    assert 'spark.read.format("delta")' in generated.body
    assert "bronze.orders" in generated.body


def test_pyspark_generator_uses_jdbc_for_sqlalchemy_source():
    gen = build_generator(_config("sqlalchemy", "databricks"))
    generated = gen.generate(_config("sqlalchemy", "databricks"))
    assert 'spark.read' in generated.body
    assert 'format("jdbc")' in generated.body
    assert "<SOURCE_URL>" in generated.body
