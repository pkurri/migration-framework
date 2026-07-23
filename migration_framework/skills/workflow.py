"""Workflow runner for composing reusable skills.

A workflow is itself a skill: it runs a sequence of steps, where each step is
another skill looked up by name.  Workflows share a single `SkillContext` across
steps, so later skills can read outputs produced by earlier ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import Skill, SkillContext, SkillResult, get_skill


@dataclass
class WorkflowStep:
    """One step inside a workflow."""

    skill: str
    when: str | None = None
    max_retries: int = 0
    outputs_into: dict[str, str] = field(default_factory=dict)
    # Map result key -> context output key so workflows can rename outputs.


class Workflow(Skill):
    """A skill that composes other skills into a reusable workflow."""

    name: str = ""
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)

    def __init__(
        self,
        name: str,
        description: str = "",
        steps: list[WorkflowStep] | None = None,
    ):
        self.name = name
        self.description = description
        self.steps = steps or []

    def run(self, context: SkillContext) -> SkillResult:
        reasoning: list[str] = []
        for step in self.steps:
            if step.when and not self._evaluate_condition(step.when, context):
                reasoning.append(f"skipped {step.skill}: condition '{step.when}' false")
                continue

            skill_cls = get_skill(step.skill)
            if skill_cls is None:
                return SkillResult.failed(f"unknown skill {step.skill!r}")

            attempt = 0
            while True:
                result = skill_cls().run(context)
                if result.success or attempt >= step.max_retries:
                    break
                attempt += 1
                reasoning.append(f"retrying {step.skill} (attempt {attempt})")

            if not result.success:
                return SkillResult.failed(
                    f"workflow stopped at {step.skill}: {result.error}",
                    outputs=context.outputs,
                )

            for src, dst in step.outputs_into.items():
                if src in result.outputs:
                    context.outputs[dst] = result.outputs[src]

            context.outputs.update(result.outputs)
            context.notes.extend(result.reasoning)
            reasoning.append(f"ran {step.skill}")

        return SkillResult(outputs=context.outputs, reasoning=reasoning)

    def _evaluate_condition(self, condition: str, context: SkillContext) -> bool:
        """Evaluate a simple expression against the context."""
        # Support comparisons like `outputs.has_mapping` or `inputs.auto_only`.
        parts = condition.split()
        if len(parts) == 3 and parts[1] == "==":
            return str(context.get(parts[0].split(".")[-1])) == parts[2]
        if len(parts) == 3 and parts[1] == "!=":
            return str(context.get(parts[0].split(".")[-1])) != parts[2]
        return bool(context.get(condition.split(".")[-1]))
