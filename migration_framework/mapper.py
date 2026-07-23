"""Proposes a column mapping between a source and target schema.

This is deliberately not an LLM call: it's plain heuristics (name
similarity, type compatibility, and a look at the actual sample values) so
the framework runs the same way offline, in CI, or anywhere else, without
depending on any particular AI vendor being reachable. An agent/LLM can sit
in front of this later and do a better job on hard cases - see the `hints`
parameter - but the framework works fully without one.

Every target column ends up in one of two buckets: auto-mapped (confident,
unambiguous) or flagged (needs a person). Nothing is ever silently guessed
past the threshold.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from .connectors.base import ColumnInfo, TableSchema

AUTO_ACCEPT_THRESHOLD = 0.72
AMBIGUITY_MARGIN = 0.05

ABBREVIATIONS = {
    "dt": "date",
    "ts": "timestamp",
    "nbr": "number",
    "num": "number",
    "snum": "number",
    "qty": "quantity",
    "amt": "amount",
    "cd": "code",
    "desc": "description",
    "ind": "indicator",
    "id": "identifier",
    "flg": "flag",
    "vnd": "vendor",
    "str": "store",
}

_TYPE_COMPATIBILITY: dict[tuple[str, str], float] = {
    ("string", "string"): 1.0,
    ("integer", "integer"): 1.0,
    ("float", "float"): 1.0,
    ("boolean", "boolean"): 1.0,
    ("date", "date"): 1.0,
    ("timestamp", "timestamp"): 1.0,
    ("integer", "float"): 0.85,
    ("float", "integer"): 0.85,
    ("date", "timestamp"): 0.85,
    ("timestamp", "date"): 0.85,
    ("string", "date"): 0.5,
    ("date", "string"): 0.5,
    ("string", "timestamp"): 0.5,
    ("timestamp", "string"): 0.5,
    ("string", "integer"): 0.4,
    ("integer", "string"): 0.4,
    ("string", "float"): 0.4,
    ("float", "string"): 0.4,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_INT_RE = re.compile(r"^-?\d+$")
_FLOAT_RE = re.compile(r"^-?\d+\.\d+$")
_BOOL_VALUES = {"true", "false", "y", "n", "yes", "no", "0", "1"}


def normalize_name(name: str) -> tuple[str, list[str]]:
    """Returns (normalized string for fuzzy matching, expanded tokens for set overlap)."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[^a-zA-Z0-9]+", " ", spaced).lower()
    raw_tokens = [t for t in spaced.split() if t]
    expanded = [ABBREVIATIONS.get(t, t) for t in raw_tokens]
    return " ".join(raw_tokens), expanded


def name_score(a: str, b: str) -> float:
    norm_a, tokens_a = normalize_name(a)
    norm_b, tokens_b = normalize_name(b)
    seq_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    set_a, set_b = set(tokens_a), set(tokens_b)
    jaccard = len(set_a & set_b) / len(set_a | set_b) if (set_a | set_b) else 0.0
    return 0.5 * seq_ratio + 0.5 * jaccard


def type_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return _TYPE_COMPATIBILITY.get((a, b), 0.2)


def _looks_like(value: Any, canonical_type: str) -> bool:
    text = str(value).strip()
    if text == "" or text.lower() == "none":
        return True  # nulls don't disqualify a match
    if canonical_type in ("date", "timestamp"):
        return bool(_DATE_RE.match(text))
    if canonical_type == "integer":
        return bool(_INT_RE.match(text))
    if canonical_type == "float":
        return bool(_FLOAT_RE.match(text) or _INT_RE.match(text))
    if canonical_type == "boolean":
        return text.lower() in _BOOL_VALUES
    return True  # "string"/"other" accepts anything


def shape_score(sample_values: list[Any], target_type: str) -> float:
    values = [v for v in sample_values if v is not None]
    if not values:
        return 0.5  # no evidence either way
    matches = sum(1 for v in values if _looks_like(v, target_type))
    return matches / len(values)


@dataclass
class MappingCandidate:
    source_column: str
    confidence: float
    name_score: float
    type_score: float
    shape_score: float
    reasoning: str = ""


@dataclass
class ColumnProposal:
    target_column: str
    target_type: str
    status: str  # "auto" or "flagged"
    candidates: list[MappingCandidate] = field(default_factory=list)
    reason: str = ""

    @property
    def best(self) -> MappingCandidate | None:
        return self.candidates[0] if self.candidates else None


@dataclass
class MappingProposal:
    columns: list[ColumnProposal]

    @property
    def auto_mapped(self) -> list[ColumnProposal]:
        return [c for c in self.columns if c.status == "auto"]

    @property
    def flagged(self) -> list[ColumnProposal]:
        return [c for c in self.columns if c.status == "flagged"]


def _score_pair(source_col: ColumnInfo, target_col: ColumnInfo, sample_rows: list[dict[str, Any]]) -> MappingCandidate:
    n_score = name_score(source_col.name, target_col.name)
    t_score = type_score(source_col.canonical_type, target_col.canonical_type)
    values = [row.get(source_col.name) for row in sample_rows]
    s_score = shape_score(values, target_col.canonical_type)
    confidence = 0.5 * n_score + 0.3 * t_score + 0.2 * s_score
    return MappingCandidate(
        source_column=source_col.name,
        confidence=round(confidence, 4),
        name_score=round(n_score, 4),
        type_score=round(t_score, 4),
        shape_score=round(s_score, 4),
    )


def propose_mapping(
    source_schema: TableSchema,
    target_schema: TableSchema,
    auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
    ambiguity_margin: float = AMBIGUITY_MARGIN,
) -> MappingProposal:
    """Score every (source, target) column pair, then greedily assign the
    highest-confidence pairs first so two target columns don't both claim the
    same strong source match."""

    all_scores: list[tuple[float, str, str, MappingCandidate]] = []
    for target_col in target_schema.columns:
        for source_col in source_schema.columns:
            candidate = _score_pair(source_col, target_col, source_schema.sample_rows)
            all_scores.append((candidate.confidence, target_col.name, source_col.name, candidate))
    all_scores.sort(key=lambda x: x[0], reverse=True)

    candidates_by_target: dict[str, list[MappingCandidate]] = {t.name: [] for t in target_schema.columns}
    for _, target_name, _source_name, candidate in all_scores:
        candidates_by_target[target_name].append(candidate)
    for cands in candidates_by_target.values():
        cands.sort(key=lambda c: c.confidence, reverse=True)

    claimed_sources: set[str] = set()
    assignment: dict[str, str] = {}  # target -> source, only for confident+unambiguous+unclaimed
    for confidence, target_name, source_name, _candidate in all_scores:
        if confidence < auto_accept_threshold:
            continue
        if target_name in assignment or source_name in claimed_sources:
            continue
        assignment[target_name] = source_name
        claimed_sources.add(source_name)

    proposals: list[ColumnProposal] = []
    for target_col in target_schema.columns:
        candidates = candidates_by_target[target_col.name][:3]
        chosen_source = assignment.get(target_col.name)

        if not candidates or candidates[0].confidence < auto_accept_threshold:
            status, reason = "flagged", "no confident match"
        elif chosen_source != candidates[0].source_column:
            status, reason = "flagged", f"best match {candidates[0].source_column!r} was already claimed by another column"
        elif len(candidates) > 1 and (candidates[0].confidence - candidates[1].confidence) < ambiguity_margin:
            status, reason = "flagged", "top two candidates are too close to call automatically"
        else:
            status, reason = "auto", ""

        proposals.append(
            ColumnProposal(
                target_column=target_col.name,
                target_type=target_col.canonical_type,
                status=status,
                candidates=candidates,
                reason=reason,
            )
        )

    return MappingProposal(columns=proposals)
