"""Agent that reads the source schema and a sample of its rows."""

from __future__ import annotations

from ..discovery import read_schema
from .base import Agent, AgentContext, AgentResult


class SourceSchemaAgent(Agent):
    """Reads the source side of a migration through the registered connector."""

    def run(self, context: AgentContext) -> AgentResult:
        schema = read_schema(
            context.source_connector,
            context.source_connection,
            context.source_table,
            sample_size=context.sample_size,
        )
        return AgentResult(
            data=schema,
            reasoning=[
                f"Read source {context.source_table!r} via {context.source_connector} connector, "
                f"found {len(schema.columns)} columns and {len(schema.sample_rows)} sample rows."
            ],
        )
