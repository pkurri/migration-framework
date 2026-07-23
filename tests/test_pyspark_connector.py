import sys
import types
from unittest.mock import MagicMock, patch

from migration_framework.connectors import PySparkConnector
from migration_framework.registry import CONNECTOR_REGISTRY


def _fake_pyspark_module():
    """Build a minimal fake pyspark/sql tree for unit tests."""
    fake = types.ModuleType("pyspark")
    fake_sql = types.ModuleType("pyspark.sql")

    builder = MagicMock()
    session = MagicMock()
    fake_sparksession = MagicMock()
    fake_sparksession.builder = builder
    builder.appName.return_value = builder
    builder.master.return_value = builder
    builder.config.return_value = builder
    builder.getOrCreate.return_value = session

    fake_sql.SparkSession = fake_sparksession
    fake_sql.Row = MagicMock()
    fake.sql = fake_sql
    return fake, fake_sql, session


def test_pyspark_connector_is_registered():
    assert "pyspark" in CONNECTOR_REGISTRY
    assert CONNECTOR_REGISTRY["pyspark"] is PySparkConnector


def test_pyspark_connector_get_schema():
    fake, fake_sql, session = _fake_pyspark_module()
    fake.modules = {"pyspark": fake, "pyspark.sql": fake_sql}

    field = MagicMock()
    field.name = "id"
    field.dataType.simpleString.return_value = "IntegerType()"
    field.nullable = True
    schema = MagicMock()
    schema.fields = [field]
    df = MagicMock()
    df.schema = schema
    row = MagicMock()
    row.asDict.return_value = {"id": 1}
    df.limit.return_value.collect.return_value = [row]
    session.table.return_value = df

    with patch.dict(sys.modules, fake.modules):
        connector = PySparkConnector(spark=session)
        table_schema = connector.get_schema("bronze.orders", sample_size=1)

    assert table_schema.name == "bronze.orders"
    assert table_schema.columns[0].name == "id"
    assert table_schema.columns[0].canonical_type == "integer"
    assert len(table_schema.sample_rows) == 1


def test_pyspark_connector_read_rows():
    fake, fake_sql, session = _fake_pyspark_module()
    fake.modules = {"pyspark": fake, "pyspark.sql": fake_sql}

    df = MagicMock()
    row1 = MagicMock()
    row1.asDict.return_value = {"id": 1}
    row2 = MagicMock()
    row2.asDict.return_value = {"id": 2}
    df.toLocalIterator.return_value = [row1, row2]
    df.select.return_value = df
    session.table.return_value = df

    with patch.dict(sys.modules, fake.modules):
        connector = PySparkConnector(spark=session)
        result = list(connector.read_rows("silver.orders", columns=["id"]))

    assert result == [{"id": 1}, {"id": 2}]
    df.select.assert_called_once_with("id")


def test_pyspark_connector_write_rows():
    fake, fake_sql, session = _fake_pyspark_module()
    fake.modules = {"pyspark": fake, "pyspark.sql": fake_sql}

    sc = MagicMock()
    rdd = MagicMock()
    sc.parallelize.return_value = rdd
    session.sparkContext = sc

    read_df = MagicMock()
    read_df.__getitem__ = lambda self, k: MagicMock()
    session.read.json.return_value = read_df

    writer = MagicMock()
    read_df.select.return_value.write.mode.return_value = writer

    with patch.dict(sys.modules, fake.modules):
        connector = PySparkConnector(spark=session)
        count = connector.write_rows("gold.orders", [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}])

    assert count == 2
    writer.saveAsTable.assert_called_once_with("gold.orders")


def test_pyspark_connector_row_count():
    fake, fake_sql, session = _fake_pyspark_module()
    fake.modules = {"pyspark": fake, "pyspark.sql": fake_sql}

    df = MagicMock()
    df.count.return_value = 100
    session.table.return_value = df

    with patch.dict(sys.modules, fake.modules):
        connector = PySparkConnector(spark=session)
        assert connector.row_count("bronze.orders") == 100
