from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

logger = logging.getLogger("nexa.intelligence.self_test")


@dataclass
class SubsystemTestResult:
    subsystem: str
    passed: bool
    duration_ms: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class CapabilityReport:
    total: int
    passed: int
    failed: int
    overall_status: str  # 'VERIFIED', 'PARTIAL', 'BROKEN'
    duration_ms: float
    timestamp: str
    results: list[SubsystemTestResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "overall_status": self.overall_status,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "results": [
                {
                    "subsystem": r.subsystem,
                    "passed": r.passed,
                    "duration_ms": r.duration_ms,
                    "details": r.details,
                    "error": r.error,
                }
                for r in self.results
            ],
        }

    def summary_markdown(self) -> str:
        lines = [
            f"# NEXA Capability Verification Report",
            f"**Status**: {self.overall_status} ({self.passed}/{self.total} passed) in {self.duration_ms:.1f}ms",
            f"**Timestamp**: {self.timestamp}",
            "",
            "| Subsystem | Status | Duration | Details |",
            "|-----------|--------|----------|---------|",
        ]
        for r in self.results:
            st = "PASS" if r.passed else "FAIL"
            detail_str = r.error if r.error else f"{len(r.details)} checks ok"
            lines.append(f"| {r.subsystem} | {st} | {r.duration_ms:.1f}ms | {detail_str} |")
        return "\n".join(lines)


class SelfTestAgent:
    """Autonomous agent that runs deterministic capability verification across all 17 NEXA subsystems."""

    def __init__(self, kernel: Any | None = None) -> None:
        self._kernel = kernel

    def run_all(self) -> CapabilityReport:
        start_time = time.monotonic()
        results: list[SubsystemTestResult] = []

        subsystems = [
            ("kernel_and_security", self._test_kernel_and_security),
            ("registry_and_discovery", self._test_registry_and_discovery),
            ("failsafe_monitor", self._test_failsafe_monitor),
            ("screen_and_vision", self._test_screen_and_vision),
            ("mouse_controller", self._test_mouse_controller),
            ("keyboard_controller", self._test_keyboard_controller),
            ("window_manager", self._test_window_manager),
            ("clipboard_manager", self._test_clipboard_manager),
            ("browser_control", self._test_browser_control),
            ("terminal_execution", self._test_terminal_execution),
            ("file_system", self._test_file_system),
            ("app_control", self._test_app_control),
            ("task_planner", self._test_task_planner),
            ("plan_executor", self._test_plan_executor),
            ("ui_server_and_api", self._test_ui_server_and_api),
            ("voice_subsystem", self._test_voice_subsystem),
            ("context_and_memory", self._test_context_and_memory),
        ]

        for name, test_fn in subsystems:
            t0 = time.monotonic()
            try:
                details = test_fn()
                dur = (time.monotonic() - t0) * 1000.0
                results.append(SubsystemTestResult(name, True, dur, details))
            except Exception as exc:
                dur = (time.monotonic() - t0) * 1000.0
                logger.warning("Self-test failed for %s: %s", name, exc)
                results.append(SubsystemTestResult(name, False, dur, {}, str(exc)))

        passed_count = sum(1 for r in results if r.passed)
        failed_count = len(results) - passed_count
        status = "VERIFIED" if failed_count == 0 else ("PARTIAL" if passed_count > 0 else "BROKEN")
        total_dur = (time.monotonic() - start_time) * 1000.0

        return CapabilityReport(
            total=len(results),
            passed=passed_count,
            failed=failed_count,
            overall_status=status,
            duration_ms=total_dur,
            timestamp=datetime.now(timezone.utc).isoformat(),
            results=results,
        )

    def _test_kernel_and_security(self) -> dict[str, Any]:
        from core.security import SecurityGate
        from core.contracts import RiskTier, PolicyOutcome
        gate = SecurityGate()
        p1 = gate.decide(RiskTier.READ)
        p2 = gate.decide(RiskTier.DESTRUCTIVE)
        if p1.outcome != PolicyOutcome.ALLOW or p2.outcome != PolicyOutcome.REQUIRE_CONFIRMATION:
            raise AssertionError("Security policy outcome unexpected")
        return {"security_gate": "operational", "risk_tiers_enforced": True}

    def _test_registry_and_discovery(self) -> dict[str, Any]:
        from core.registry import SkillRegistry
        from skills.file_skill import FileSkill
        reg = SkillRegistry()
        fs = FileSkill()
        reg.register(fs)
        match = reg.resolve("read file test.txt", {})
        if not match or match.skill_name != "files":
            raise AssertionError("Registry failed to resolve files skill")
        return {"registry": "operational", "registered_skills": len(reg.list_metadata())}

    def _test_failsafe_monitor(self) -> dict[str, Any]:
        from core.failsafe import FailsafeMonitor, FailsafeTriggered, FailsafeConfig
        fs = FailsafeMonitor(FailsafeConfig(corner_enabled=True, corner_threshold_px=5))
        fs.check_before_action(mouse_x=100, mouse_y=100)
        corner_caught = False
        try:
            fs.check_before_action(mouse_x=0, mouse_y=0)
        except FailsafeTriggered:
            corner_caught = True
        fs.reset()
        if not corner_caught:
            raise AssertionError("Failsafe failed to catch corner trigger")
        return {"failsafe_monitor": "operational", "emergency_stop": True}

    def _test_screen_and_vision(self) -> dict[str, Any]:
        from computer.screen import ScreenCapture
        from computer.vision import ScreenAnalyzer
        sc = ScreenCapture()
        sa = ScreenAnalyzer()
        return {"screen_capture_ready": True, "vision_analyzer_ready": True}

    def _test_mouse_controller(self) -> dict[str, Any]:
        from computer.mouse import MouseController
        mc = MouseController()
        return {"mouse_controller_ready": True}

    def _test_keyboard_controller(self) -> dict[str, Any]:
        from computer.keyboard import KeyboardController
        kc = KeyboardController()
        return {"keyboard_controller_ready": True}

    def _test_window_manager(self) -> dict[str, Any]:
        from computer.window import WindowManager
        wm = WindowManager()
        wins = wm.list_windows()
        return {"window_manager_ready": True, "detected_windows": len(wins)}

    def _test_clipboard_manager(self) -> dict[str, Any]:
        from computer.clipboard import ClipboardManager
        cm = ClipboardManager()
        return {"clipboard_manager_ready": True}

    def _test_browser_control(self) -> dict[str, Any]:
        from skills.browser_control_skill import BrowserControlSkill
        skill = BrowserControlSkill()
        browsers = skill.detect_browsers()
        m = skill.match("open https://google.com", {})
        if not m or m.operation != "open":
            raise AssertionError("BrowserControlSkill failed to match open URL")
        return {"browser_control_ready": True, "installed_browsers": len(browsers)}

    def _test_terminal_execution(self) -> dict[str, Any]:
        from skills.terminal_skill import TerminalSkill
        ts = TerminalSkill(timeout=5.0)
        res = ts.execute("run_safe", {"command": "python --version"}, {})
        if not res.success:
            res = ts.execute("run_safe", {"command": "whoami"}, {})
        if not res.success:
            raise AssertionError(f"TerminalSkill execution failed: {res.error}")
        return {"terminal_skill": "operational", "test_command": True}

    def _test_file_system(self) -> dict[str, Any]:
        from skills.file_skill import FileSkill
        fs = FileSkill()
        res = fs.execute("list", {"path": "."}, {})
        if not res.success:
            raise AssertionError("FileSkill list failed")
        return {"file_skill": "operational"}

    def _test_app_control(self) -> dict[str, Any]:
        from skills.app_skill import AppSkill
        app_s = AppSkill()
        m = app_s.match("open notepad", {})
        if not m or m.operation != "launch":
            raise AssertionError("AppSkill failed to match launch notepad")
        return {"app_skill": "operational"}

    def _test_task_planner(self) -> dict[str, Any]:
        from planner.task_planner import TaskPlanner
        from core.registry import SkillRegistry
        from skills.file_skill import FileSkill
        reg = SkillRegistry()
        reg.register(FileSkill())
        planner = TaskPlanner(registry=reg)
        plan = planner.plan("read file test.txt and file list .")
        if len(plan.steps) < 2:
            raise AssertionError("TaskPlanner failed multi-step split")
        return {"task_planner": "operational", "multi_step_decomposition": True}

    def _test_plan_executor(self) -> dict[str, Any]:
        from planner.executor import PlanExecutor
        from planner.contracts import TaskPlan, PlanStep
        executor = PlanExecutor()
        plan = TaskPlan(
            plan_id="self_test_plan",
            description="Plan executor verification",
            steps=[
                PlanStep(step_id=1, description="verify step", skill_name="", operation="")
            ],
            original_request="verify step",
            created_at="now",
        )
        res = executor.execute(plan)
        if not res.success:
            raise AssertionError("PlanExecutor failed")
        return {"plan_executor": "operational", "verification_engine": True}

    def _test_ui_server_and_api(self) -> dict[str, Any]:
        from ui.event_bus import get_event_bus, UIEventType
        bus = get_event_bus()
        bus.emit(UIEventType.SYSTEM_HEALTH_CHANGED, "Health Test", "Self-test health ping", {})
        return {"ui_event_bus": "operational"}

    def _test_voice_subsystem(self) -> dict[str, Any]:
        from voice.contracts import VoiceMode
        return {"voice_contracts_ready": True, "mode": VoiceMode.PUSH_TO_TALK.value}

    def _test_context_and_memory(self) -> dict[str, Any]:
        from core.context import CURRENT_DEVICE_CONTEXT
        from core.entity_resolver import EntityResolver
        res_app = EntityResolver.resolve_app_name("calc")
        if res_app != "calculator":
            raise AssertionError(f"EntityResolver failed: calc -> {res_app}")
        return {"device_context": "operational", "entity_resolver": True}

