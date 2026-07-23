"""Agent-based discovery and mapping workflow.

A workflow orchestrates small, focused agents that discover schemas, propose
column mappings, and verify those proposals before anything is auto-accepted.
The default agents run locally, but each has a clean interface so an
LLM-backed implementation can be dropped in without changing the workflow or
any downstream code.
"""

from .base import Agent, AgentContext, AgentResult
from .mapping_agent import LocalMappingAgent, MappingAgent
from .orchestrator import DiscoveryWorkflow
from .source_agent import SourceSchemaAgent
from .target_agent import TargetSchemaAgent
from .verifier_agent import LocalVerifierAgent, VerifierAgent

__all__ = [
    "Agent",
    "AgentContext",
    "AgentResult",
    "MappingAgent",
    "LocalMappingAgent",
    "VerifierAgent",
    "LocalVerifierAgent",
    "SourceSchemaAgent",
    "TargetSchemaAgent",
    "DiscoveryWorkflow",
]
