from pathlib import Path

import pytest

from platform.agent import NexaAgent
from platform.runtime import SessionManager, SessionState
from platform.tools import build_default_registry


def test_registry_discovers_workspace_tools():
    registry = build_default_registry()
    names = {item["name"] for item in registry.search("workspace file")}
    assert "workspace.read" in names
    assert "workspace.write" in names


def test_workspace_round_trip(tmp_path: Path):
    registry = build_default_registry()
    result = registry.call("workspace.write", {"workspace": str(tmp_path), "path": "hello.txt", "content": "NEXA"})
    assert result.success
    result = registry.call("workspace.read", {"workspace": str(tmp_path), "path": "hello.txt"})
    assert result.success
    assert result.data["content"] == "NEXA"


def test_workspace_blocks_escape(tmp_path: Path):
    result = build_default_registry().call("workspace.read", {"workspace": str(tmp_path), "path": "../secret.txt"})
    assert not result.success


def test_session_lifecycle(tmp_path: Path):
    manager = SessionManager(tmp_path)
    session = manager.create()
    assert session.state == SessionState.CREATED
    manager.transition(session, SessionState.RUNNING)
    manager.transition(session, SessionState.SUSPENDED)
    manager.transition(session, SessionState.RUNNING)
    manager.transition(session, SessionState.STOPPED)
    with pytest.raises(ValueError):
        manager.transition(session, SessionState.RUNNING)


def test_agent_chat_persists_conversation(tmp_path: Path):
    agent = NexaAgent(sessions=SessionManager(tmp_path / "sessions"))
    first = agent.chat("show tools")
    assert "workspace.read" in first.message
    session = agent.sessions.load(first.session_id)
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
