"""Reusable skills and workflows.

Skills are tool-agnostic units of work.  They can be invoked from the CLI,
composed into workflows, or called directly from Python.
"""

from __future__ import annotations

from .base import Skill, SkillContext, SkillResult, get_skill, list_skills, register_skill
from .builtin import (
    BuildConfigSkill,
    CodegenSkill,
    DiscoverSkill,
    GitPullRequestSkill,
    MapSkill,
    MapVerifyCodegenWorkflow,
    ProfileSkill,
    PytestSkill,
    ReadSourceSkill,
    ReadTargetSkill,
    SubstituteSkill,
    VerifySkill,
)
from .workflow import Workflow, WorkflowStep

__all__ = [
    "Skill",
    "SkillContext",
    "SkillResult",
    "Workflow",
    "WorkflowStep",
    "get_skill",
    "list_skills",
    "register_skill",
    "ReadSourceSkill",
    "ReadTargetSkill",
    "MapSkill",
    "VerifySkill",
    "DiscoverSkill",
    "CodegenSkill",
    "BuildConfigSkill",
    "ProfileSkill",
    "GitPullRequestSkill",
    "PytestSkill",
    "SubstituteSkill",
    "MapVerifyCodegenWorkflow",
]
