from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Mapping, Sequence


class StepKind(str, Enum):
    PLAN = "plan"
    TOOL = "tool"
    VERIFY = "verify"


@dataclass(frozen=True)
class AgentTask:
    """A normalized user goal handled by the agent loop."""

    goal: str


@dataclass(frozen=True)
class PlanStep:
    id: str
    kind: StepKind
    description: str
    tool: str | None = None
    mutating: bool = False


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Mapping[str, object] = field(default_factory=dict)
    confirmed: bool = False


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str
    verified: bool = False


@dataclass(frozen=True)
class AgentPlan:
    task: AgentTask
    steps: tuple[PlanStep, ...]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    mutating: bool
    handler: Callable[[Mapping[str, object]], ToolResult]


class AgentCore:
    """Small, deterministic agent orchestration layer for NEXA.

    This is an independent Astra-style capability layer, not a copy of any
    proprietary model internals. Planning is explicit, tools are allow-listed,
    mutations require confirmation, and successful tool work is followed by a
    verification step.
    """

    def __init__(self, tools: Sequence[ToolSpec] = ()) -> None:
        self._tools: dict[str, ToolSpec] = {tool.name: tool for tool in tools}

    def register_tool(self, tool: ToolSpec) -> None:
        if not tool.name or tool.name.startswith("_"):
            raise ValueError("Tool name must be a public non-empty identifier")
        self._tools[tool.name] = tool

    def available_tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._tools))

    def plan(self, goal: str) -> AgentPlan:
        goal = goal.strip()
        if not goal:
            raise ValueError("Agent goal cannot be empty")

        normalized = goal.lower()
        steps: list[PlanStep] = [
            PlanStep("understand", StepKind.PLAN, "Understand and normalize the requested goal."),
        ]

        if any(token in normalized for token in ("git status", "repo status", "repository status")):
            steps.append(PlanStep("tool", StepKind.TOOL, "Inspect repository status.", "git.status"))
        elif any(token in normalized for token in ("git diff", "repo changes", "changes nokku")):
            steps.append(PlanStep("tool", StepKind.TOOL, "Inspect repository changes.", "git.diff"))
        elif "git pull" in normalized or "pull latest" in normalized:
            steps.append(PlanStep("tool", StepKind.TOOL, "Update the repository with a fast-forward-only pull.", "git.pull", True))
        elif "git push" in normalized or "push" in normalized and "github" in normalized:
            steps.append(PlanStep("tool", StepKind.TOOL, "Push the current branch to its configured remote.", "git.push", True))
        elif "commit" in normalized:
            steps.append(PlanStep("tool", StepKind.TOOL, "Create a Git commit using the explicit user message.", "git.commit", True))
        else:
            steps.append(PlanStep("reason", StepKind.PLAN, "Reason about the goal without executing an unregistered tool."))

        steps.append(PlanStep("verify", StepKind.VERIFY, "Verify the outcome before reporting success."))
        return AgentPlan(AgentTask(goal), tuple(steps))

    def execute(self, call: ToolCall) -> ToolResult:
        spec = self._tools.get(call.name)
        if spec is None:
            return ToolResult(False, f"Tool not allowed: {call.name}")
        if spec.mutating and not call.confirmed:
            return ToolResult(False, f"Confirmation required before mutating tool: {call.name}")

        result = spec.handler(call.args)
        if not result.ok:
            return result
        return ToolResult(True, result.output, verified=self.verify(call.name, result))

    @staticmethod
    def verify(tool_name: str, result: ToolResult) -> bool:
        """Conservative verification: a tool must succeed and return output."""
        return bool(tool_name and result.ok and result.output.strip())

    def describe(self) -> str:
        if not self._tools:
            return "Agent Core v1 active; no execution tools registered."
        lines = ["Agent Core v1 tools:"]
        for name in self.available_tools():
            spec = self._tools[name]
            mutation = "mutating" if spec.mutating else "read-only"
            lines.append(f"- {name} [{mutation}] - {spec.description}")
        return "\n".join(lines)
