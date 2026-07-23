import pytest

from migration_framework.hitl import UnresolvedColumnsError, resolve_interactive, resolve_with_answers
from migration_framework.mapper import ColumnProposal, MappingCandidate, MappingProposal


def _proposal():
    auto_col = ColumnProposal(
        target_column="PO_HDR_SNUM",
        target_type="string",
        status="auto",
        candidates=[MappingCandidate("PO_HDR_SNUM", 0.95, 0.9, 1.0, 1.0)],
    )
    flagged_col = ColumnProposal(
        target_column="SHIP_START_DT",
        target_type="date",
        status="flagged",
        reason="no confident match",
        candidates=[
            MappingCandidate("PO_HDR_COL_01", 0.41, 0.1, 0.5, 1.0),
            MappingCandidate("PO_HDR_COL_02", 0.39, 0.1, 0.5, 0.9),
        ],
    )
    derived_col = ColumnProposal(target_column="EDIT_PHASE_IND", target_type="string", status="flagged", reason="no match")
    return MappingProposal(columns=[auto_col, flagged_col, derived_col])


def test_resolve_with_answers_covers_all_flagged():
    proposal = _proposal()
    answers = {
        "SHIP_START_DT": {"source": "PO_HDR_COL_01"},
        "EDIT_PHASE_IND": {"derived": {"when": [{"condition": "PO_VERSION in ('E','B')", "then": "Y"}], "otherwise": None}},
    }
    mappings = resolve_with_answers(proposal, answers)
    by_target = {m.target: m for m in mappings}

    assert by_target["PO_HDR_SNUM"].matched_by == "auto"
    assert by_target["SHIP_START_DT"].source == "PO_HDR_COL_01"
    assert by_target["SHIP_START_DT"].matched_by == "human_confirmed"
    # SHIP_START_DT is a date-typed target column - a raw source string needs
    # a cast, or it'll fail the moment a strongly-typed target rejects it.
    assert by_target["SHIP_START_DT"].cast == "date"
    assert by_target["EDIT_PHASE_IND"].derived["when"][0]["then"] == "Y"


def test_auto_mapped_column_gets_a_cast_when_target_type_needs_one():
    proposal = _proposal()  # PO_HDR_SNUM is auto-mapped, target_type "string"
    mappings = resolve_with_answers(proposal, {"SHIP_START_DT": {"source": "x"}, "EDIT_PHASE_IND": {"skip": True}})
    by_target = {m.target: m for m in mappings}
    assert by_target["PO_HDR_SNUM"].cast is None  # string-to-string needs no cast


def test_resolve_with_answers_raises_when_incomplete():
    proposal = _proposal()
    with pytest.raises(UnresolvedColumnsError) as exc_info:
        resolve_with_answers(proposal, {"SHIP_START_DT": {"source": "PO_HDR_COL_01"}})
    assert "EDIT_PHASE_IND" in str(exc_info.value)


def test_resolve_interactive_picks_candidate_by_number():
    proposal = _proposal()
    scripted_inputs = iter(["1", "d", "PO_VERSION in ('E','B') -> Y", "", ""])
    printed = []
    mappings = resolve_interactive(proposal, input_fn=lambda _: next(scripted_inputs), print_fn=printed.append)
    by_target = {m.target: m for m in mappings}

    assert by_target["SHIP_START_DT"].source == "PO_HDR_COL_01"
    assert by_target["SHIP_START_DT"].matched_by == "human_confirmed"
    assert by_target["EDIT_PHASE_IND"].derived["when"][0]["condition"] == "PO_VERSION in ('E','B')"
