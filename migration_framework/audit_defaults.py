"""Best-guess generator for a target column that's clearly a pipeline
bookkeeping column rather than something copied from the source - so
`discover` doesn't ask a person to map `BATCH_ID` to a source column."""

from __future__ import annotations

DEFAULT_AUDIT_GENERATORS: dict[str, str] = {
    "batch_id": "batch_id",
    "etl_load_ts": "now",
    "etl_updt_ts": "now",
    "src_load_ts": "null",
    "load_ts": "now",
    "created_at": "now",
    "updated_at": "now",
}


def guess_audit_generator(name: str) -> str:
    return DEFAULT_AUDIT_GENERATORS.get(name.lower(), "null")
