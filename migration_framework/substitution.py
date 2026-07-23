"""Tool-agnostic token substitution for configuration and nested dictionaries.

This module is modelled after the Lakeflow Framework substitution manager but
uses only the Python standard library so it works for any connector or runtime.

It supports:

- ``${env:VAR}`` lookups in ``os.environ``.
- ``{token}`` lookups from a caller-supplied token dictionary.
- Prefix/suffix rules keyed by dictionary key name (useful for medallion
  naming conventions such as ``bronze_`` table prefixes).
- Recursive substitution in strings, lists, and dictionaries.
"""

from __future__ import annotations

import os
import re
from typing import Any, Pattern


_ENV_PATTERN: Pattern = re.compile(r"\$?\{env:([^}]+)\}")
_TOKEN_PATTERN: Pattern = re.compile(r"\{(\w+)\}")


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge ``override`` into ``base``.

    Lists are replaced; dictionaries are merged. Non-mapping values from
    ``override`` take precedence.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = deep_merge(merged.get(key), value) if key in merged else value
        return merged
    return override


class SubstitutionEngine:
    """Replace tokens and apply prefix/suffix rules in strings and dicts."""

    def __init__(
        self,
        tokens: dict[str, Any] | None = None,
        prefix_suffix: dict[str, dict[str, str]] | None = None,
    ) -> None:
        self.tokens = tokens or {}
        self.prefix_suffix = prefix_suffix or {}

    @classmethod
    def from_files(
        cls,
        *paths: str,
        tokens: dict[str, Any] | None = None,
        prefix_suffix: dict[str, dict[str, str]] | None = None,
    ) -> "SubstitutionEngine":
        """Load ``tokens`` and ``prefix_suffix`` from one or more JSON/YAML files.

        Later files override earlier files. The expected file shape is a dict
        with optional top-level ``tokens`` and ``prefix_suffix`` keys.
        """
        import json

        import yaml

        merged_tokens: dict[str, Any] = {}
        merged_rules: dict[str, dict[str, str]] = {}
        for path in paths:
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) if path.endswith((".yaml", ".yml")) else json.load(fh)
            if raw:
                merged_tokens = deep_merge(merged_tokens, raw.get("tokens", {}))
                merged_rules = deep_merge(merged_rules, raw.get("prefix_suffix", {}))
        if tokens:
            merged_tokens = deep_merge(merged_tokens, tokens)
        if prefix_suffix:
            merged_rules = deep_merge(merged_rules, prefix_suffix)
        return cls(tokens=merged_tokens, prefix_suffix=merged_rules)

    def substitute(self, data: Any) -> Any:
        """Recursively substitute tokens in ``data``."""
        if isinstance(data, dict):
            return {
                key: self._apply_prefix_suffix(key, self.substitute(value))
                for key, value in data.items()
            }
        if isinstance(data, list):
            return [self.substitute(item) for item in data]
        if isinstance(data, str):
            return self._substitute_string(data)
        return data

    def _substitute_string(self, value: str) -> str:
        def env_repl(match: re.Match) -> str:
            return os.environ.get(match.group(1), match.group(0))

        def token_repl(match: re.Match) -> str:
            token = match.group(1)
            if token in self.tokens:
                return str(self.tokens[token])
            return match.group(0)

        value = _ENV_PATTERN.sub(env_repl, value)
        value = _TOKEN_PATTERN.sub(token_repl, value)
        return value

    def _apply_prefix_suffix(self, key: str, value: Any) -> Any:
        if isinstance(value, str) and key in self.prefix_suffix:
            rules = self.prefix_suffix[key]
            if "prefix" in rules:
                value = rules["prefix"] + value
            if "suffix" in rules:
                value = value + rules["suffix"]
        return value
