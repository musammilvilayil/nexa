from pathlib import Path

from platform.agent import NexaAgent
from platform.runtime import SessionManager
from platform.tools import build_default_registry


def test_chat_lists_tools(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = NexaAgent(build_default_registry(), SessionManager(tmp_path / "sessions"))
    reply = agent.chat("show tools")
    assert reply.session_id
    assert "workspace.read" in reply.message


def test_chat_write_then_read(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agent = NexaAgent(build_default_registry(), SessionManager(tmp_path / "sessions"))
    first = agent.chat("write hello.txt :: hello nexa")
    assert first.tool_calls[0]["success"] is True
    second = agent.chat("read hello.txt", first.session_id)
    assert second.tool_calls[0]["success"] is True
    assert "hello nexa" in str(second.tool_calls[0]["data"])
