from migration_framework.skills import (
    SkillContext,
    Workflow,
    WorkflowStep,
    get_skill,
    list_skills,
    register_skill,
)
from migration_framework.skills.base import Skill, SkillResult


@register_skill
class EchoSkill(Skill):
    name = "echo"
    description = "echoes an input back"

    def run(self, context: SkillContext) -> SkillResult:
        return SkillResult(outputs={"echo": context.inputs.get("message", "")})


def test_registry_lists_builtin_and_custom_skills():
    names = list_skills()
    assert "discover" in names
    assert "map" in names
    assert "verify" in names
    assert "codegen" in names
    assert "map-verify-codegen" in names
    assert "echo" in names


def test_get_skill_returns_class():
    assert get_skill("echo") is EchoSkill
    assert get_skill("map") is not None


def test_workflow_composes_steps_and_shares_context():
    wf = Workflow(
        name="double-echo",
        description="run echo twice",
        steps=[
            WorkflowStep(skill="echo"),
            WorkflowStep(skill="echo"),
        ],
    )
    result = wf.run(SkillContext(inputs={"message": "hello"}))
    assert result.success
    assert result.outputs["echo"] == "hello"
    assert result.reasoning == ["ran echo", "ran echo"]


def test_workflow_conditional_step():
    wf = Workflow(
        name="conditional",
        steps=[
            WorkflowStep(skill="echo"),
            WorkflowStep(skill="echo", when="skip == true"),
        ],
    )
    result = wf.run(SkillContext(inputs={"message": "hi", "skip": "false"}))
    assert result.success
    assert "skipped" in result.reasoning[-1]


def test_workflow_retries_failed_step():
    class FlakySkill(Skill):
        name = "flaky"
        description = "fails then succeeds"
        calls = 0

        def run(self, context: SkillContext) -> SkillResult:
            FlakySkill.calls += 1
            if FlakySkill.calls < 2:
                return SkillResult.failed("not yet")
            return SkillResult(outputs={"ok": True})

    register_skill(FlakySkill)

    wf = Workflow(
        name="retry-test",
        steps=[WorkflowStep(skill="flaky", max_retries=2)],
    )
    result = wf.run(SkillContext())
    assert result.success
    assert result.outputs["ok"] is True
    assert FlakySkill.calls == 2


def test_codegen_skill_rejects_missing_config():
    skill = get_skill("codegen")
    result = skill().run(SkillContext())
    assert not result.success
    assert "config" in result.error.lower()


def test_skill_context_require_and_get():
    ctx = SkillContext(inputs={"a": 1}, outputs={"b": 2})
    assert ctx.get("a") == 1
    assert ctx.get("b") == 2
    assert ctx.get("c", 3) == 3
    assert ctx.require("a") == 1
