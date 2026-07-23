import json
import subprocess
from unittest.mock import MagicMock, patch

from migration_framework.connectors.base import ColumnInfo, TableSchema
from migration_framework.skills import GitPullRequestSkill, ProfileSkill, PytestSkill, SkillContext


def test_profile_skill():
    connector = MagicMock()
    connector.get_schema.return_value = TableSchema(
        name="orders",
        columns=[
            ColumnInfo(name="id", canonical_type="integer", native_type="INT", nullable=True),
            ColumnInfo(name="name", canonical_type="string", native_type="VARCHAR", nullable=True),
        ],
        sample_rows=[{"id": 1, "name": "a"}, {"id": 2, "name": None}],
    )
    connector.row_count.return_value = 100

    with patch("migration_framework.skills.builtin.build_connector", return_value=connector):
        result = ProfileSkill().run(
            SkillContext(inputs={"connector": "sqlalchemy", "connection": {}, "table": "orders"})
        )

    assert result.success
    profile = result.outputs["profile"]
    assert profile["table"] == "orders"
    assert profile["total_rows"] == 100
    assert len(profile["columns"]) == 2
    id_col = next(c for c in profile["columns"] if c["name"] == "id")
    assert id_col["min"] == 1.0
    assert id_col["max"] == 2.0
    name_col = next(c for c in profile["columns"] if c["name"] == "name")
    assert name_col["null_count"] == 1


def test_git_pull_request_skill_missing_credentials():
    with patch.dict("os.environ", {}, clear=True):
        result = GitPullRequestSkill().run(
            SkillContext(inputs={"branch": "feat/test", "title": "test", "files": []})
        )
    assert not result.success
    assert "github_token" in result.error.lower() or "required" in result.error.lower()


def _fake_subprocess_run(*args, **kwargs):
    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")


def test_git_pull_request_skill_creates_pr(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.co"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo), check=True, capture_output=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(repo), check=True, capture_output=True)

    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({"html_url": "https://github.com/o/r/pull/1", "number": 1}).encode()
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with (
        patch("migration_framework.skills.builtin.subprocess.run", side_effect=_fake_subprocess_run),
        patch("migration_framework.skills.builtin.urllib.request.urlopen", return_value=fake_response),
    ):
        result = GitPullRequestSkill().run(
            SkillContext(
                inputs={
                    "repo_path": str(repo),
                    "branch": "feat/test",
                    "title": "Add test",
                    "body": "PR body",
                    "files": [{"path": "test.txt", "content": "hello"}],
                    "github_token": "fake-token",
                    "repo_owner": "o",
                    "repo_name": "r",
                    "base_branch": "main",
                }
            )
        )

    assert result.success
    assert result.outputs["pr_url"] == "https://github.com/o/r/pull/1"


def test_pytest_skill_passes():
    code = "def add(x, y):\n    return x + y\n"
    test_code = "from generated_module import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    result = PytestSkill().run(SkillContext(inputs={"code": code, "test_code": test_code}))
    assert result.success
    assert result.outputs["passed"]


def test_pytest_skill_fails():
    code = "def add(x, y):\n    return x + y\n"
    test_code = "from generated_module import add\n\ndef test_add():\n    assert add(1, 2) == 99\n"
    result = PytestSkill().run(SkillContext(inputs={"code": code, "test_code": test_code}))
    assert result.success
    assert not result.outputs["passed"]
