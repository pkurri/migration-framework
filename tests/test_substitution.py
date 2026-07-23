import os
from pathlib import Path

import yaml

from migration_framework.config import MigrationConfig
from migration_framework.skills import SubstituteSkill, SkillContext
from migration_framework.substitution import SubstitutionEngine, deep_merge


def test_deep_merge_dicts():
    base = {"a": {"b": 1, "c": 2}, "d": [1, 2]}
    override = {"a": {"c": 3, "e": 4}, "d": [5]}
    assert deep_merge(base, override) == {"a": {"b": 1, "c": 3, "e": 4}, "d": [5]}


def test_substitution_engine_env_and_tokens(monkeypatch):
    monkeypatch.setenv("DB_NAME", "production")
    engine = SubstitutionEngine(tokens={"schema": "silver"})
    data = {
        "connection_url": "postgresql:///{env:DB_NAME}/{schema}.orders",
        "name": "{schema}_orders",
    }
    assert engine.substitute(data) == {
        "connection_url": "postgresql:///production/silver.orders",
        "name": "silver_orders",
    }


def test_substitution_engine_prefix_suffix():
    engine = SubstitutionEngine(
        tokens={"layer": "bronze"},
        prefix_suffix={"table": {"prefix": "bronze_"}},
    )
    assert engine.substitute({"table": "{layer}_orders"}) == {"table": "bronze_bronze_orders"}


def test_substitution_engine_from_files(tmp_path):
    tokens_path = tmp_path / "tokens.yaml"
    tokens_path.write_text("tokens:\n  env: prod\nprefix_suffix:\n  table:\n    prefix: prod_\n")
    engine = SubstitutionEngine.from_files(str(tokens_path))
    assert engine.substitute({"table": "{env}_orders"}) == {"table": "prod_prod_orders"}


def test_substitution_skill():
    result = SubstituteSkill().run(
        SkillContext(
            inputs={
                "data": {"name": "{schema}_orders"},
                "tokens": {"schema": "silver"},
            }
        )
    )
    assert result.success
    assert result.outputs["data"] == {"name": "silver_orders"}


def test_migration_config_load_with_overrides_and_substitutions(tmp_path):
    base = tmp_path / "base.yaml"
    override = tmp_path / "override.yaml"
    base.write_text(
        yaml.safe_dump({
            "job_name": "orders",
            "source": {"connector": "sqlalchemy", "connection": {"url": "{base_url}"}, "table": "raw_orders"},
            "target": {"connector": "sqlalchemy", "connection": {"url": "{base_url}"}, "table": "orders"},
            "columns": [{"target": "id", "source": "id"}],
        })
    )
    override.write_text(
        yaml.safe_dump({
            "source": {"connection": {"url": "overridden"}},
            "target": {"table": "silver_orders"},
        })
    )

    config = MigrationConfig.load(str(base), overrides_path=str(override), substitutions={"base_url": "sqlite:///dev.db"})
    assert config.job_name == "orders"
    assert config.source.connection["url"] == "overridden"
    assert config.target.table == "silver_orders"
