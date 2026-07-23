"""Tool-agnostic reusable skills.

A `Skill` is a small, independently runnable unit of work.  Skills accept a
`SkillContext` (a bag of inputs and any outputs produced so far) and return a
`SkillResult`.  They are intentionally not tied to any one database, CLI command,
or source/target pair, so the same skill can be reused inside workflows,
test fixtures, or future non-migration tooling.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillContext:
    """Inputs and working state for a skill.

    `inputs` holds the parameters supplied by the caller.  `outputs` is a shared
    workspace where skills can leave values for later skills in a workflow.
    """

    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def require(self, key: str) -> Any:
        if key in self.inputs:
            return self.inputs[key]
        if key in self.outputs:
            return self.outputs[key]
        raise KeyError(f"skill input {key!r} not found in context")

    def get(self, key: str, default: Any = None) -> Any:
        return self.inputs.get(key, self.outputs.get(key, default))


@dataclass
class SkillResult:
    """Result of running a skill."""

    outputs: dict[str, Any] = field(default_factory=dict)
    reasoning: list[str] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @classmethod
    def failed(cls, message: str, outputs: dict[str, Any] | None = None) -> "SkillResult":
        return cls(outputs=outputs or {}, success=False, error=message)


class Skill(ABC):
    """A reusable, tool-agnostic unit of work."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run(self, context: SkillContext) -> SkillResult:
        """Execute the skill."""


SKILL_REGISTRY: dict[str, type[Skill]] = {}


def register_skill(cls: type[Skill]) -> type[Skill]:
    """Decorator that registers a skill by its `name`."""
    if not cls.name:
        raise ValueError(f"skill {cls.__name__} must define a `name`")
    SKILL_REGISTRY[cls.name] = cls
    return cls


def get_skill(name: str) -> type[Skill] | None:
    return SKILL_REGISTRY.get(name)


def list_skills() -> dict[str, str]:
    return {name: cls.description for name, cls in SKILL_REGISTRY.items()}
