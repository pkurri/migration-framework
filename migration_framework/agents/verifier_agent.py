"""Agent that challenges high-confidence mapping proposals before they are auto-accepted.

The verifier's job is to argue against each proposed match. If it can find a
credible objection, the column is downgraded from `auto` to `flagged` so a
person decides. If it cannot, the match sticks.
"""

from __future__ import annotations

import re

from ..mapper import MappingCandidate, MappingProposal
from .base import Agent, AgentContext, AgentResult


class VerifierAgent(Agent):
    """Attempts to disprove each high-confidence mapping proposal."""

    def run(self, context: AgentContext) -> AgentResult:
        raise NotImplementedError


class LocalVerifierAgent(VerifierAgent):
    """Deterministic verifier using structured objections.

    It objects when:
    - the source column's sample values do not look compatible with the target type,
    - another unclaimed target column has a strong name match to the same source,
    - the confidence is dominated by ordinal position rather than name/type/shape,
    - the source column name is generically numbered and there is no strong
      corroborating evidence (prevents silent guesses on `COL_01` vs `COL_02`).
    """

    def __init__(self, shape_tolerance: float = 0.6, name_floor: float = 0.25, ambiguity_margin: float = 0.05):
        self.shape_tolerance = shape_tolerance
        self.name_floor = name_floor
        self.ambiguity_margin = ambiguity_margin

    def _is_generic_name(self, name: str) -> bool:
        """Detect names like COL_01, COLUMN_1, FIELD_02, PO_HDR_COL_01."""
        return bool(re.search(r"(?:^|_)(?:col|column|field|attr|f|c)_?\d+$", name, re.IGNORECASE))

    def _objections_for(
        self,
        proposal: MappingProposal,
        target_name: str,
        candidate: MappingCandidate,
    ) -> list[str]:
        objections: list[str] = []

        if candidate.shape_score < self.shape_tolerance:
            objections.append(
                f"sample values do not look like target type (shape score {candidate.shape_score:.0%})"
            )

        # Is another target column a stronger name match to this same source?
        for other in proposal.columns:
            if other.target_column == target_name:
                continue
            for cand in other.candidates:
                if (
                    cand.source_column == candidate.source_column
                    and cand.name_score > candidate.name_score
                    and cand.name_score > 0.5
                ):
                    objections.append(
                        f"{other.target_column!r} has a stronger name match to {candidate.source_column!r}"
                    )
                    break

        # Generic source columns cannot be reliably distinguished from each other
        # when multiple of them sit at the top of the candidate list.
        if self._is_generic_name(candidate.source_column):
            if candidate.name_score < 0.5 and candidate.shape_score < 0.85:
                objections.append(
                    f"source name {candidate.source_column!r} is generic and evidence is weak"
                )
            else:
                generic_alternatives = [
                    cand
                    for col in proposal.columns
                    for cand in col.candidates[:3]
                    if cand is not candidate
                    and self._is_generic_name(cand.source_column)
                    and cand.confidence >= candidate.confidence - self.ambiguity_margin
                ]
                if generic_alternatives:
                    objections.append(
                        f"source name {candidate.source_column!r} is generic and "
                        f"indistinguishable from {generic_alternatives[0].source_column!r}"
                    )

        # Confidence must come from more than ordinal position.
        if candidate.name_score < self.name_floor and candidate.shape_score < 0.75:
            objections.append("match relies almost entirely on position, not name or data shape")

        return objections

    def run(self, context: AgentContext) -> AgentResult:
        proposal: MappingProposal = context.candidate_proposals["mapping_proposal"]
        changed = 0
        reasoning: list[str] = []

        for col in proposal.columns:
            if col.status != "auto" or not col.best:
                continue
            objections = self._objections_for(proposal, col.target_column, col.best)
            if objections:
                col.status = "flagged"
                col.reason = "verification failed: " + "; ".join(objections)
                changed += 1
                reasoning.append(
                    f"{col.target_column} -> {col.best.source_column}: {col.reason}"
                )

        return AgentResult(
            data=proposal,
            reasoning=reasoning or ["No credible objections to the proposed auto-matches."],
            confidence=1.0 if changed == 0 else 1.0 - (changed / len(proposal.columns)),
        )
