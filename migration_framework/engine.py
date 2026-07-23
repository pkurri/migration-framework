"""Runs an actual migration from a finished MigrationConfig.

This is the part that never changes between jobs: same code whether the
mapping came from the auto-mapper, a human, or both, and regardless of which
two systems are involved - it only ever talks to them through the Connector
interface.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from .conditions import Condition
from .config import ColumnMapping, DateCutoff, JoinFilter, JoinSpec, MigrationConfig, SourceSpec
from .registry import build_connector

logger = logging.getLogger("migration_framework")


class ValidationError(RuntimeError):
    pass


class ReconciliationError(RuntimeError):
    pass


@dataclass
class RunResult:
    job_name: str
    rows_read: int
    rows_written: int
    target_row_count_before: int | None = None
    target_row_count_after: int | None = None
    reconciled: bool | None = None
    dry_run: bool = False


def _norm(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


def _apply_join_filter(join_rows: list[dict[str, Any]], filt: JoinFilter, source: SourceSpec) -> list[dict[str, Any]]:
    if filt.via_table:
        via_connector = build_connector(filt.via_connector or source.connector, filt.via_connection or source.connection)
        via_rows = list(via_connector.read_rows(filt.via_table))
        valid_right_values = {
            row.get(filt.via_join_on["right"])
            for row in via_rows
            if _norm(row.get(filt.column)) == _norm(filt.equals)
        }
        left_col = filt.via_join_on["left"]
        return [row for row in join_rows if row.get(left_col) in valid_right_values]
    return [row for row in join_rows if _norm(row.get(filt.column)) == _norm(filt.equals)]


def _apply_join(rows: list[dict[str, Any]], join: JoinSpec, source: SourceSpec) -> list[dict[str, Any]]:
    join_connector = build_connector(join.connector or source.connector, join.connection or source.connection)
    join_rows = list(join_connector.read_rows(join.table))

    if join.filter:
        join_rows = _apply_join_filter(join_rows, join.filter, source)

    left_col, right_col = join.join_on["left"], join.join_on["right"]

    if join.mode == "semi":
        valid_keys = {row.get(right_col) for row in join_rows}
        return [row for row in rows if row.get(left_col) in valid_keys]

    if join.mode == "enrich":
        select_cols = join.select or (list(join_rows[0].keys()) if join_rows else [])
        by_key: dict[Any, dict[str, Any]] = {}
        for row in join_rows:
            by_key.setdefault(row.get(right_col), row)
        merged_rows = []
        for row in rows:
            match = by_key.get(row.get(left_col))
            merged = dict(row)
            for col in select_cols:
                merged[f"{join.alias}.{col}"] = match.get(col) if match else None
            merged_rows.append(merged)
        return merged_rows

    raise ValueError(f"Unknown join mode {join.mode!r} for join {join.alias!r}")


def _apply_date_cutoff(rows: list[dict[str, Any]], cutoff: DateCutoff) -> list[dict[str, Any]]:
    cutoff_date = datetime.date.fromisoformat(cutoff.on_or_after)

    def parse(value: Any) -> datetime.date | None:
        if value is None:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        try:
            return datetime.date.fromisoformat(str(value)[:10])
        except ValueError:
            return None

    kept = []
    for row in rows:
        parsed = parse(row.get(cutoff.column))
        if parsed is not None and parsed >= cutoff_date:
            kept.append(row)
    return kept


def read_source_rows(source: SourceSpec) -> list[dict[str, Any]]:
    connector = build_connector(source.connector, source.connection)
    rows = list(connector.read_rows(source.table))

    for join in source.joins:
        rows = _apply_join(rows, join, source)

    if source.date_cutoff:
        rows = _apply_date_cutoff(rows, source.date_cutoff)

    return rows


def _get_value(row: dict[str, Any], source_ref: str) -> Any:
    if source_ref in row:
        return row[source_ref]
    bare = source_ref.split(".")[-1]
    return row.get(bare)


def _cast(value: Any, cast_type: str) -> Any:
    if value is None:
        return None
    if cast_type == "date":
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return datetime.date.fromisoformat(str(value)[:10])
    if cast_type == "timestamp":
        if isinstance(value, datetime.datetime):
            return value
        text = str(value)
        try:
            return datetime.datetime.fromisoformat(text)
        except ValueError:
            return datetime.datetime.fromisoformat(text[:19])
    if cast_type in ("int", "integer"):
        return int(value)
    if cast_type == "float":
        return float(value)
    if cast_type in ("bool", "boolean"):
        return str(value).strip().lower() in ("1", "true", "y", "yes")
    if cast_type in ("string", "str"):
        return str(value)
    raise ValueError(f"Unknown cast type {cast_type!r}")


def apply_column_mapping(row: dict[str, Any], mapping: ColumnMapping) -> Any:
    if mapping.derived is not None:
        for rule in mapping.derived.get("when", []):
            if Condition.parse(rule["condition"]).evaluate(row):
                return rule["then"]
        return mapping.derived.get("otherwise")

    if mapping.literal_null is not None:
        return None

    value = _get_value(row, mapping.source) if mapping.source else None

    if mapping.trim and isinstance(value, str):
        value = value.strip()
    if value is None and mapping.default is not None:
        value = mapping.default
    if mapping.cast and value is not None:
        value = _cast(value, mapping.cast)
    return value


def _generate_audit_value(generator: str, run_timestamp: datetime.datetime) -> Any:
    if generator == "batch_id":
        return run_timestamp.strftime("%Y%m%d")
    if generator == "now":
        return run_timestamp
    if generator == "null":
        return None
    raise ValueError(f"Unknown audit column generator {generator!r}")


def project_rows(
    rows: Iterable[dict[str, Any]], config: MigrationConfig, run_timestamp: datetime.datetime
) -> list[dict[str, Any]]:
    projected = []
    for row in rows:
        out = {mapping.target: apply_column_mapping(row, mapping) for mapping in config.columns}
        for audit in config.audit_columns:
            out[audit.name] = _generate_audit_value(audit.generator, run_timestamp)
        projected.append(out)
    return projected


def validate_columns(config: MigrationConfig, projected_rows: list[dict[str, Any]]) -> None:
    expected = config.validation.expected_column_count
    if expected is None:
        return
    actual_columns = {m.target for m in config.columns} | {a.name for a in config.audit_columns}
    if len(actual_columns) != expected:
        raise ValidationError(
            f"{config.job_name}: expected {expected} columns, config defines {len(actual_columns)}: "
            f"{sorted(actual_columns)}"
        )


def run_migration(config: MigrationConfig, dry_run: bool = False, run_timestamp: datetime.datetime | None = None) -> RunResult:
    run_timestamp = run_timestamp or datetime.datetime.now()

    logger.info("[%s] reading source rows", config.job_name)
    source_rows = read_source_rows(config.source)

    logger.info("[%s] projecting %d rows onto %d target columns", config.job_name, len(source_rows), len(config.columns))
    projected = project_rows(source_rows, config, run_timestamp)

    validate_columns(config, projected)

    if dry_run:
        logger.info("[%s] dry run: would write %d rows, nothing was written", config.job_name, len(projected))
        return RunResult(job_name=config.job_name, rows_read=len(source_rows), rows_written=0, dry_run=True)

    target_connector = build_connector(config.target.connector, config.target.connection)
    if config.target.pre_actions and hasattr(target_connector, "execute"):
        target_connector.execute(config.target.pre_actions)

    before = target_connector.row_count(config.target.table)
    written = target_connector.write_rows(config.target.table, projected, mode=config.target.mode)
    after = target_connector.row_count(config.target.table)

    result = RunResult(
        job_name=config.job_name,
        rows_read=len(source_rows),
        rows_written=written,
        target_row_count_before=before,
        target_row_count_after=after,
    )

    if config.validation.reconcile_row_count:
        expected_after = written if config.target.mode == "overwrite" else before + written
        result.reconciled = after == expected_after
        if not result.reconciled:
            raise ReconciliationError(
                f"{config.job_name}: expected {expected_after} rows in target after the write, found {after}"
            )

    logger.info("[%s] wrote %d rows (target now has %d)", config.job_name, written, after)
    return result
