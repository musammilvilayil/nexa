from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core import AgentCore, ToolCall, ToolResult, ToolSpec
from gemini_agent import GeminiAgent, GeminiAgentError
from git_skill import GitSkill


class AgentRuntime:
    """Connect Gemini reasoning to NEXA's allow-listed local tools."""

    def __init__(self, repo_root: str | Path):
        self.git = GitSkill(repo_root)
        self.gemini = GeminiAgent()
        self.core = AgentCore()
        self._pending: ToolCall | None = None
        self._register_tools()

    @staticmethod
    def _git_result(result) -> ToolResult:
        output = result.stdout or result.stderr or "(no output)"
        return ToolResult(result.ok, output)

    def _register_tools(self) -> None:
        self.core.register_tool(ToolSpec(
            "git.status", "Read repository status.", False,
            lambda args: self._git_result(self.git.status()),
        ))
        self.core.register_tool(ToolSpec(
            "git.diff", "Read working-tree diff.", False,
            lambda args: self._git_result(self.git.diff(bool(args.get("staged", False)))),
        ))
        self.core.register_tool(ToolSpec(
            "git.branch", "Read the current branch.", False,
            lambda args: self._git_result(self.git.current_branch()),
        ))
        self.core.register_tool(ToolSpec(
            "git.history", "Read recent commits.", False,
            lambda args: self._git_result(self.git.history(int(args.get("limit", 10)))),
        ))
        self.core.register_tool(ToolSpec(
            "git.conflicts", "Read unresolved conflict files.", False,
            lambda args: self._git_result(self.git.conflict_files()),
        ))
        self.core.register_tool(ToolSpec(
            "git.pull", "Fast-forward-only pull.", True,
            lambda args: self._git_result(self.git.pull_ff_only(str(args["branch"]), str(args.get("remote", "origin")))),
        ))
        self.core.register_tool(ToolSpec(
            "git.commit", "Create a commit with an explicit message.", True,
            lambda args: self._git_result(self.git.commit(str(args["message"]))),
        ))
        self.core.register_tool(ToolSpec(
            "git.push", "Push an explicit branch to a configured remote.", True,
            lambda args: self._git_result(self.git.push(str(args["branch"]), str(args.get("remote", "origin")), bool(args.get("set_upstream", False)))),
        ))

    def tools_for_gemini(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": self.core._tools[name].description, "mutating": self.core._tools[name].mutating}
            for name in self.core.available_tools()
        ]

    def run(self, goal: str) -> str:
        if not self.gemini.available:
            return "Gemini agent unavailable: GEMINI_API_KEY configure cheyyanam."
        try:
            decision = self.gemini.decide(goal, self.tools_for_gemini())
        except GeminiAgentError as exc:
            return f"Gemini agent error: {exc}"

        if not decision.tool:
            return decision.answer or "Goal understand cheythu; execution tool select cheythilla."

        if decision.tool not in self.core.available_tools():
            return f"Blocked: Gemini selected unregistered tool `{decision.tool}`."

        spec = self.core._tools[decision.tool]
        call = ToolCall(decision.tool, decision.args, confirmed=False)
        if spec.mutating:
            self._pending = call
            return (
                f"Action ready: {decision.tool}\n"
                f"Args: {dict(decision.args)}\n"
                "Ithu repository change undakkum. Confirm cheyyan `/agent confirm` use cheyyu."
            )

        result = self.core.execute(call)
        if not result.ok:
            return f"Tool failed: {result.output}"
        return f"{decision.answer}\n\nTool result (verified={result.verified}):\n{result.output}"

    def confirm(self) -> str:
        if self._pending is None:
            return "Pending mutating agent action illa."
        call = ToolCall(self._pending.name, self._pending.args, confirmed=True)
        self._pending = None
        result = self.core.execute(call)
        if not result.ok:
            return f"Confirmed action failed: {result.output}"
        return f"Action completed and verified={result.verified}:\n{result.output}"
