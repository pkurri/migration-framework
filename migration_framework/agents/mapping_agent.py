"""Agent that proposes a column mapping between source and target schemas.

The default `LocalMappingAgent` does not require an external LLM. It performs
the kind of reasoning a person would do - name similarity, type compatibility,
data-shape checks, and ordinal-position clues - and returns a ranked list of
candidates with an explanation for each proposal.

An LLM-backed subclass only needs to override `run()` and return the same
`AgentResult` shape.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from ..connectors.base import ColumnInfo, TableSchema
from ..mapper import ColumnProposal, MappingCandidate, MappingProposal
from .base import Agent, AgentContext, AgentResult


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
    "hdr": "header",
    "dtl": "detail",
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


def _looks_like(value: Any, canonical_type: str) -> bool:
    text = str(value).strip()
    if text == "" or text.lower() == "none":
        return True
    if canonical_type in ("date", "timestamp"):
        return bool(_DATE_RE.match(text))
    if canonical_type == "integer":
        return bool(_INT_RE.match(text))
    if canonical_type == "float":
        return bool(_FLOAT_RE.match(text) or _INT_RE.match(text))
    if canonical_type == "boolean":
        return text.lower() in _BOOL_VALUES
    return True


def _shape_score(sample_values: list[Any], target_type: str) -> float:
    values = [v for v in sample_values if v is not None]
    if not values:
        return 0.5
    matches = sum(1 for v in values if _looks_like(v, target_type))
    return matches / len(values)


def _normalize_name(name: str) -> tuple[str, list[str]]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    spaced = re.sub(r"[^a-zA-Z0-9]+", " ", spaced).lower()
    raw_tokens = [t for t in spaced.split() if t]
    expanded = [ABBREVIATIONS.get(t, t) for t in raw_tokens]
    return " ".join(raw_tokens), expanded


def _name_score(a: str, b: str) -> float:
    norm_a, tokens_a = _normalize_name(a)
    norm_b, tokens_b = _normalize_name(b)
    seq_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()
    set_a, set_b = set(tokens_a), set(tokens_b)
    jaccard = len(set_a & set_b) / len(set_a | set_b) if (set_a | set_b) else 0.0
    return 0.5 * seq_ratio + 0.5 * jaccard


def _type_score(a: str, b: str) -> float:
    if a == b:
        return 1.0
    return _TYPE_COMPATIBILITY.get((a, b), 0.2)


class MappingAgent(Agent):
    """Proposes how target columns map to source columns."""

    def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError


class LocalMappingAgent(MappingAgent):
    """Deterministic mapping agent that uses structured reasoning.

    It treats the column list order as a weak clue: if a target column has no
    name match but the source column at the same ordinal position has the right
    type and data shape, it is flagged as a *likely* (not auto-accepted) match.
    This is how generically-numbered columns such as `PO_HDR_COL_01` can be
    surfaced to a human without being silently guessed.
    """

    def __init__(
        self,
        auto_accept_threshold: float = AUTO_ACCEPT_THRESHOLD,
        ambiguity_margin: float = AMBIGUITY_MARGIN,
    ):
        self.auto_accept_threshold = auto_accept_threshold
        self.ambiguity_margin = ambiguity_margin

    def _score_pair(
        self,
        source_col: ColumnInfo,
        target_col: ColumnInfo,
        sample_rows: list[dict[str, Any]],
        source_index: int,
        target_index: int,
    ) -> MappingCandidate:
        n_score = _name_score(source_col.name, target_col.name)
        t_score = _type_score(source_col.canonical_type, target_col.canonical_type)
        values = [row.get(source_col.name) for row in sample_rows]
        s_score = _shape_score(values, target_col.canonical_type)

        # Ordinal-position bonus when both columns sit at the same index and
        # there is at least a token/type clue to support it.
        position_bonus = 0.0
        if source_index == target_index and source_index >= 0:
            if n_score > 0.1 or t_score >= 0.85:
                position_bonus = 0.05

        confidence = 0.5 * n_score + 0.3 * t_score + 0.2 * s_score + position_bonus

        reasons: list[str] = []
        if n_score >= 0.5:
            reasons.append(f"name similarity {n_score:.0%}")
        if t_score >= 0.85:
            reasons.append("types are compatible")
        if s_score >= 0.75:
            reasons.append(f"sample values look like {target_col.canonical_type}")
        if position_bonus:
            reasons.append("same ordinal position as target")
        if not reasons:
            reasons.append("weak or no match")

        return MappingCandidate(
            source_column=source_col.name,
            confidence=round(min(confidence, 1.0), 4),
            name_score=round(n_score, 4),
            type_score=round(t_score, 4),
            shape_score=round(s_score, 4),
            reasoning="; ".join(reasons),
        )

    def _candidate_for_target(
        self,
        target_col: ColumnInfo,
        target_index: int,
        source_schema: TableSchema,
    ) -> list[MappingCandidate]:
        candidates: list[MappingCandidate] = []
        for i, source_col in enumerate(source_schema.columns):
            candidate = self._score_pair(
                source_col,
                target_col,
                source_schema.sample_rows,
                i,
                target_index,
            )
            candidates.append(candidate)
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def run(self, context: AgentContext) -> AgentResult:
        source_schema = context.source_schema
        target_schema = context.target_schema
        if source_schema is None or target_schema is None:
            raise ValueError("MappingAgent requires source and target schemas in context")

        all_candidates: list[tuple[float, str, str, MappingCandidate]] = []
        for target_index, target_col in enumerate(target_schema.columns):
            candidates = self._candidate_for_target(target_col, target_index, source_schema)
            for candidate in candidates:
                all_candidates.append((candidate.confidence, target_col.name, candidate.source_column, candidate))

        all_candidates.sort(key=lambda x: x[0], reverse=True)

        candidates_by_target: dict[str, list[MappingCandidate]] = {
            t.name: [] for t in target_schema.columns
        }
        for _, target_name, _source_name, candidate in all_candidates:
            candidates_by_target[target_name].append(candidate)
        for cands in candidates_by_target.values():
            cands.sort(key=lambda c: c.confidence, reverse=True)

        claimed_sources: set[str] = set()
        assignment: dict[str, str] = {}
        for confidence, target_name, source_name, _candidate in all_candidates:
            if confidence < self.auto_accept_threshold:
                continue
            if target_name in assignment or source_name in claimed_sources:
                continue
            assignment[target_name] = source_name
            claimed_sources.add(source_name)

        proposals: list[ColumnProposal] = []
        for target_col in target_schema.columns:
            candidates = candidates_by_target[target_col.name][:3]
            chosen_source = assignment.get(target_col.name)

            if not candidates or candidates[0].confidence < self.auto_accept_threshold:
                status, reason = "flagged", "no confident match"
            elif chosen_source != candidates[0].source_column:
                status, reason = (
                    "flagged",
                    f"best match {candidates[0].source_column!r} was already claimed by another column",
                )
            elif len(candidates) > 1 and round(
                candidates[0].confidence - candidates[1].confidence, 4
            ) <= self.ambiguity_margin:
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

        proposal = MappingProposal(columns=proposals)
        return AgentResult(
            data=proposal,
            reasoning=[
                f"Proposed {len(proposal.auto_mapped)} auto-matches and flagged {len(proposal.flagged)} columns for human review."
            ],
            confidence=1.0 if not proposal.flagged else len(proposal.auto_mapped) / len(proposal.columns),
        )
