import datetime

from sqlalchemy import Column, Date, DateTime, Float, MetaData, String, Table, create_engine, select

from migration_framework.config import (
    AuditColumn,
    ColumnMapping,
    DateCutoff,
    MigrationConfig,
    SourceSpec,
    TargetSpec,
    ValidationSpec,
)
from migration_framework.engine import run_migration


def _make_source_db(path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    table = Table(
        "legacy_orders",
        metadata,
        Column("ORDER_ID", String, primary_key=True),
        Column("ORDER_DT", String),
        Column("CUST_NUM", String),
        Column("AMT", Float),
        Column("STATUS_CD", String),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            table.insert(),
            [
                {"ORDER_ID": " O1 ", "ORDER_DT": "2022-01-05", "CUST_NUM": "C100", "AMT": 12.5, "STATUS_CD": "A"},
                {"ORDER_ID": "O2", "ORDER_DT": "2022-01-06", "CUST_NUM": "C101", "AMT": 40.0, "STATUS_CD": "X"},
                {"ORDER_ID": "O3", "ORDER_DT": "2021-01-01", "CUST_NUM": "C102", "AMT": 5.0, "STATUS_CD": "A"},
            ],
        )
    engine.dispose()


def _make_target_db(path) -> Table:
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    table = Table(
        "orders_fact",
        metadata,
        Column("order_id", String, primary_key=True),
        Column("order_date", Date),
        Column("customer_number", String),
        Column("amount", Float),
        Column("is_cancelled", String),
        Column("batch_id", String),
        Column("etl_load_ts", DateTime),
    )
    metadata.create_all(engine)
    engine.dispose()
    return table


def _build_config(source_path, target_path) -> MigrationConfig:
    return MigrationConfig(
        job_name="orders_demo",
        source=SourceSpec(
            connector="sqlalchemy",
            connection={"connection_url": f"sqlite:///{source_path}"},
            table="legacy_orders",
            date_cutoff=DateCutoff(column="ORDER_DT", on_or_after="2022-01-01"),
        ),
        target=TargetSpec(
            connector="sqlalchemy",
            connection={"connection_url": f"sqlite:///{target_path}"},
            table="orders_fact",
            mode="append",
        ),
        columns=[
            ColumnMapping(target="order_id", source="ORDER_ID", trim=True, matched_by="auto"),
            ColumnMapping(target="order_date", source="ORDER_DT", cast="date", matched_by="auto"),
            ColumnMapping(target="customer_number", source="CUST_NUM", trim=True, matched_by="auto"),
            ColumnMapping(target="amount", source="AMT", matched_by="auto"),
            ColumnMapping(
                target="is_cancelled",
                derived={"when": [{"condition": "STATUS_CD == 'X'", "then": "Y"}], "otherwise": "N"},
                matched_by="human_defined",
            ),
        ],
        audit_columns=[
            AuditColumn(name="batch_id", generator="batch_id"),
            AuditColumn(name="etl_load_ts", generator="now"),
        ],
        validation=ValidationSpec(expected_column_count=7),
    )


def test_end_to_end_migration(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _make_source_db(source_path)
    _make_target_db(target_path)

    config = _build_config(source_path, target_path)
    run_ts = datetime.datetime(2024, 3, 15, 10, 30, 0)

    result = run_migration(config, run_timestamp=run_ts)

    assert result.rows_read == 2  # the 2021 row is excluded by the date cutoff
    assert result.rows_written == 2
    assert result.target_row_count_before == 0
    assert result.target_row_count_after == 2
    assert result.reconciled is True

    engine = create_engine(f"sqlite:///{target_path}")
    metadata = MetaData()
    table = Table("orders_fact", metadata, autoload_with=engine)
    with engine.connect() as conn:
        rows = {row.order_id: row for row in conn.execute(select(table)).mappings()}

    assert set(rows) == {"O1", "O2"}
    assert rows["O1"]["order_date"] == datetime.date(2022, 1, 5)
    assert rows["O1"]["is_cancelled"] == "N"
    assert rows["O2"]["is_cancelled"] == "Y"
    assert rows["O1"]["batch_id"] == "20240315"


def test_dry_run_writes_nothing(tmp_path):
    source_path = tmp_path / "source.db"
    target_path = tmp_path / "target.db"
    _make_source_db(source_path)
    _make_target_db(target_path)

    config = _build_config(source_path, target_path)
    result = run_migration(config, dry_run=True)

    assert result.dry_run is True
    assert result.rows_written == 0

    engine = create_engine(f"sqlite:///{target_path}")
    metadata = MetaData()
    table = Table("orders_fact", metadata, autoload_with=engine)
    with engine.connect() as conn:
        count = conn.execute(select(table)).all()
    assert count == []
