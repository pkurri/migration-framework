import json

from migration_framework.mcp_server import list_connectors, list_skills, run_skill


def test_list_skills_returns_registered_skills():
    result = json.loads(list_skills())
    assert "discover" in result
    assert "map-verify-codegen" in result


def test_list_connectors_includes_native_connectors():
    result = json.loads(list_connectors())
    assert "sqlalchemy" in result
    assert "snowflake" in result
    assert "databricks" in result


def test_run_skill_returns_result_for_codegen_skill():
    inputs = json.dumps({"config": {"job_name": "demo", "source": {"connector": "sqlalchemy", "connection": {}, "table": "a"}, "target": {"connector": "sqlalchemy", "connection": {}, "table": "b"}, "columns": []}})
    result = json.loads(run_skill("codegen", inputs))
    assert result["success"] is True
    assert "generated" in result["outputs"]


def test_run_skill_returns_error_for_unknown_skill():
    result = json.loads(run_skill("no-such-skill", "{}"))
    assert result["success"] is False
