"""Built-in reusable skills and workflows for the migration framework.

These wrap the existing agents and code generators in the tool-agnostic
`Skill` interface so they can be invoked standalone or composed into custom
workflows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from ..agents import DiscoveryWorkflow, LocalMappingAgent, LocalVerifierAgent
from ..agents.base import AgentContext
from ..codegen import generate_for
from ..config import AuditColumn, MigrationConfig
from ..connectors.base import TableSchema
from ..registry import build_connector
from ..substitution import SubstitutionEngine
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

        config_path = context.inputs.get("config_path")
        if isinstance(config, str):
            config_path = config_path or config
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
            generated = generate_for(migration_config, config_path=config_path)
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


def _column_profile(rows: list[dict[str, Any]], column: str, canonical_type: str) -> dict[str, Any]:
    values = [r.get(column) for r in rows]
    null_count = sum(1 for v in values if v is None)
    non_null = [v for v in values if v is not None]

    distinct: int | None = None
    if non_null:
        try:
            distinct = len(set(non_null))
        except TypeError:
            distinct = len({str(v) for v in non_null})

    profile: dict[str, Any] = {
        "null_count": null_count,
        "non_null_count": len(non_null),
        "distinct_count": distinct,
        "examples": non_null[:5],
    }

    if canonical_type in ("integer", "float") and non_null:
        try:
            nums = [float(v) for v in non_null]
            profile["min"] = min(nums)
            profile["max"] = max(nums)
        except (TypeError, ValueError):
            pass
    elif canonical_type in ("date", "timestamp") and non_null:
        import datetime

        parsed: list[datetime.datetime | datetime.date] = []
        for v in non_null:
            if isinstance(v, (datetime.datetime, datetime.date)):
                parsed.append(v)
        if parsed:
            profile["min"] = min(parsed).isoformat()
            profile["max"] = max(parsed).isoformat()

    return profile


def _table_profile(schema: TableSchema, total_rows: int, sample_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sample_rows or schema.sample_rows or []
    return {
        "table": schema.name,
        "total_rows": total_rows,
        "sample_size": len(rows),
        "columns": [
            {
                "name": col.name,
                "canonical_type": col.canonical_type,
                "native_type": col.native_type,
                "nullable": col.nullable,
                **_column_profile(rows, col.name, col.canonical_type),
            }
            for col in schema.columns
        ],
    }


@register_skill
class ProfileSkill(Skill):
    """Profile a table through any Connector."""

    name = "profile"
    description = "Return schema, row count, and per-column statistics for any table."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        try:
            connector = build_connector(inputs["connector"], inputs.get("connection", {}))
            table = inputs["table"]
            sample_size = inputs.get("sample_size", 100)
            schema = connector.get_schema(table, sample_size=sample_size)
            total_rows = connector.row_count(table)
            sample_rows = list(connector.read_rows(table)) if not schema.sample_rows else schema.sample_rows
            if len(sample_rows) > sample_size:
                sample_rows = sample_rows[:sample_size]
            profile = _table_profile(schema, total_rows, sample_rows)
        except Exception as exc:  # noqa: BLE001
            return SkillResult.failed(f"profile failed: {exc}")

        return SkillResult(
            outputs={"profile": profile},
            reasoning=[f"profiled {table}: {total_rows} rows, {len(schema.columns)} columns"],
        )


@register_skill
class GitPullRequestSkill(Skill):
    """Create a GitHub pull request from generated files using git and the GitHub API."""

    name = "create-pull-request"
    description = "Commit generated files to a new branch and open a GitHub pull request."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        repo_path = inputs.get("repo_path", ".")
        branch = inputs["branch"]
        base_branch = inputs.get("base_branch", "main")
        title = inputs["title"]
        body = inputs.get("body", "")
        files = inputs.get("files", [])
        token = inputs.get("github_token") or os.environ.get("GITHUB_TOKEN")
        owner = inputs.get("repo_owner") or os.environ.get("GITHUB_REPO_OWNER")
        repo = inputs.get("repo_name") or os.environ.get("GITHUB_REPO_NAME")

        if not token or not owner or not repo:
            return SkillResult.failed(
                "github_token, repo_owner, and repo_name are required (or set GITHUB_TOKEN, GITHUB_REPO_OWNER, GITHUB_REPO_NAME)"
            )

        repo_path = Path(repo_path)
        if not (repo_path / ".git").exists():
            return SkillResult.failed(f"{repo_path} is not a git repository")

        def git(args: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                ["git", *args],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
            )

        checkout = git(["checkout", "-b", branch])
        if checkout.returncode != 0:
            return SkillResult.failed(f"git checkout failed: {checkout.stderr}")

        for file_info in files:
            file_path = repo_path / file_info["path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(file_info["content"])

        add = git(["add", "-A"])
        if add.returncode != 0:
            return SkillResult.failed(f"git add failed: {add.stderr}")

        commit = git(["commit", "-m", title, "--allow-empty"])
        if commit.returncode != 0:
            return SkillResult.failed(f"git commit failed: {commit.stderr}")

        push = git(["push", "origin", branch])
        if push.returncode != 0:
            return SkillResult.failed(f"git push failed: {push.stderr}")

        url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "head": branch,
                "base": base_branch,
            }
        ).encode()
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req) as resp:
                pr = json.loads(resp.read().decode())
        except Exception as exc:  # noqa: BLE001
            return SkillResult.failed(f"GitHub API call failed: {exc}")

        return SkillResult(
            outputs={"pr_url": pr.get("html_url"), "pr_number": pr.get("number")},
            reasoning=[f"created pull request {pr.get('number')} at {pr.get('html_url')}"],
        )


@register_skill
class PytestSkill(Skill):
    """Run pytest against generated code and test files."""

    name = "test-generated"
    description = "Write generated code and pytest tests to temp files and run pytest."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        code = inputs.get("code")
        test_code = inputs.get("test_code")
        if not code or not test_code:
            return SkillResult.failed("both `code` and `test_code` are required")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            code_file = tmp / "generated_module.py"
            test_file = tmp / "test_generated.py"
            code_file.write_text(code)
            test_file.write_text(test_code)

            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=short"],
                cwd=str(tmp),
                capture_output=True,
                text=True,
            )

        return SkillResult(
            outputs={
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "passed": result.returncode == 0,
            },
            reasoning=["pytest run completed"],
        )


@register_skill
class SubstituteSkill(Skill):
    """Apply token substitutions (${env:VAR}, {token}) to a config dict or string."""

    name = "substitute"
    description = "Substitute tokens and optional prefix/suffix rules into configuration data."

    def run(self, context: SkillContext) -> SkillResult:
        inputs = context.inputs
        data = inputs.get("data")
        if data is None:
            return SkillResult.failed("substitute skill requires a `data` input")

        engine = SubstitutionEngine(
            tokens=inputs.get("tokens", {}),
            prefix_suffix=inputs.get("prefix_suffix", {}),
        )
        try:
            result = engine.substitute(data)
        except Exception as exc:  # noqa: BLE001
            return SkillResult.failed(f"substitution failed: {exc}")

        return SkillResult(
            outputs={"data": result},
            reasoning=["applied token substitutions"],
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
