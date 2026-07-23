"""Workflow orchestrator: runs the discovery and mapping agents in sequence.

This is the "workflow" layer from the design doc. It coordinates the individual
agents, feeds their outputs forward, and produces a `MappingProposal` that the
CLI/HITL layer can resolve.
"""

from __future__ import annotations

from typing import Any

from ..connectors.base import TableSchema
from .base import AgentContext
from .mapping_agent import LocalMappingAgent, MappingAgent, MappingProposal
from .source_agent import SourceSchemaAgent
from .target_agent import TargetSchemaAgent
from .verifier_agent import LocalVerifierAgent, VerifierAgent


class DiscoveryWorkflow:
    """Discover + propose + verify a mapping for one source/target pair."""

    def __init__(
        self,
        source_agent: SourceSchemaAgent | None = None,
        target_agent: TargetSchemaAgent | None = None,
        mapping_agent: MappingAgent | None = None,
        verifier_agent: VerifierAgent | None = None,
    ):
        self.source_agent = source_agent or SourceSchemaAgent()
        self.target_agent = target_agent or TargetSchemaAgent()
        self.mapping_agent = mapping_agent or LocalMappingAgent()
        self.verifier_agent = verifier_agent or LocalVerifierAgent()

    def run(
        self,
        source_connector: str,
        source_connection: dict[str, Any],
        source_table: str,
        target_connector: str,
        target_connection: dict[str, Any],
        target_table: str,
        sample_size: int = 50,
    ) -> MappingProposal:
        context = AgentContext(
            source_connector=source_connector,
            source_connection=source_connection,
            source_table=source_table,
            target_connector=target_connector,
            target_connection=target_connection,
            target_table=target_table,
            sample_size=sample_size,
        )

        source_result = self.source_agent.run(context)
        source_schema: TableSchema = source_result.data
        context = context.with_source(source_schema)

        target_result = self.target_agent.run(context)
        target_schema: TableSchema = target_result.data
        context = context.with_target(target_schema)

        mapping_result = self.mapping_agent.run(context)
        mapping_proposal: MappingProposal = mapping_result.data
        context.candidate_proposals = {"mapping_proposal": mapping_proposal}

        verified_result = self.verifier_agent.run(context)
        return verified_result.data
