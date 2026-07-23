"""Built-in reusable skills and workflows for the migration framework.

These wrap the existing agents and code generators in the tool-agnostic
`Skill` interface so they can be invoked standalone or composed into custom
workflows.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..agents import DiscoveryWorkflow, LocalMappingAgent, LocalVerifierAgent
from ..agents.base import AgentContext
from ..codegen import generate_for
from ..config import AuditColumn, MigrationConfig
from .base import Skill, SkillContext, SkillResult, register_skill
from .workflow import Workflow, WorkflowStep


def _agent_context_from_inputs(inputs: dict[str, Any]) -> AgentContext:
    """Build an AgentContext from skill inputs."""
    return AgentContext(
        source_connector=inputs["source_connector"],
        source_connection=inputs.get("source_connection", {}),
        source_table=inputs["source_table"],
        target_connector=inputs["target_connector"],
        target_connection=inputs.get("target_connection", {}),
        target_table=inputs["target_table"],
        sample_size=inputs.get("sample_size", 50),
        source_schema=inputs.get("source_schema"),
        target_schema=inputs.get("target_schema"),
    )


@register_skill
class ReadSourceSkill(Skill):
    """Read a source schema and sample rows."""

    name = "read-source"
    description = "Read the source schema and sample rows for a given table."

    def run(self, context: SkillContext) -> SkillResult:
        ctx = _agent_context_from_inputs(context.inputs)
        result = DiscoveryWorkflow().source_agent.run(ctx)
        return SkillResult(
            outputs={"source_schema": result.data},
            reasoning=result.reasoning,
        )


@register_skill
class ReadTargetSkill(Skill):
    """Read a target schema and sample rows."""

    name = "read-target"
    description = "Read the target schema and sample rows for a given table."

    def run(self, context: SkillContext) -> SkillResult:
        ctx = _agent_context_from_inputs(context.inputs)
        result = DiscoveryWorkflow().target_agent.run(ctx)
        return SkillResult(
            outputs={"target_schema": result.data},
            reasoning=result.reasoning,
        )


@register_skill
class MapSkill(Skill):
    """Propose a column mapping between source and target schemas."""

    name = "map"
    description = "Propose a column mapping given source and target schemas."

    def run(self, context: SkillContext) -> SkillResult:
        ctx = _agent_context_from_inputs(context.inputs)
        if ctx.source_schema is None or ctx.target_schema is None:
            return SkillResult.failed(
                "map skill requires source_schema and target_schema in inputs or outputs"
            )
        result = LocalMappingAgent().run(ctx)
        return SkillResult(
            outputs={"mapping_proposal": result.data},
            reasoning=result.reasoning,
        )


@register_skill
class VerifySkill(Skill):
    """Verify a mapping proposal, downgrading weak or ambiguous matches."""

    name = "verify"
    description = "Verify a mapping proposal and downgrade uncertain matches."

    def run(self, context: SkillContext) -> SkillResult:
        ctx = _agent_context_from_inputs(context.inputs)
        proposal = context.inputs.get("mapping_proposal")
        if proposal is None:
            return SkillResult.failed("verify skill requires mapping_proposal in inputs")
        ctx.candidate_proposals = {"mapping_proposal": proposal}
        result = LocalVerifierAgent().run(ctx)
        return SkillResult(
            outputs={"mapping_proposal": result.data},
            reasoning=result.reasoning,
        )


@register_skill
class DiscoverSkill(Skill):
    """Run the full discovery and mapping workflow for a source/target pair."""

    name = "discover"
    description = "Discover schemas, propose a mapping, and verify it."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        try:
            proposal = DiscoveryWorkflow().run(
                source_connector=inputs["source_connector"],
                source_connection=inputs.get("source_connection", {}),
                source_table=inputs["source_table"],
                target_connector=inputs["target_connector"],
                target_connection=inputs.get("target_connection", {}),
                target_table=inputs["target_table"],
                sample_size=inputs.get("sample_size", 50),
            )
        except Exception as exc:  # noqa: BLE001 - surface root cause without tying to one connector
            return SkillResult.failed(f"discovery failed: {exc}")
        return SkillResult(
            outputs={"mapping_proposal": proposal},
            reasoning=["ran full discover workflow"],
        )


@register_skill
class CodegenSkill(Skill):
    """Generate a runnable load script for a migration config."""

    name = "codegen"
    description = "Generate SQL, PySpark, or Snowpark load code for a config."

    def run(self, context: SkillContext) -> SkillResult:
        config = context.inputs.get("config")
        if config is None:
            return SkillResult.failed("codegen skill requires a `config` input")

        if isinstance(config, str):
            if not os.path.exists(config):
                return SkillResult.failed(f"config file not found: {config}")
            try:
                migration_config = MigrationConfig.load(config)
            except Exception as exc:  # noqa: BLE001
                return SkillResult.failed(f"failed to load config: {exc}")
        elif isinstance(config, dict):
            try:
                migration_config = MigrationConfig.from_dict(config)
            except Exception as exc:  # noqa: BLE001
                return SkillResult.failed(f"failed to parse config dict: {exc}")
        elif isinstance(config, MigrationConfig):
            migration_config = config
        else:
            return SkillResult.failed("config must be a path, dict, or MigrationConfig")

        try:
            generated = generate_for(migration_config)
        except Exception as exc:  # noqa: BLE001
            return SkillResult.failed(f"code generation failed: {exc}")

        return SkillResult(
            outputs={
                "generated": {
                    "path": generated.path,
                    "language": generated.language,
                    "body": generated.body,
                }
            },
            reasoning=[f"generated {generated.language} load script"],
        )


@register_skill
class BuildConfigSkill(Skill):
    """Build a MigrationConfig from a verified mapping proposal."""

    name = "build-config"
    description = "Turn a mapping proposal and audit columns into a MigrationConfig."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        proposal = inputs.get("mapping_proposal")
        if proposal is None:
            return SkillResult.failed("build-config requires mapping_proposal")

        audit_names = set(n.strip() for n in inputs.get("audit_columns", "").split(",") if n.strip())
        audit_columns = [AuditColumn(name=n, generator=inputs.get("audit_generators", {}).get(n, "null")) for n in sorted(audit_names)]

        from ..hitl import resolve_with_answers

        try:
            columns = resolve_with_answers(proposal, inputs.get("answers", {}))
        except Exception as exc:  # noqa: BLE001
            return SkillResult.failed(f"could not resolve mapping: {exc}")

        config = MigrationConfig(
            job_name=inputs["job_name"],
            source=migration_from_inputs(inputs, "source"),
            target=migration_from_inputs(inputs, "target"),
            columns=columns,
            audit_columns=audit_columns,
        )
        return SkillResult(
            outputs={"config": config},
            reasoning=["built MigrationConfig from mapping proposal"],
        )


def migration_from_inputs(inputs: dict[str, Any], side: str):
    from ..config import SourceSpec, TargetSpec
    cls = SourceSpec if side == "source" else TargetSpec
    return cls(
        connector=inputs[f"{side}_connector"],
        connection=inputs.get(f"{side}_connection", {}),
        table=inputs[f"{side}_table"],
    )


@register_skill
class MapVerifyCodegenWorkflow(Workflow):
    """Built-in reusable workflow: discover -> build config -> codegen."""

    name = "map-verify-codegen"
    description = "Discover, verify, build a config, and generate load code."

    def __init__(self) -> None:
        super().__init__(
            name=self.name,
            description=self.description,
            steps=[
                WorkflowStep(skill="discover"),
                WorkflowStep(skill="build-config", outputs_into={"config": "config"}),
                WorkflowStep(skill="codegen"),
            ],
        )
