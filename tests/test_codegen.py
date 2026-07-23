from migration_framework.codegen import generate_for
from migration_framework.config import (
    AuditColumn,
    ColumnMapping,
    MigrationConfig,
    SourceSpec,
    TargetSpec,
    ValidationSpec,
)


def _config(connector: str = "sqlalchemy") -> MigrationConfig:
    return MigrationConfig(
        job_name="orders",
        source=SourceSpec(connector=connector, connection={"connection_url": "sqlite:///src.db"}, table="legacy_orders"),
        target=TargetSpec(connector=connector, connection={"connection_url": "sqlite:///tgt.db"}, table="orders_fact"),
        columns=[
            ColumnMapping(target="order_id", source="ORDER_ID"),
            ColumnMapping(target="order_date", source="ORDER_DT", cast="date"),
            ColumnMapping(
                target="is_cancelled",
                derived={"when": [{"condition": "STATUS_CD == 'X'", "then": "Y"}], "otherwise": "N"},
            ),
        ],
        audit_columns=[
            AuditColumn(name="batch_id", generator="batch_id"),
            AuditColumn(name="etl_load_ts", generator="now"),
        ],
        validation=ValidationSpec(expected_column_count=5),
    )


def test_sql_generator_produces_insert_select():
    config = _config()
    generated = generate_for(config)
    assert "INSERT INTO" in generated.body.upper()
    assert "SELECT" in generated.body.upper()
    assert generated.body.endswith(".sql") is False
    assert generated.path.endswith(".sql")


def test_pyspark_generator_for_pyspark_like_target():
    config = _config(connector="pyspark")
    generated = generate_for(config)
    assert "SparkSession" in generated.body or "spark.read" in generated.body
    assert generated.path.endswith(".py")


def test_snowpark_generator_for_snowflake_target():
    config = _config(connector="snowflake")
    generated = generate_for(config)
    assert "Session.builder" in generated.body or "session.sql" in generated.body
    assert generated.path.endswith(".py")


def test_codegen_includes_derived_column_condition():
    config = _config()
    generated = generate_for(config)
    assert "STATUS_CD" in generated.body
    assert "X" in generated.body


def test_codegen_registry_falls_back_to_sql_for_unknown_target():
    config = _config(connector="unknown")
    generated = generate_for(config)
    assert generated.path.endswith(".sql")
    assert "INSERT INTO" in generated.body.upper()
