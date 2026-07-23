"""Base types for the agent workflow.

Agents are small, focused workers. Each accepts an `AgentContext` and returns
an `AgentResult`. The local implementations run deterministically; the shapes
are chosen so that an LLM-based agent can use the same context and return the
same kind of structured result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ..connectors.base import TableSchema


@dataclass
class AgentContext:
    """Everything an agent might need to reason about a migration."""

    source_connector: str
    source_connection: dict[str, Any]
    source_table: str
    target_connector: str
    target_connection: dict[str, Any]
    target_table: str
    sample_size: int = 50
    source_schema: TableSchema | None = None
    target_schema: TableSchema | None = None
    candidate_proposals: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    def with_source(self, schema: TableSchema) -> "AgentContext":
        return AgentContext(
            source_connector=self.source_connector,
            source_connection=self.source_connection,
            source_table=self.source_table,
            target_connector=self.target_connector,
            target_connection=self.target_connection,
            target_table=self.target_table,
            sample_size=self.sample_size,
            source_schema=schema,
            target_schema=self.target_schema,
            notes=self.notes,
        )

    def with_target(self, schema: TableSchema) -> "AgentContext":
        return AgentContext(
            source_connector=self.source_connector,
            source_connection=self.source_connection,
            source_table=self.source_table,
            target_connector=self.target_connector,
            target_connection=self.target_connection,
            target_table=self.target_table,
            sample_size=self.sample_size,
            source_schema=self.source_schema,
            target_schema=schema,
            notes=self.notes,
        )


@dataclass
class AgentResult:
    """Generic result container returned by every agent."""

    data: Any
    reasoning: list[str] = field(default_factory=list)
    confidence: float = 0.0


class Agent(ABC):
    """One step in the discovery/mapping workflow."""

    @abstractmethod
    def run(self, context: AgentContext) -> AgentResult:
        """Execute the agent against the provided context."""
