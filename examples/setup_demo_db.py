"""Creates two throwaway SQLite databases standing in for a legacy system and
a new one, with deliberately mismatched column names/types - so `migrate
discover` has real work to do. Run once before following the README quickstart.
"""

from sqlalchemy import Column, Date, DateTime, Float, MetaData, String, Table, create_engine

HERE = __import__("pathlib").Path(__file__).parent


def build_source(path) -> None:
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
                {"ORDER_ID": "O1001", "ORDER_DT": "2024-01-05", "CUST_NUM": "C500", "AMT": 129.99, "STATUS_CD": "A"},
                {"ORDER_ID": "O1002", "ORDER_DT": "2024-01-06", "CUST_NUM": "C501", "AMT": 42.50, "STATUS_CD": "X"},
                {"ORDER_ID": "O1003", "ORDER_DT": "2024-01-07", "CUST_NUM": "C502", "AMT": 76.00, "STATUS_CD": "A"},
            ],
        )
    engine.dispose()
    print(f"wrote {path}")


def build_target(path) -> None:
    engine = create_engine(f"sqlite:///{path}")
    metadata = MetaData()
    Table(
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
    print(f"wrote {path}")


if __name__ == "__main__":
    build_source(HERE / "source.db")
    build_target(HERE / "target.db")
