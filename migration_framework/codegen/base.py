"""Base interface for code generators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import MigrationConfig


@dataclass
class GeneratedCode:
    """Result of generating a migration script."""

    path: str
    language: str  # pyspark | snowpark | sql | dbt | python
    body: str


class CodeGenerator(ABC):
    """Generates a load script for one specific source/target pair."""

    @abstractmethod
    def generate(self, config: MigrationConfig) -> GeneratedCode:
        """Return the generated script and suggested file path."""
