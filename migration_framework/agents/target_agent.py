"""Agent that reads the target schema and a sample of its rows."""

from __future__ import annotations

from ..discovery import read_schema
from .base import Agent, AgentContext, AgentResult


class TargetSchemaAgent(Agent):
    """Reads the target side of a migration through the registered connector."""

    def run(self, context: AgentContext) -> AgentResult:
        schema = read_schema(
            context.target_connector,
            context.target_connection,
            context.target_table,
            sample_size=context.sample_size,
        )
        return AgentResult(
            data=schema,
            reasoning=[
                f"Read target {context.target_table!r} via {context.target_connector} connector, "
                f"found {len(schema.columns)} columns and {len(schema.sample_rows)} sample rows."
            ],
        )
