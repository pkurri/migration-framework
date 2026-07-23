"""The job config: everything that's specific to one migration, and nothing else.

This is what discovery + the auto-mapper + a human (when needed) produce
together, and it's the only input the engine needs to actually run a job.
Same shape no matter which two systems are involved - only the `connector`
and `connection` values change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class ColumnMapping:
    target: str
    source: str | None = None
    trim: bool = False
    cast: str | None = None  # date | timestamp | int | float | string | bool
    default: Any = None
    literal_null: str | None = None
    derived: dict[str, Any] | None = None  # {"when": [{"condition": str, "then": Any}], "otherwise": Any}
    matched_by: str = "manual"  # auto | human_confirmed | human_defined | manual

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ColumnMapping":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in vars(self).items() if v not in (None, False) or k == "target"}
        return d


@dataclass
class JoinFilter:
    column: str  # column on the join table (or, with via_table set, on via_table)
    equals: Any
    via_table: str | None = None
    via_join_on: dict[str, str] | None = None  # {"left": col-on-join-table, "right": col-on-via_table}
    via_connector: str | None = None
    via_connection: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JoinFilter":
        return cls(**d)


@dataclass
class JoinSpec:
    alias: str
    table: str
    join_on: dict[str, str]  # {"left": col-on-source, "right": col-on-this-table}
    mode: str = "semi"  # "semi" filters source rows only; "enrich" merges columns in as f"{alias}.{col}"
    filter: JoinFilter | None = None
    select: list[str] | None = None
    connector: str | None = None
    connection: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JoinSpec":
        d = dict(d)
        if d.get("filter"):
            d["filter"] = JoinFilter.from_dict(d["filter"])
        return cls(**d)


@dataclass
class DateCutoff:
    column: str
    on_or_after: str


@dataclass
class SourceSpec:
    connector: str
    connection: dict[str, Any]
    table: str
    joins: list[JoinSpec] = field(default_factory=list)
    date_cutoff: DateCutoff | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceSpec":
        d = dict(d)
        d["joins"] = [JoinSpec.from_dict(j) for j in d.get("joins", [])]
        if d.get("date_cutoff"):
            d["date_cutoff"] = DateCutoff(**d["date_cutoff"])
        return cls(**d)


@dataclass
class TargetSpec:
    connector: str
    connection: dict[str, Any]
    table: str
    mode: str = "append"
    pre_actions: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TargetSpec":
        return cls(**d)


@dataclass
class AuditColumn:
    name: str
    generator: str = "null"  # batch_id | now | null

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AuditColumn":
        return cls(**d)


@dataclass
class ValidationSpec:
    expected_column_count: int | None = None
    reconcile_row_count: bool = True


@dataclass
class MigrationConfig:
    job_name: str
    source: SourceSpec
    target: TargetSpec
    columns: list[ColumnMapping]
    audit_columns: list[AuditColumn] = field(default_factory=list)
    validation: ValidationSpec = field(default_factory=ValidationSpec)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MigrationConfig":
        return cls(
            job_name=d["job_name"],
            source=SourceSpec.from_dict(d["source"]),
            target=TargetSpec.from_dict(d["target"]),
            columns=[ColumnMapping.from_dict(c) for c in d["columns"]],
            audit_columns=[AuditColumn.from_dict(a) for a in d.get("audit_columns", [])],
            validation=ValidationSpec(**d.get("validation", {})),
        )

    @classmethod
    def load(cls, path: str) -> "MigrationConfig":
        with open(path, "r") as f:
            return cls.from_dict(yaml.safe_load(f))

    def to_dict(self) -> dict[str, Any]:
        import dataclasses

        def conv(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj):
                return {k: conv(v) for k, v in vars(obj).items() if v is not None}
            if isinstance(obj, list):
                return [conv(v) for v in obj]
            return obj

        return conv(self)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)
