from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_core import AgentCore, ToolCall, ToolResult, ToolSpec, StepKind


def test_plan_always_ends_with_verification():
    plan = AgentCore().plan("git status nokku")
    assert plan.steps[0].kind is StepKind.PLAN
    assert plan.steps[-1].kind is StepKind.VERIFY
    assert plan.steps[1].tool == "git.status"


def test_unknown_tools_are_blocked():
    result = AgentCore().execute(ToolCall("shell.exec", {}))
    assert not result.ok
    assert "not allowed" in result.output


def test_mutating_tools_require_confirmation():
    core = AgentCore([
        ToolSpec("git.push", "Push branch", True, lambda args: ToolResult(True, "pushed")),
    ])
    result = core.execute(ToolCall("git.push"))
    assert not result.ok
    assert "Confirmation required" in result.output


def test_confirmed_tool_is_verified():
    core = AgentCore([
        ToolSpec("git.status", "Read status", False, lambda args: ToolResult(True, "clean")),
    ])
    result = core.execute(ToolCall("git.status"))
    assert result.ok
    assert result.verified
    assert result.output == "clean"


def test_failed_tool_is_not_verified():
    core = AgentCore([
        ToolSpec("git.status", "Read status", False, lambda args: ToolResult(False, "boom")),
    ])
    result = core.execute(ToolCall("git.status"))
    assert not result.ok
    assert not result.verified
