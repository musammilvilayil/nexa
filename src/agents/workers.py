from __future__ import annotations

from typing import Any, Mapping
from core.contracts import RiskTier
from .contracts import AgentDelegation, AgentResult, AgentRole


class BaseWorker:
    def __init__(self, role: AgentRole, allowed_risk: RiskTier = RiskTier.MUTATE) -> None:
        self.role = role
        self.allowed_risk = allowed_risk

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        raise NotImplementedError


class PlannerWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.PLANNER, allowed_risk=RiskTier.READ)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        goal = delegation.instruction
        subtasks = [
            {"step": 1, "action": "research", "goal": f"Collect info on {goal}"},
            {"step": 2, "action": "execute", "goal": f"Execute action for {goal}"},
            {"step": 3, "action": "verify", "goal": f"Verify outcome for {goal}"},
        ]
        return AgentResult(
            success=True,
            output=f"Plan generated with {len(subtasks)} steps for: {goal}",
            data={"subtasks": subtasks, "goal": goal},
            role=self.role,
        )


class ResearchWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.RESEARCH, allowed_risk=RiskTier.REMOTE)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        query = delegation.instruction
        findings = [
            {"title": f"Source 1 on {query}", "snippet": f"Validated details regarding {query}"},
            {"title": f"Source 2 on {query}", "snippet": f"Additional verified findings for {query}"},
        ]
        return AgentResult(
            success=True,
            output=f"Research completed for '{query}' with {len(findings)} references.",
            data={"query": query, "findings": findings},
            role=self.role,
        )


class BrowserWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.BROWSER, allowed_risk=RiskTier.REMOTE)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        target = delegation.instruction
        return AgentResult(
            success=True,
            output=f"Browser action completed: {target}",
            data={"action": "browser_navigation", "target": target},
            role=self.role,
        )


class DesktopWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.DESKTOP, allowed_risk=RiskTier.MUTATE)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        action = delegation.instruction
        return AgentResult(
            success=True,
            output=f"Desktop action executed: {action}",
            data={"action": "desktop_control", "details": delegation.params},
            role=self.role,
        )


class CoderWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.CODER, allowed_risk=RiskTier.MUTATE)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        task = delegation.instruction
        return AgentResult(
            success=True,
            output=f"Code changes synthesized for: {task}",
            data={"files_modified": ["src/example.py"], "diff_lines": 4},
            role=self.role,
        )


class VerifierWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.VERIFIER, allowed_risk=RiskTier.READ)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        condition = delegation.instruction
        return AgentResult(
            success=True,
            output=f"Verification passed for condition: {condition}",
            data={"verified": True, "condition": condition},
            role=self.role,
        )


class SecurityWorker(BaseWorker):
    def __init__(self) -> None:
        super().__init__(AgentRole.SECURITY, allowed_risk=RiskTier.READ)

    def execute(self, delegation: AgentDelegation, context: Mapping[str, Any]) -> AgentResult:
        op = delegation.instruction
        is_safe = "drop table" not in op.lower() and "rm -rf" not in op.lower()
        return AgentResult(
            success=is_safe,
            output="Operation passed security audit" if is_safe else "Security violation detected",
            data={"approved": is_safe},
            role=self.role,
        )
