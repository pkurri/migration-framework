"""MCP server exposing the migration framework as composable tools.

Requires the `mcp` extra:
    pip install "migration-framework[mcp]"

Run with stdio (for Claude Desktop / Claude Code):
    python -m migration_framework.mcp_server

Or programmatically:
    from migration_framework.mcp_server import mcp
    mcp.run(transport="stdio")
"""

from __future__ import annotations

import json
import sys
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError("mcp server requires `pip install migration-framework[mcp]`") from exc

from .cli import build_parser
from .config import MigrationConfig
from .engine import run_migration
from .registry import CONNECTOR_REGISTRY
from .skills import SkillContext, get_skill, list_skills as _list_skills

mcp = FastMCP("migration-framework")


def _serialize(value: Any) -> str:
    return json.dumps(value, default=str, indent=2)


@mcp.tool()
def list_skills() -> str:
    """Return all registered skills and workflows."""
    return _serialize(_list_skills())


@mcp.tool()
def list_connectors() -> str:
    """Return all registered source/target connectors."""
    return _serialize({name: cls.__doc__ or "" for name, cls in CONNECTOR_REGISTRY.items()})


@mcp.tool()
def run_skill(name: str, inputs: str) -> str:
    """Run a single reusable skill or workflow.

    Args:
        name: skill/workflow name, e.g. "discover", "codegen", "map-verify-codegen".
        inputs: JSON object of skill inputs.
    """
    skill_cls = get_skill(name)
    if skill_cls is None:
        return _serialize({"success": False, "error": f"unknown skill {name!r}"})
    parsed = json.loads(inputs) if inputs else {}
    result = skill_cls().run(SkillContext(inputs=parsed))
    return _serialize({
        "success": result.success,
        "outputs": result.outputs,
        "reasoning": result.reasoning,
        "error": result.error,
    })


@mcp.tool()
def run_workflow(name: str, inputs: str) -> str:
    """Alias for run_skill; workflows are also registered skills."""
    return run_skill(name, inputs)


@mcp.tool()
def discover(
    source_connector: str,
    source_connection: str,
    source_table: str,
    target_connector: str,
    target_connection: str,
    target_table: str,
    job_name: str,
    audit_columns: str = "",
    sample_size: int = 50,
) -> str:
    """Discover schemas, propose a mapping, and generate a load script.

    Connections should be JSON objects containing the driver-specific kwargs.
    """
    inputs = {
        "source_connector": source_connector,
        "source_connection": json.loads(source_connection),
        "source_table": source_table,
        "target_connector": target_connector,
        "target_connection": json.loads(target_connection),
        "target_table": target_table,
        "job_name": job_name,
        "audit_columns": audit_columns,
        "sample_size": sample_size,
    }
    return run_skill("map-verify-codegen", json.dumps(inputs))


@mcp.tool()
def migrate(config_path: str, dry_run: bool = False) -> str:
    """Run a migration from a saved YAML config."""
    try:
        config = MigrationConfig.load(config_path)
        result = run_migration(config, dry_run=dry_run)
        return _serialize({
            "success": True,
            "rows_read": result.rows_read,
            "rows_written": result.rows_written,
            "target_row_count_before": result.target_row_count_before,
            "target_row_count_after": result.target_row_count_after,
            "reconciled": result.reconciled,
            "dry_run": result.dry_run,
        })
    except Exception as exc:  # noqa: BLE001
        return _serialize({"success": False, "error": str(exc)})


def main() -> int:
    transport = "stdio"
    if len(sys.argv) > 1:
        transport = sys.argv[1]
    mcp.run(transport=transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
