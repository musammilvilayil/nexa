from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gemini_agent import GeminiAgent, GeminiAgentError


def test_gemini_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(GeminiAgentError, match="GEMINI_API_KEY"):
        GeminiAgent().decide("check repo", [])


def test_gemini_decision_never_executes_tool_text(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"answer":"ok","tool":"git.status","args":{},"requires_confirmation":false}'}]}}]}

    monkeypatch.setattr("gemini_agent.httpx.post", lambda *args, **kwargs: FakeResponse())
    decision = GeminiAgent().decide("check repo", [{"name": "git.status", "mutating": False}])
    assert decision.tool == "git.status"
    assert decision.args == {}
    assert decision.requires_confirmation is False
