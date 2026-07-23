"""Native connector for a local/standalone PySpark session.

Requires the `pyspark` extra:
    pip install "migration-framework[pyspark]"

Use this when the source or target is a Spark table, a Delta path, or any
location reachable through `SparkSession.table()` / `DataFrame.write.saveAsTable()`.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from .base import ColumnInfo, Connector, TableSchema


def _canonical_type(spark_type_name: str) -> str:
    name = spark_type_name.upper().split("(")[0].removesuffix("TYPE")
    mapping: dict[str, str] = {
        "STRING": "string",
        "VARCHAR": "string",
        "CHAR": "string",
        "INT": "integer",
        "INTEGER": "integer",
        "BIGINT": "integer",
        "SMALLINT": "integer",
        "TINYINT": "integer",
        "LONG": "integer",
        "FLOAT": "float",
        "DOUBLE": "float",
        "DECIMAL": "float",
        "BOOLEAN": "boolean",
        "BOOL": "boolean",
        "DATE": "date",
        "TIMESTAMP": "timestamp",
    }
    return mapping.get(name, "other")


class PySparkConnector(Connector):
    """Connector backed by a SparkSession."""

    def __init__(
        self,
        app_name: str = "migration-framework",
        master: str = "local[*]",
        config: dict[str, str] | None = None,
        spark: Any | None = None,
        format: str | None = None,
        path: str | None = None,
    ):
        import pyspark.sql

        self._SparkSession = pyspark.sql.SparkSession
        self._Row = pyspark.sql.Row

        self._spark = spark
        self._app_name = app_name
        self._master = master
        self._extra_config = config or {}
        self._format = format
        self._path = path

    def _session(self) -> Any:
        if self._spark is None:
            builder = self._SparkSession.builder.appName(self._app_name).master(self._master)
            for key, value in self._extra_config.items():
                builder = builder.config(key, value)
            self._spark = builder.getOrCreate()
        return self._spark

    def _read_df(self, table: str):
        spark = self._session()
        if self._format and self._path:
            return spark.read.format(self._format).load(self._path)
        return spark.table(table)

    def get_schema(self, table: str, sample_size: int = 50) -> TableSchema:
        df = self._read_df(table)
        columns = [
            ColumnInfo(
                name=f.name,
                canonical_type=_canonical_type(f.dataType.simpleString()),
                native_type=f.dataType.simpleString(),
                nullable=f.nullable,
            )
            for f in df.schema.fields
        ]
        sample_rows = [r.asDict() for r in df.limit(sample_size).collect()]
        return TableSchema(name=table, columns=columns, sample_rows=sample_rows)

    def read_rows(self, table: str, columns: Iterable[str] | None = None) -> Iterator[dict[str, Any]]:
        df = self._read_df(table)
        if columns:
            df = df.select(*list(columns))
        for row in df.toLocalIterator():
            yield row.asDict()

    def write_rows(self, table: str, rows: Iterable[dict[str, Any]], mode: str = "append") -> int:
        rows = list(rows)
        if not rows:
            return 0
        spark = self._session()
        # Build a DataFrame with the exact column order of the first row.
        rdd = spark.sparkContext.parallelize(rows)
        df = spark.read.json(rdd)
        # Re-project to the keys of the first row so the schema matches.
        ordered = [df[k] for k in rows[0].keys()]
        df = df.select(*ordered)
        df.write.mode(mode).saveAsTable(table)
        return len(rows)

    def row_count(self, table: str) -> int:
        return self._read_df(table).count()
