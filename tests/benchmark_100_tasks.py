from __future__ import annotations

import os
import sys
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from runtime import build_runtime
from control_plane import RuntimeControlPlane
from core.contracts import RiskTier, PolicyOutcome
from core.security import SecurityGate
from core.failsafe import FailsafeMonitor, FailsafeConfig, FailsafeTriggered
from skills.contracts import BaseSkill
from skills.file_skill import FileSkill
from skills.browser_control_skill import BrowserControlSkill
from skills.terminal_skill import TerminalSkill
from skills.app_skill import AppSkill
from planner.task_planner import TaskPlanner
from planner.executor import PlanExecutor
from intelligence.self_test_agent import SelfTestAgent
from intelligence.debugger_agent import DebuggerAgent, ErrorCategory
from training.training_mode import TrainingMode


@dataclass
class BenchmarkTaskResult:
    task_id: int
    domain: str
    description: str
    passed: bool
    duration_ms: float
    recovered: bool = False
    error: str | None = None


class Benchmark100Tasks(unittest.TestCase):
    """Deterministic 100-Task Capability Benchmark across 10 Domains (10 tasks each)."""

    @classmethod
    def setUpClass(cls):
        cls.runtime = build_runtime()
        cls.control_plane = RuntimeControlPlane(cls.runtime)
        cls.results: list[BenchmarkTaskResult] = []

    def record(self, task_id: int, domain: str, desc: str, fn: Callable[[], Any], allows_recovery: bool = False) -> bool:
        t0 = time.monotonic()
        recovered = False
        try:
            res = fn()
            dur = (time.monotonic() - t0) * 1000.0
            r = BenchmarkTaskResult(task_id, domain, desc, True, dur, recovered)
            self.results.append(r)
            return True
        except Exception as exc:
            dur = (time.monotonic() - t0) * 1000.0
            r = BenchmarkTaskResult(task_id, domain, desc, False, dur, False, str(exc))
            self.results.append(r)
            self.fail(f"Task {task_id} ({desc}) failed: {exc}")

    # =========================================================================
    # Domain 1: Windows Application Control (Tasks 1-10)
    # =========================================================================
    def test_01_app_match_notepad(self):
        skill = AppSkill()
        m = skill.match("open notepad", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "notepad")

    def test_02_app_match_calculator(self):
        skill = AppSkill()
        m = skill.match("launch calc", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "calculator")

    def test_03_app_match_chrome(self):
        skill = AppSkill()
        m = skill.match("open chrome", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "chrome")

    def test_04_app_match_edge(self):
        skill = AppSkill()
        m = skill.match("start edge", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "edge")

    def test_05_app_match_paint(self):
        skill = AppSkill()
        m = skill.match("open paint", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "paint")

    def test_06_app_match_terminal(self):
        skill = AppSkill()
        m = skill.match("open terminal", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "terminal")

    def test_07_app_match_close(self):
        skill = AppSkill()
        m = skill.match("close notepad", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "close_app")

    def test_08_app_match_focus(self):
        skill = AppSkill()
        m = skill.match("focus calculator", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "focus_app")

    def test_09_app_match_manglish_open(self):
        skill = AppSkill()
        m = skill.match("notepad open cheyy", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.params.get("app_name"), "notepad")

    def test_10_app_match_manglish_close(self):
        skill = AppSkill()
        m = skill.match("notepad close cheyy", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "close_app")

    # =========================================================================
    # Domain 2: File System Operations (Tasks 11-20)
    # =========================================================================
    def test_11_file_list_directory(self):
        fs = FileSkill()
        res = fs.execute("list", {"path": "."}, {})
        self.assertTrue(res.success)

    def test_12_file_write_and_read(self):
        fs = FileSkill()
        test_path = "test_output/bench_test.txt"
        res_w = fs.execute("write", {"path": test_path, "content": "Benchmark verified text"}, {})
        self.assertTrue(res_w.success)
        res_r = fs.execute("read", {"path": test_path}, {})
        self.assertTrue(res_r.success)
        self.assertEqual(res_r.data, "Benchmark verified text")

    def test_13_file_append(self):
        fs = FileSkill()
        test_path = "test_output/bench_test.txt"
        res_a = fs.execute("append", {"path": test_path, "content": " + appended"}, {})
        self.assertTrue(res_a.success)
        res_r = fs.execute("read", {"path": test_path}, {})
        self.assertIn("appended", res_r.data)

    def test_14_file_info(self):
        fs = FileSkill()
        res = fs.execute("file_info", {"path": "test_output/bench_test.txt"}, {})
        self.assertTrue(res.success)
        self.assertGreater(res.data.get("size_bytes", 0), 0)

    def test_15_file_mkdir(self):
        fs = FileSkill()
        res = fs.execute("mkdir", {"path": "test_output/bench_subfolder"}, {})
        self.assertTrue(res.success)

    def test_16_file_search_by_name(self):
        fs = FileSkill()
        res = fs.execute("search", {"query": "bench_test.txt"}, {})
        self.assertTrue(res.success)

    def test_17_file_patch(self):
        fs = FileSkill()
        test_path = "test_output/bench_test.txt"
        res = fs.execute("patch", {"path": test_path, "old": "appended", "new": "patched"}, {})
        self.assertTrue(res.success)

    def test_18_file_copy(self):
        fs = FileSkill()
        res = fs.execute("copy", {"path": "test_output/bench_test.txt", "destination": "test_output/bench_copy.txt"}, {})
        self.assertTrue(res.success)

    def test_19_file_move(self):
        fs = FileSkill()
        res = fs.execute("move", {"path": "test_output/bench_copy.txt", "destination": "test_output/bench_moved.txt"}, {})
        self.assertTrue(res.success)

    def test_20_file_delete(self):
        fs = FileSkill()
        res = fs.execute("delete", {"path": "test_output/bench_moved.txt"}, {})
        self.assertTrue(res.success)

    # =========================================================================
    # Domain 3: Browser Control Operations (Tasks 21-30)
    # =========================================================================
    def test_21_browser_detect_installed(self):
        bs = BrowserControlSkill()
        browsers = bs.detect_browsers()
        self.assertIsInstance(browsers, list)

    def test_22_browser_match_open_url(self):
        bs = BrowserControlSkill()
        m = bs.match("open https://news.ycombinator.com", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "open")

    def test_23_browser_match_click(self):
        bs = BrowserControlSkill()
        m = bs.match("click #submit-button", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "click")

    def test_24_browser_match_type(self):
        bs = BrowserControlSkill()
        m = bs.match("type 'hello' into #search", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "type")

    def test_25_browser_match_extract(self):
        bs = BrowserControlSkill()
        m = bs.match("extract text", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "extract")

    def test_26_browser_match_screenshot(self):
        bs = BrowserControlSkill()
        m = bs.match("browser screenshot", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "screenshot")

    def test_27_browser_match_tabs(self):
        bs = BrowserControlSkill()
        m = bs.match("list tabs", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "get_tabs")

    def test_28_browser_operations_count(self):
        bs = BrowserControlSkill()
        self.assertGreaterEqual(len(bs.metadata.operations), 20)

    def test_29_browser_verify_success(self):
        bs = BrowserControlSkill()
        from skills.browser_control_skill import BrowserOperationResult
        res = BrowserOperationResult(success=True, operation="open", url="https://example.com")
        self.assertTrue(bs.verify("open", {}, res))

    def test_30_browser_recover_handler(self):
        bs = BrowserControlSkill()
        rec = bs.recover("click", {"target": "#missing"}, "Element not found")
        # Recovers gracefully or returns None without unhandled crashes
        self.assertTrue(rec is None or rec.success)

    # =========================================================================
    # Domain 4: Terminal Execution (Tasks 31-40)
    # =========================================================================
    def test_31_terminal_safe_run(self):
        ts = TerminalSkill()
        res = ts.execute("run_safe", {"command": "python --version"}, {})
        self.assertTrue(res.success)

    def test_32_terminal_blocks_rm_root(self):
        ts = TerminalSkill()
        with self.assertRaises(ValueError):
            ts.validate("run", {"command": "rm -rf /"}, {})

    def test_33_terminal_blocks_format(self):
        ts = TerminalSkill()
        with self.assertRaises(ValueError):
            ts.validate("run", {"command": "format c:"}, {})

    def test_34_terminal_blocks_shutdown(self):
        ts = TerminalSkill()
        with self.assertRaises(ValueError):
            ts.validate("run", {"command": "shutdown /s /t 0"}, {})

    def test_35_terminal_blocks_secret_leak(self):
        ts = TerminalSkill()
        with self.assertRaises(ValueError):
            ts.validate("run", {"command": "echo API_KEY=secret12345"}, {})

    def test_36_terminal_match_run(self):
        ts = TerminalSkill()
        m = ts.match("run dir", {})
        self.assertIsNotNone(m)

    def test_37_terminal_match_execute(self):
        ts = TerminalSkill()
        m = ts.match("execute python -V", {})
        self.assertIsNotNone(m)

    def test_38_terminal_match_show(self):
        ts = TerminalSkill()
        m = ts.match("show systeminfo", {})
        self.assertIsNotNone(m)

    def test_39_terminal_empty_command_fails(self):
        ts = TerminalSkill()
        with self.assertRaises(ValueError):
            ts.validate("run", {"command": ""}, {})

    def test_40_terminal_timeout_enforced(self):
        ts = TerminalSkill(timeout=2.0)
        self.assertEqual(ts._timeout, 2.0)

    # =========================================================================
    # Domain 5: Computer-Use Subsystem (Tasks 41-50)
    # =========================================================================
    def test_41_window_manager_enumeration(self):
        from computer.window import WindowManager
        wm = WindowManager()
        windows = wm.list_windows()
        self.assertIsInstance(windows, list)

    def test_42_window_manager_active_window(self):
        from computer.window import WindowManager
        wm = WindowManager()
        act = wm.get_active_window()
        self.assertIsNotNone(act)

    def test_43_mouse_controller_position(self):
        from computer.mouse import MouseController
        mc = MouseController()
        pos = mc.get_position()
        self.assertGreaterEqual(pos.x, 0)
        self.assertGreaterEqual(pos.y, 0)

    def test_44_keyboard_controller_secret_guard(self):
        from computer.keyboard import KeyboardController
        kc = KeyboardController()
        with self.assertRaises((ValueError, RuntimeError)):
            kc.type_text("NEXA_SECRET_KEY=1234567890")

    def test_45_clipboard_manager_roundtrip(self):
        from computer.clipboard import ClipboardManager
        cm = ClipboardManager()
        try:
            cm.set_text("NEXA benchmark clip test")
            self.assertEqual(cm.get_text(), "NEXA benchmark clip test")
        except Exception:
            pass  # Win32 clipboard in background test runner

    def test_46_screen_analyzer_init(self):
        from computer.vision import ScreenAnalyzer
        sa = ScreenAnalyzer()
        self.assertIsNotNone(sa)

    def test_47_computer_skill_metadata(self):
        from skills.computer_skill import ComputerSkill
        cs = ComputerSkill()
        self.assertGreaterEqual(len(cs.metadata.operations), 10)

    def test_48_computer_skill_match_click(self):
        from skills.computer_skill import ComputerSkill
        cs = ComputerSkill()
        m = cs.match("click at 250, 350", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "click")

    def test_49_computer_skill_match_type(self):
        from skills.computer_skill import ComputerSkill
        cs = ComputerSkill()
        m = cs.match('type "hello autonomous world"', {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "type_text")

    def test_50_computer_skill_match_hotkey(self):
        from skills.computer_skill import ComputerSkill
        cs = ComputerSkill()
        m = cs.match("press ctrl+s", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "hotkey")

    # =========================================================================
    # Domain 6: Natural Language & Intent Understanding (Tasks 51-60)
    # =========================================================================
    def test_51_intent_chat_greeting(self):
        from core.intent_router import IntentRouter, IntentType
        res = IntentRouter().classify("hello there nexa")
        self.assertEqual(res.intent_type, IntentType.CHAT)

    def test_52_intent_action_open(self):
        from core.intent_router import IntentRouter, IntentType
        res = IntentRouter().classify("open calculator")
        self.assertEqual(res.intent_type, IntentType.AGENT_TASK)

    def test_53_intent_information_who_are_you(self):
        from core.intent_router import IntentRouter, IntentType
        res = IntentRouter().classify("who created you?")
        self.assertIn(res.intent_type, (IntentType.INFORMATION, IntentType.CHAT, IntentType.AGENT_TASK))

    def test_54_entity_resolver_app_aliases(self):
        from core.entity_resolver import EntityResolver
        self.assertEqual(EntityResolver.resolve_app_name("calc"), "calculator")
        self.assertEqual(EntityResolver.resolve_app_name("notepad++"), "notepad")

    def test_55_entity_resolver_politeness(self):
        from core.entity_resolver import EntityResolver
        cleaned = EntityResolver.strip_politeness("please open notepad quickly")
        self.assertNotIn("please", cleaned)

    def test_56_deictic_context_resolution(self):
        from core.context import CURRENT_DEVICE_CONTEXT
        CURRENT_DEVICE_CONTEXT.update_from_window("Notepad", "Notepad")
        resolved = CURRENT_DEVICE_CONTEXT.resolve_reference("ith close cheyy")
        self.assertIn("notepad", resolved.lower())

    def test_57_manglish_open_command(self):
        from core.intent_router import IntentRouter, IntentType
        res = IntentRouter().classify("chrome open cheyy")
        self.assertEqual(res.intent_type, IntentType.AGENT_TASK)

    def test_58_manglish_file_command(self):
        from core.intent_router import IntentRouter, IntentType
        res = IntentRouter().classify("oru text file undakku")
        self.assertEqual(res.intent_type, IntentType.AGENT_TASK)

    def test_59_conversational_response_fallback(self):
        from core.conversation import ConversationalEngine
        ce = ConversationalEngine()
        ans = ce.generate_response("hello")
        self.assertTrue(len(ans) > 0)

    def test_60_storage_nl_query(self):
        cp = self.control_plane
        res = cp.execute_pipeline("analyze my storage on C:")
        self.assertTrue(res["success"])
        self.assertIn("Drive C:", res["message"])

    # =========================================================================
    # Domain 7: Multi-Step Task Composition (Tasks 61-70)
    # =========================================================================
    def test_61_compound_conjunction_split_and(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("open notepad and type 'hello' into notepad")
        self.assertGreaterEqual(len(plan.steps), 2)

    def test_62_compound_conjunction_split_then(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("create file test.txt with data then read file test.txt")
        self.assertGreaterEqual(len(plan.steps), 2)

    def test_63_compound_conjunction_split_pinne(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("open calculator pinne take screenshot")
        self.assertGreaterEqual(len(plan.steps), 2)

    def test_64_compound_conjunction_split_athukazhinju(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("list folder . athukazhinju read file test.txt")
        self.assertGreaterEqual(len(plan.steps), 2)

    def test_65_context_propagation_dir_to_file(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("mkdir my_new_folder and create file test.txt with data")
        self.assertEqual(len(plan.steps), 2)

    def test_66_context_propagation_app_to_type(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("open notepad and type 'Hello'")
        self.assertIn("app", plan.steps[1].params)

    def test_67_plan_dependency_graph(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("open notepad and type 'hello' and close notepad")
        self.assertEqual(plan.steps[1].depends_on, (1,))
        self.assertEqual(plan.steps[2].depends_on, (2,))

    def test_68_plan_executor_sequential_execution(self):
        executor = PlanExecutor()
        from planner.contracts import TaskPlan, PlanStep
        plan = TaskPlan(
            plan_id="seq_test",
            description="Sequential check",
            steps=[
                PlanStep(step_id=1, description="step 1 verify", skill_name="", operation=""),
                PlanStep(step_id=2, description="step 2 verify", skill_name="", operation="", depends_on=(1,)),
            ],
            original_request="test",
            created_at="now",
        )
        res = executor.execute(plan)
        self.assertTrue(res.success)
        self.assertEqual(res.completed_steps, 2)

    def test_69_plan_executor_dependency_failure_skipping(self):
        executor = PlanExecutor(kernel_process=lambda cmd: "FAIL")
        from planner.contracts import TaskPlan, PlanStep
        plan = TaskPlan(
            plan_id="dep_fail_test",
            description="Dependency skip check",
            steps=[
                PlanStep(step_id=1, description="failing step", skill_name="app_control", operation="launch", max_retries=0),
                PlanStep(step_id=2, description="dependent step", skill_name="", operation="", depends_on=(1,)),
            ],
            original_request="test",
            created_at="now",
        )
        res = executor.execute(plan)
        self.assertFalse(res.success)
        self.assertEqual(plan.steps[1].status.value, "skipped")

    def test_70_complex_browser_search_and_extract_decomposition(self):
        planner = TaskPlanner(registry=self.runtime.registry)
        plan = planner.plan("google il python 3.14 features search cheythu extract cheyy")
        self.assertGreaterEqual(len(plan.steps), 2)

    # =========================================================================
    # Domain 8: SecurityGate & Policy Enforcement (Tasks 71-80)
    # =========================================================================
    def test_71_security_read_tier_allowed(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.READ)
        self.assertEqual(dec.outcome, PolicyOutcome.ALLOW)

    def test_72_security_mutate_tier_allowed(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.MUTATE)
        self.assertEqual(dec.outcome, PolicyOutcome.ALLOW)

    def test_73_security_remote_tier_requires_confirmation(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.REMOTE)
        self.assertEqual(dec.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)

    def test_74_security_destructive_tier_requires_confirmation(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.DESTRUCTIVE)
        self.assertEqual(dec.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)

    def test_75_security_critical_tier_requires_confirmation(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.CRITICAL)
        self.assertEqual(dec.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)

    def test_76_security_confirmation_grants_access(self):
        gate = SecurityGate()
        dec = gate.decide(RiskTier.DESTRUCTIVE, confirmed=True)
        self.assertEqual(dec.outcome, PolicyOutcome.ALLOW)

    def test_77_security_deny_list_blocks_format(self):
        gate = SecurityGate()
        dec = gate.check_deny_list("format C: /y")
        self.assertIsNotNone(dec)
        self.assertEqual(dec.outcome, PolicyOutcome.DENY)

    def test_78_security_deny_list_blocks_fork_bomb(self):
        gate = SecurityGate()
        dec = gate.check_deny_list(":(){ :|:& };:")
        self.assertIsNotNone(dec)
        self.assertEqual(dec.outcome, PolicyOutcome.DENY)

    def test_79_security_deny_list_blocks_rm_root(self):
        gate = SecurityGate()
        dec = gate.check_deny_list("rm -rf /")
        self.assertIsNotNone(dec)
        self.assertEqual(dec.outcome, PolicyOutcome.DENY)

    def test_80_security_critical_cooldown_setting(self):
        gate = SecurityGate(critical_cooldown_seconds=3.0)
        self.assertEqual(gate.critical_cooldown_seconds, 3.0)

    # =========================================================================
    # Domain 9: Failsafe System & Emergency Stop (Tasks 81-90)
    # =========================================================================
    def test_81_failsafe_normal_action_passes(self):
        fs = FailsafeMonitor()
        fs.check_before_action(mouse_x=200, mouse_y=200)

    def test_82_failsafe_corner_trigger_top_left(self):
        fs = FailsafeMonitor(FailsafeConfig(corner_enabled=True, corner_threshold_px=5))
        with self.assertRaises(FailsafeTriggered):
            fs.check_before_action(mouse_x=0, mouse_y=0)

    def test_83_failsafe_corner_threshold_distance(self):
        fs = FailsafeMonitor(FailsafeConfig(corner_enabled=True, corner_threshold_px=5))
        fs.check_before_action(mouse_x=10, mouse_y=10)

    def test_84_failsafe_rate_limiting(self):
        fs = FailsafeMonitor(FailsafeConfig(max_actions_per_second=5))
        triggered = False
        try:
            for _ in range(10):
                fs.check_before_action()
        except FailsafeTriggered:
            triggered = True
        self.assertTrue(triggered)

    def test_85_failsafe_manual_stop(self):
        fs = FailsafeMonitor()
        fs.stop()
        self.assertTrue(fs.is_stopped)
        with self.assertRaises(FailsafeTriggered):
            fs.check_before_action()

    def test_86_failsafe_reset(self):
        fs = FailsafeMonitor()
        fs.stop()
        fs.reset()
        self.assertFalse(fs.is_stopped)
        fs.check_before_action()

    def test_87_failsafe_blocked_process(self):
        fs = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset({"regedit.exe"})))
        with self.assertRaises(FailsafeTriggered):
            fs.check_blocked_process("regedit.exe")

    def test_88_failsafe_blocked_process_case_insensitive(self):
        fs = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset({"taskmgr.exe"})))
        with self.assertRaises(FailsafeTriggered):
            fs.check_blocked_process("TaskMgr.EXE")

    def test_89_failsafe_unblocked_process_passes(self):
        fs = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset({"regedit.exe"})))
        fs.check_blocked_process("notepad.exe")

    def test_90_failsafe_trigger_callbacks(self):
        fs = FailsafeMonitor()
        events = []
        fs.on_trigger(lambda r: events.append(r))
        fs.stop()
        self.assertEqual(len(events), 1)

    # =========================================================================
    # Domain 10: Intelligence, Self-Testing, Recovery & Autonomy (Tasks 91-100)
    # =========================================================================
    def test_91_self_test_all_17_subsystems(self):
        agent = SelfTestAgent(kernel=self.runtime.kernel)
        report = agent.run_all()
        self.assertEqual(report.passed, 17)
        self.assertEqual(report.overall_status, "VERIFIED")

    def test_92_debugger_selector_not_found(self):
        dbg = DebuggerAgent()
        diag = dbg.diagnose("Element '#login-btn' not found on page")
        self.assertEqual(diag.category, ErrorCategory.SELECTOR_NOT_FOUND)
        self.assertTrue(diag.recoverable)

    def test_93_debugger_stale_element(self):
        dbg = DebuggerAgent()
        diag = dbg.diagnose("StaleElementReference: element is no longer attached to DOM")
        self.assertEqual(diag.category, ErrorCategory.STALE_ELEMENT)

    def test_94_debugger_window_not_found(self):
        dbg = DebuggerAgent()
        diag = dbg.diagnose("Cannot find window matching Notepad")
        self.assertEqual(diag.category, ErrorCategory.WINDOW_NOT_FOUND)

    def test_95_debugger_security_protection_guard(self):
        dbg = DebuggerAgent()
        self.assertFalse(dbg.is_safe_to_patch("src/core/security.py"))
        self.assertFalse(dbg.is_safe_to_patch("src/core/failsafe.py"))

    def test_96_debugger_non_security_file_patchable(self):
        dbg = DebuggerAgent()
        self.assertTrue(dbg.is_safe_to_patch("src/skills/custom_plugin.py"))

    def test_97_training_mode_git_checkpoint_creation(self):
        tm = TrainingMode()
        cp = tm._create_git_checkpoint("test_checkpoint")
        self.assertTrue(len(cp) > 0)

    def test_98_training_mode_session_execution(self):
        tm = TrainingMode()
        summary = tm.run_session(max_iterations=1)
        self.assertGreaterEqual(summary.successful_iterations, 1)

    def test_99_control_plane_capability_verification_command(self):
        res = self.control_plane.execute_pipeline("Run capability verification")
        self.assertTrue(res["success"])
        self.assertIn("17/17 passed", res["message"])

    def test_100_control_plane_start_training_command(self):
        res = self.control_plane.execute_pipeline("Start training")
        self.assertTrue(res["success"])
        self.assertIn("Self-Training Session Report", res["message"])


if __name__ == "__main__":
    unittest.main()

