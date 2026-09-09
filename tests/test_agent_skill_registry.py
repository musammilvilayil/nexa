from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skill_registry import handle_skill_command, render_skill_list


def test_agent_plan_command_is_available():
    reply = handle_skill_command("/agent plan git status nokku")
    assert reply is not None
    assert "Agent plan for: git status nokku" in reply
    assert "git.status" in reply
    assert "verify" in reply


def test_agent_tools_command_is_available():
    reply = handle_skill_command("/agent tools")
    assert reply == "Agent Core v1 active; no execution tools registered."


def test_skill_list_advertises_agent_core():
    reply = render_skill_list()
    assert "Agent Core v1 [active]" in reply
    assert "/agent plan <goal>" in reply
