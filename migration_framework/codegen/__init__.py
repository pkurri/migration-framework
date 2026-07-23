"""Per-pair code generation.

Once a mapping is finalized, a `CodeGenerator` writes a runnable load script
for the specific source/target pair. The generated script is checked in and
reviewed like any other code before it is scheduled.
"""

from .base import CodeGenerator, GeneratedCode
from .pyspark_generator import PySparkGenerator
from .registry import build_generator, generate_for, register_generator
from .snowpark_generator import SnowparkGenerator
from .sql_generator import SQLGenerator

__all__ = [
    "CodeGenerator",
    "GeneratedCode",
    "PySparkGenerator",
    "SnowparkGenerator",
    "SQLGenerator",
    "register_generator",
    "build_generator",
    "generate_for",
]
