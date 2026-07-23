"""The human-in-the-loop step: turns a MappingProposal's flagged columns into
a short list of questions, and turns the answers into ColumnMapping entries.

Two ways to answer:
  - interactively, at a terminal (`resolve_interactive`)
  - by supplying a pre-filled answers dict (`resolve_with_answers`) - this is
    what lets the same resolution step be driven by a script, a test, or a
    different front end (a web form, a Slack message) instead of a terminal.
Either way produces the exact same output: a plain list of ColumnMapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .conditions import Condition, ConditionError
from .config import ColumnMapping
from .mapper import ColumnProposal, MappingProposal


class UnresolvedColumnsError(RuntimeError):
    """Raised in non-interactive mode when a flagged column has no answer supplied."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(
            "No answer supplied for flagged column(s): "
            + ", ".join(missing)
            + ". Provide an entry for each in the answers file, or run interactively."
        )


@dataclass
class DerivedAnswer:
    when: list[dict[str, Any]]
    otherwise: Any = None


def _validate_derived(derived: dict[str, Any]) -> dict[str, Any]:
    for rule in derived.get("when", []):
        Condition.parse(rule["condition"])  # raises ConditionError if malformed
    return derived


# Target types that need an explicit cast because the source is read back as
# whatever native type the source system gave it (often a plain string) -
# without this, e.g. a date-shaped string never becomes an actual date and
# fails the moment a strongly-typed target column rejects it.
_CAST_BY_TARGET_TYPE = {"date": "date", "timestamp": "timestamp", "integer": "int", "float": "float", "boolean": "bool"}


def _mapping_for_auto(col: ColumnProposal) -> ColumnMapping:
    return ColumnMapping(
        target=col.target_column,
        source=col.best.source_column,
        cast=_CAST_BY_TARGET_TYPE.get(col.target_type),
        matched_by="auto",
    )


def _mapping_from_answer(target: str, answer: dict[str, Any], target_type: str | None = None) -> ColumnMapping:
    if answer.get("skip"):
        return ColumnMapping(target=target, literal_null="string", matched_by="human_defined")
    if "derived" in answer:
        derived = _validate_derived(answer["derived"])
        return ColumnMapping(target=target, derived=derived, matched_by="human_defined")
    if "source" in answer:
        return ColumnMapping(
            target=target,
            source=answer["source"],
            cast=_CAST_BY_TARGET_TYPE.get(target_type),
            matched_by="human_confirmed",
        )
    raise ValueError(f"Answer for {target!r} must contain one of: source, derived, skip. Got: {answer!r}")


def resolve_with_answers(proposal: MappingProposal, answers: dict[str, dict[str, Any]]) -> list[ColumnMapping]:
    """Non-interactive resolution - the same shape a UI, a test, or an
    automation script would use instead of a terminal prompt."""
    resolved: list[ColumnMapping] = []
    missing: list[str] = []
    for col in proposal.columns:
        if col.status == "auto":
            resolved.append(_mapping_for_auto(col))
            continue
        answer = answers.get(col.target_column)
        if answer is None:
            missing.append(col.target_column)
            continue
        resolved.append(_mapping_from_answer(col.target_column, answer, col.target_type))
    if missing:
        raise UnresolvedColumnsError(missing)
    return resolved


def resolve_interactive(proposal: MappingProposal, input_fn=input, print_fn=print) -> list[ColumnMapping]:
    """Walks a person through only the columns the mapper couldn't resolve on
    its own. Everything else is already decided."""
    total = len(proposal.columns)
    print_fn(f"\n{len(proposal.auto_mapped)} of {total} columns auto-mapped confidently.\n")

    resolved: list[ColumnMapping] = [_mapping_for_auto(c) for c in proposal.auto_mapped]

    if not proposal.flagged:
        return resolved

    print_fn("Needs a decision:")
    for col in proposal.flagged:
        print_fn(f"\n  {col.target_column} ({col.target_type}) — {col.reason}")
        for i, cand in enumerate(col.candidates, start=1):
            print_fn(f"    [{i}] {cand.source_column}   (confidence {cand.confidence:.0%})")
        print_fn("    [d] derived / business-rule column (no source copy)")
        print_fn("    [s] skip - leave this column null")
        print_fn("    or type the exact source column name")

        while True:
            choice = input_fn("  > ").strip()
            if choice.lower() == "s":
                resolved.append(ColumnMapping(target=col.target_column, literal_null="string", matched_by="human_defined"))
                break
            if choice.lower() == "d":
                rules = []
                print_fn("    Enter each rule as 'condition -> value', blank line when done.")
                while True:
                    rule_line = input_fn("    rule> ").strip()
                    if not rule_line:
                        break
                    if "->" not in rule_line:
                        print_fn("    expected 'condition -> value', e.g. \"PO_VERSION in ('E','B') -> Y\"")
                        continue
                    condition_text, value = (p.strip() for p in rule_line.split("->", 1))
                    try:
                        Condition.parse(condition_text)
                    except ConditionError as exc:
                        print_fn(f"    {exc}")
                        continue
                    rules.append({"condition": condition_text, "then": value})
                otherwise = input_fn("    otherwise (blank = null)> ").strip() or None
                resolved.append(
                    ColumnMapping(
                        target=col.target_column,
                        derived={"when": rules, "otherwise": otherwise},
                        matched_by="human_defined",
                    )
                )
                break
            if choice.isdigit() and 1 <= int(choice) <= len(col.candidates):
                source_column = col.candidates[int(choice) - 1].source_column
                resolved.append(
                    ColumnMapping(
                        target=col.target_column,
                        source=source_column,
                        cast=_CAST_BY_TARGET_TYPE.get(col.target_type),
                        matched_by="human_confirmed",
                    )
                )
                break
            if choice:
                resolved.append(
                    ColumnMapping(
                        target=col.target_column,
                        source=choice,
                        cast=_CAST_BY_TARGET_TYPE.get(col.target_type),
                        matched_by="human_confirmed",
                    )
                )
                break
            print_fn("    please choose an option")

    return resolved
