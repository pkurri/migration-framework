"""A tool-agnostic framework for migrating data between any two systems.

Point it at a source table and a target table; it reads both schemas,
proposes a column mapping on its own, asks a person only about what it
can't confidently resolve, and then runs (and re-runs) the migration from
the resulting config.
"""

from .config import ColumnMapping, MigrationConfig, SourceSpec, TargetSpec
from .engine import RunResult, run_migration
from .mapper import MappingProposal, propose_mapping

__all__ = [
    "MigrationConfig",
    "SourceSpec",
    "TargetSpec",
    "ColumnMapping",
    "propose_mapping",
    "MappingProposal",
    "run_migration",
    "RunResult",
]

__version__ = "0.1.0"
