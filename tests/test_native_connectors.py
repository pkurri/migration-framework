from unittest.mock import MagicMock, patch

from migration_framework.connectors import DatabricksConnector, SnowflakeConnector
from migration_framework.connectors.base import ColumnInfo


def _make_cursor(rows, description=None):
    cur = MagicMock()
    cur.fetchall.return_value = rows
    cur.fetchone.return_value = (len(rows),) if rows else (0,)
    cur.description = description or [["name"], ["type"], ["kind"], ["null?"]]
    return cur


def _make_conn(cur):
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_snowflake_connector_get_schema():
    rows = [
        ("id", "INTEGER", "COLUMN", "N"),
        ("name", "VARCHAR(100)", "COLUMN", "Y"),
    ]
    sample_rows = [(1, "alice"), (2, "bob")]
    sample_description = [["id"], ["name"]]

    def side_effect(sql):
        if sql.startswith("DESCRIBE"):
            cur.fetchall.return_value = rows
            cur.description = [["name"], ["type"], ["kind"], ["null?"]]
        elif sql.startswith("SELECT"):
            cur.fetchall.return_value = sample_rows
            cur.description = sample_description

    cur = _make_cursor(rows)
    cur.execute.side_effect = side_effect
    conn = _make_conn(cur)

    with patch("snowflake.connector.connect", return_value=conn):
        connector = SnowflakeConnector(account="x", user="u", password="p", database="d", schema="s")
        schema = connector.get_schema("bronze.orders", sample_size=2)

    assert schema.name == "bronze.orders"
    assert schema.columns == [
        ColumnInfo(name="id", canonical_type="integer", native_type="INTEGER", nullable=False),
        ColumnInfo(name="name", canonical_type="string", native_type="VARCHAR(100)", nullable=True),
    ]
    assert len(schema.sample_rows) == 2


def test_databricks_connector_get_schema():
    rows = [
        ("id", "INT", "comment"),
        ("score", "DOUBLE", "comment"),
    ]
    sample_rows = [(1, 99.5)]

    def side_effect(sql):
        if sql.startswith("DESCRIBE"):
            cur.fetchall.return_value = rows
            cur.description = [["col_name"], ["data_type"], ["comment"]]
        elif sql.startswith("SELECT"):
            cur.fetchall.return_value = sample_rows
            cur.description = [["id"], ["score"]]

    cur = _make_cursor(rows)
    cur.execute.side_effect = side_effect
    conn = _make_conn(cur)

    with patch("databricks.sql.connect", return_value=conn):
        connector = DatabricksConnector(
            server_hostname="host", http_path="path", access_token="token", catalog="c", schema="s"
        )
        schema = connector.get_schema("silver.orders", sample_size=1)

    assert schema.name == "silver.orders"
    assert schema.columns == [
        ColumnInfo(name="id", canonical_type="integer", native_type="INT", nullable=True),
        ColumnInfo(name="score", canonical_type="float", native_type="DOUBLE", nullable=True),
    ]


def test_snowflake_connector_write_rows():
    cur = _make_cursor([])
    conn = _make_conn(cur)

    with patch("snowflake.connector.connect", return_value=conn):
        connector = SnowflakeConnector(account="x", user="u", password="p")
        count = connector.write_rows("silver.orders", [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}])

    assert count == 2
    cur.executemany.assert_called_once()
    sql, params = cur.executemany.call_args[0]
    assert "INSERT INTO silver.orders" in sql
    assert "%(id)s" in sql and "%(name)s" in sql
    assert params == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]


def test_databricks_connector_write_rows():
    cur = _make_cursor([])
    conn = _make_conn(cur)

    with patch("databricks.sql.connect", return_value=conn):
        connector = DatabricksConnector(server_hostname="h", http_path="p", access_token="t")
        count = connector.write_rows("gold.orders", [{"id": 1, "name": "alice"}])

    assert count == 1
    cur.executemany.assert_called_once()
    sql, params = cur.executemany.call_args[0]
    assert "INSERT INTO gold.orders" in sql
    assert ":id" in sql and ":name" in sql
    assert params == [{"id": 1, "name": "alice"}]


def test_snowflake_connector_row_count():
    cur = _make_cursor([])
    cur.fetchone.return_value = (42,)
    conn = _make_conn(cur)

    with patch("snowflake.connector.connect", return_value=conn):
        connector = SnowflakeConnector(account="x", user="u", password="p")
        assert connector.row_count("bronze.orders") == 42
    cur.execute.assert_called_with("SELECT COUNT(*) FROM bronze.orders")


def test_databricks_connector_read_rows():
    rows = [(1, "alice"), (2, "bob")]

    def side_effect(sql):
        cur.fetchall.return_value = rows
        cur.description = [["id"], ["name"]]

    cur = _make_cursor(rows)
    cur.execute.side_effect = side_effect
    conn = _make_conn(cur)

    with patch("databricks.sql.connect", return_value=conn):
        connector = DatabricksConnector(server_hostname="h", http_path="p", access_token="t")
        result = list(connector.read_rows("silver.orders", columns=["id", "name"]))

    assert result == [{"id": 1, "name": "alice"}, {"id": 2, "name": "bob"}]
