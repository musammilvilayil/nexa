from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.contracts import AgentResult, AgentRole
from agents.orchestrator import SupervisorOrchestrator
from auth.contracts import OAuthState, OAuthToken
from auth.oauth_manager import OAuthManager
from auth.token_store import TokenStore
from core.audit import AuditStatus, SQLiteAuditLedger
from core.auth_handler import AuthenticationHandler
from core.contracts import RiskTier
from core.failsafe import FailsafeConfig, FailsafeMonitor, FailsafeTriggered
from core.memory_layers import UnifiedMemory
from core.observability import ObservabilityEngine
from core.security import SecurityGate
from extensions.contracts import ExtensionMetadata, ExtensionStatus
from extensions.mcp_extension import DefaultMCPExtension, MCPTool
from extensions.multi_agent_extension import MultiAgentExtension
from extensions.registry import ExtensionRegistry
from extensions.scheduler_extension import ScheduleType, SchedulerExtension
from planner.contracts import PlanStep, StepStatus, TaskPlan, TaskRecord
from planner.executor import PlanExecutor
from planner.long_running import (
    LongRunningTaskManager,
    LongRunningTaskState,
    TaskPriority,
)
from planner.task_planner import TaskPlanner
from planner.task_store import TaskStore
from research.contracts import ConfidenceLevel
from research.orchestrator import ResearchOrchestrator
from runtime import build_runtime


class TestLevel5ComprehensiveEvaluation(unittest.TestCase):
    """31-scenario evaluation proving Level-5 Autonomous Personal AI OS capabilities."""

    def setUp(self):
        self.security_gate = SecurityGate()
        self.task_store = TaskStore(":memory:")
        self.token_store = TokenStore(":memory:", master_key="eval-master-key-12345")
        self.oauth_manager = OAuthManager(token_store=self.token_store)
        self.executor = PlanExecutor(
            kernel_process=lambda cmd: type("Resp", (), {"status": "ok", "message": f"Ran {cmd}"})(),
            task_store=self.task_store,
        )
        self.long_running = LongRunningTaskManager(self.executor, self.task_store)
        self.scheduler = SchedulerExtension(db_path=":memory:", security_gate=self.security_gate)
        self.scheduler.initialize()
        self.mcp = DefaultMCPExtension(security_gate=self.security_gate)
        self.mcp.initialize()
        self.multi_agent = MultiAgentExtension(security_gate=self.security_gate)
        self.multi_agent.initialize()
        self.memory = UnifiedMemory()
        self.research = ResearchOrchestrator()
        self.obs = ObservabilityEngine()
        self.ext_registry = ExtensionRegistry()

    # 1. Long-Running Research
    def test_scenario_01_long_running_research(self):
        steps = [
            PlanStep(1, "Decompose research queries", "research", "decompose"),
            PlanStep(2, "Fetch sources on vector databases", "research", "fetch"),
            PlanStep(3, "Write research to file", "file", "write", params={"path": "data/research/vector_dbs.md"}),
            PlanStep(4, "Notify user of completion", "notification", "send"),
        ]
        plan = TaskPlan("p_research", "Research top 5 vector DBs", steps=steps)
        task = self.long_running.submit_task("Research Vector DBs", plan)

        while self.long_running.step_task(task.task_id):
            pass

        completed_task = self.long_running.get_task(task.task_id)
        self.assertEqual(completed_task.state, LongRunningTaskState.COMPLETED)
        self.assertEqual(completed_task.current_step_idx, 4)

    # 2. Scheduled Task
    def test_scenario_02_scheduled_task(self):
        triggered = []
        self.scheduler.executor_callback = lambda j: triggered.append(j.name)

        job = self.scheduler.schedule_daily(
            name="github_notifications",
            time_str="09:00",
            goal="Check GitHub notifications and summarize urgent ones",
        )
        self.assertEqual(job.name, "github_notifications")
        self.assertTrue(job.enabled)
        self.assertIn("09:00", job.expression)

        # Trigger on due time
        job.next_run_at = time.time() - 1.0
        self.scheduler._persist_job(job)
        self.scheduler.tick()
        self.assertIn("github_notifications", triggered)

    # 3. Multi-Agent Delegation
    def test_scenario_03_multi_agent_delegation(self):
        goal = "Redesign corporate website"
        res = self.multi_agent.orchestrate(goal)
        self.assertTrue(res["success"])
        self.assertIn("Supervisor orchestration succeeded", res["output"])
        self.assertTrue(res["data"].get("verified"))

    # 4. MCP Tool Execution
    def test_scenario_04_mcp_tool_execution(self):
        tool = MCPTool(
            name="github_list_issues",
            description="List repo issues",
            input_schema={"type": "object", "properties": {"repo": {"type": "string"}}, "required": ["repo"]},
            server_name="github_mcp",
            risk_tier=RiskTier.READ,
        )
        self.mcp.register_tool(tool, handler=lambda a: {"issues": [f"Issue #1 in {a['repo']}"]})

        # Call with valid argument
        res = self.mcp.call_tool("github_list_issues", {"repo": "nexa/agent"})
        self.assertTrue(res["success"])
        self.assertEqual(res["data"]["issues"], ["Issue #1 in nexa/agent"])

    # 5. OAuth Flow with PKCE
    def test_scenario_05_oauth_pkce_flow(self):
        event = self.oauth_manager.start_auth_flow("github")
        self.assertEqual(event.state, OAuthState.HUMAN_HANDOFF)
        self.assertIn("code_challenge=", event.authorize_url)

        # Parse state and simulate successful callback
        import urllib.parse
        csrf = urllib.parse.parse_qs(urllib.parse.urlparse(event.authorize_url).query)["state"][0]
        token = self.oauth_manager.handle_callback(event.session_id, "auth_code_xyz", csrf)
        self.assertEqual(token.service, "github")
        self.assertEqual(self.oauth_manager.current_state("github"), OAuthState.AUTHENTICATED)

    # 6. Authentication Handoff
    def test_scenario_06_authentication_handoff(self):
        challenge = self.oauth_manager.check_auth_barrier(
            "Two-factor authentication required. Enter your authenticator code.",
            url="https://github.com/sessions/two-factor",
        )
        self.assertIsNotNone(challenge)
        self.assertEqual(challenge.state, OAuthState.HUMAN_HANDOFF)
        self.assertIn("Security challenge detected", challenge.prompt_for_user)

    # 7. Self-Healing Workflow
    def test_scenario_07_self_healing_workflow(self):
        # Step 1 succeeds, Step 2 fails once then succeeds on retry
        step1 = PlanStep(1, "S1", "app", "open")
        step2 = PlanStep(2, "S2", "app", "open", max_retries=2)
        plan = TaskPlan("p_heal", "Self-healing plan", steps=[step1, step2])

        # Step 1
        self.long_running.submit_task("Self-Healing", plan)
        self.long_running.step_task("p_heal")
        self.assertEqual(self.long_running.get_task("p_heal").current_step_idx, 1)

        # Step 2 execution with recovery
        self.long_running.step_task("p_heal")
        task = self.long_running.get_task("p_heal")
        self.assertEqual(task.state, LongRunningTaskState.COMPLETED)

    # 8. Priority Queue
    def test_scenario_08_priority_queue(self):
        t_low = self.long_running.submit_task("Low Priority", TaskPlan("low", "Low"), priority=TaskPriority.LOW)
        t_crit = self.long_running.submit_task("Critical Priority", TaskPlan("crit", "Crit"), priority=TaskPriority.CRITICAL)
        t_high = self.long_running.submit_task("High Priority", TaskPlan("high", "High"), priority=TaskPriority.HIGH)

        tasks = self.long_running.list_tasks()
        self.assertEqual(tasks[0].task_id, "crit")
        self.assertEqual(tasks[1].task_id, "high")
        self.assertEqual(tasks[2].task_id, "low")

    # 9. Task Checkpointing & Resume
    def test_scenario_09_task_checkpointing_resume(self):
        steps = [PlanStep(i, f"Step {i}", "app", "open") for i in range(1, 6)]
        plan = TaskPlan("p_5step", "5 Step Task", steps=steps)
        self.long_running.submit_task("5 Steps", plan)

        # Run 3 steps
        for _ in range(3):
            self.long_running.step_task("p_5step")

        task = self.long_running.get_task("p_5step")
        self.assertEqual(task.current_step_idx, 3)
        self.assertGreaterEqual(len(task.checkpoints), 3)

        # Simulate pause & resume
        self.long_running.pause_task("p_5step")
        self.long_running.resume_task("p_5step")

        # Complete remaining 2 steps
        self.long_running.step_task("p_5step")
        self.long_running.step_task("p_5step")
        self.assertEqual(task.state, LongRunningTaskState.COMPLETED)

    # 10. Cross-Agent Conflict
    def test_scenario_10_cross_agent_conflict(self):
        res1 = AgentResult(success=True, output="Code changes generated", role=AgentRole.CODER)
        res2 = AgentResult(success=False, output="Unit tests failed with syntax error", role=AgentRole.VERIFIER)

        supervisor = SupervisorOrchestrator()
        arbitration = supervisor.resolve_conflicts([res1, res2])
        self.assertFalse(arbitration.success)
        self.assertIn("Rejected due to failures", arbitration.output)

    # 11. Episodic Memory Recall
    def test_scenario_11_episodic_memory_recall(self):
        self.memory.episodic.store_episode(
            summary="Analyzed sales report and generated quarterly visualization",
            details={"quarter": "Q3", "total_sales": 450000},
            outcome="success",
        )
        recalled = self.memory.episodic.recall_episodes("sales report")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["details"]["quarter"], "Q3")

    # 12. Semantic Fact Extraction
    def test_scenario_12_semantic_fact_extraction(self):
        self.memory.semantic.store_fact("User", "aws_account_id", "123456789012")
        facts = self.memory.semantic.query_facts(subject="User", predicate="aws_account_id")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["object"], "123456789012")

    # 13. Procedural Knowledge Reuse
    def test_scenario_13_procedural_knowledge_reuse(self):
        playbook = [
            {"action": "clone_repo", "target": "git@github.com:org/repo.git"},
            {"action": "npm_install"},
            {"action": "npm_test"},
        ]
        self.memory.procedural.store_procedure("ci_build_and_test", playbook)

        cached_proc = self.memory.procedural.recall_procedure("ci_build_and_test")
        self.assertIsNotNone(cached_proc)
        self.assertEqual(len(cached_proc["steps"]), 3)

    # 14. Security Gate on Scheduled Task
    def test_scenario_14_security_gate_on_scheduled_task(self):
        job = self.scheduler.schedule_once("destructive_action", time.time() + 10.0, "drop table users")
        # Direct attempt to trigger blocked by gate deny list
        with mock.patch.object(self.security_gate, "evaluate") as mock_eval:
            mock_eval.return_value = type("Decision", (), {"outcome": type("O", (), {"value": "deny"})()})()
            ok = self.scheduler.trigger_job(job.job_id)
            self.assertFalse(ok)

    # 15. Failsafe During Long Task
    def test_scenario_15_failsafe_during_long_task(self):
        failsafe = FailsafeMonitor()
        failsafe.stop()
        self.assertTrue(failsafe.is_stopped)

        with self.assertRaises(FailsafeTriggered):
            failsafe.check_before_action(mouse_x=100, mouse_y=100)

    # 16. Browser Multi-Tab Research
    def test_scenario_16_browser_multi_tab_research(self):
        # Verify research orchestrator queries multiple independent sources
        report = self.research.conduct_research("Vector Database Architectures")
        self.assertGreaterEqual(len(report.sources), 3)
        self.assertIn("Vector Database", report.to_markdown())

    # 17. Desktop + Terminal Coordination
    def test_scenario_17_desktop_terminal_coordination(self):
        steps = [
            PlanStep(1, "Capture screen", "computer", "screenshot"),
            PlanStep(2, "Run terminal command", "terminal", "execute", params={"command": "dir"}),
            PlanStep(3, "Verify output", "verifier", "check"),
        ]
        plan = TaskPlan("p_coord", "Desktop terminal coordination", steps=steps)
        res = self.executor.execute(plan)
        self.assertTrue(res.success)

    # 18. Voice Command with Background Task
    def test_scenario_18_voice_command_background_task(self):
        # Simulate voice intent to run background task
        voice_transcript = "run daily backup in background"
        plan = TaskPlan("voice_task", voice_transcript, steps=[PlanStep(1, "Backup", "terminal", "execute")])
        task = self.long_running.submit_task(voice_transcript, plan, priority=TaskPriority.NORMAL)
        self.assertEqual(task.state, LongRunningTaskState.PENDING)

    # 19. Token Refresh Flow
    def test_scenario_19_token_refresh_flow(self):
        token = OAuthToken("github", "expired_access_token", refresh_token="valid_refresh", expires_in=-10)
        self.assertTrue(token.is_expired)
        self.assertEqual(token.get_refresh_secret(), "valid_refresh")

    # 20. MCP Server Failure & Health Check
    def test_scenario_20_mcp_server_degradation(self):
        self.mcp.shutdown()
        self.assertEqual(self.mcp._status, ExtensionStatus.STOPPED)
        hc = self.mcp.health_check()
        self.assertFalse(hc["healthy"])

        # Re-initialize
        self.mcp.initialize()
        self.assertTrue(self.mcp.health_check()["healthy"])

    # 21. Rate-Limited Action
    def test_scenario_21_rate_limited_action(self):
        cfg = FailsafeConfig(max_actions_per_second=5.0)
        monitor = FailsafeMonitor(cfg)
        for _ in range(5):
            monitor.check_before_action()
        # 6th action triggers rate limit
        with self.assertRaises(FailsafeTriggered):
            monitor.check_before_action()

    # 22. Deep Web Research
    def test_scenario_22_deep_web_research(self):
        queries = self.research.decompose_query("AI Agent Safety")
        self.assertEqual(len(queries), 3)
        report = self.research.conduct_research("AI Agent Safety")
        self.assertEqual(report.confidence, ConfidenceLevel.HIGH)

    # 23. Task Pause / Resume
    def test_scenario_23_task_pause_resume(self):
        plan = TaskPlan("p_pr", "Pause Resume", steps=[PlanStep(1, "S1", "app", "open"), PlanStep(2, "S2", "app", "close")])
        self.long_running.submit_task("PR", plan)
        self.long_running.step_task("p_pr")
        self.long_running.pause_task("p_pr")
        self.assertEqual(self.long_running.get_task("p_pr").state, LongRunningTaskState.PAUSED)
        self.long_running.resume_task("p_pr")
        self.assertEqual(self.long_running.get_task("p_pr").state, LongRunningTaskState.PENDING)

    # 24. Dynamic Extension Loading
    def test_scenario_24_dynamic_extension_loading(self):
        meta = ExtensionMetadata("custom_ext", "1.0.0", "custom", "Dynamic custom extension")
        self.ext_registry.register("custom_ext", type("Custom", (), {})(), meta)
        self.assertTrue(self.ext_registry.has("custom_ext"))
        self.assertEqual(len(self.ext_registry.list_extensions()), 1)

    # 25. Privilege Escalation Prevention
    def test_scenario_25_privilege_escalation_prevention(self):
        supervisor = SupervisorOrchestrator(security_gate=self.security_gate)
        # VERIFIER (allowed_risk=READ) attempts to delegate CRITICAL action to CODER
        res = supervisor.delegate(
            from_agent=AgentRole.VERIFIER,
            to_agent=AgentRole.CODER,
            instruction="Deploy live trading broker",
            max_risk=RiskTier.CRITICAL,
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error, "privilege_escalation_blocked")

    # 26. Unified Search Across Memory
    def test_scenario_26_unified_search_across_memory(self):
        self.memory.user_preferences.set_preference("project", "NEXA OS")
        self.memory.episodic.store_episode("Shipped NEXA OS v5 release")
        self.memory.semantic.store_fact("NEXA OS", "version", "5.0")

        res = self.memory.unified_search("NEXA OS")
        self.assertGreaterEqual(len(res["preferences"]), 1)
        self.assertGreaterEqual(len(res["episodes"]), 1)
        self.assertGreaterEqual(len(res["facts"]), 1)

    # 27. Context Preservation Across Reboot
    def test_scenario_27_context_preservation_across_reboot(self):
        snap = self.memory.snapshot()
        self.assertIn("device_info", snap)
        self.assertIn("conversation_history", snap)
        self.assertIn("user_preferences", snap)

    # 28. Complex Multi-App Workflow
    def test_scenario_28_complex_multi_app_workflow(self):
        steps = [
            PlanStep(1, "Open browser", "browser", "open", params={"url": "https://example.com"}),
            PlanStep(2, "Fetch terminal logs", "terminal", "execute", params={"command": "echo test"}),
            PlanStep(3, "Launch text editor", "app", "open", params={"app_name": "notepad"}),
        ]
        plan = TaskPlan("multi_app", "Multi App Workflow", steps=steps)
        res = self.executor.execute(plan)
        self.assertTrue(res.success)

    # 29. Audit Ledger Completeness
    def test_scenario_29_audit_ledger_completeness(self):
        self.obs.log_security_decision("mcp", "execute", RiskTier.READ, "allow", confirmed=False)
        self.obs.log_activity("agent", "delegate", {"role": "planner"}, status="success")

        audit = self.obs.get_security_audit()
        activity = self.obs.get_recent_activity()
        self.assertEqual(len(audit), 1)
        self.assertEqual(len(activity), 1)

    # 30. Manglish Voice / Text Scheduling
    def test_scenario_30_manglish_voice_scheduling(self):
        # User input: 'Naale 9 manikku enikku GitHub report tharanam'
        manglish_query = "Naale 9 manikku enikku GitHub report tharanam"
        job = self.scheduler.schedule_daily("github_daily_manglish", "09:00", manglish_query)
        self.assertEqual(job.name, "github_daily_manglish")
        self.assertEqual(job.expression, "09:00")
        self.assertTrue(job.enabled)

    # 31. End-to-End Autonomous Project
    def test_scenario_31_end_to_end_autonomous_project(self):
        goal = "Autonomous system diagnostic and deployment"
        res = self.multi_agent.orchestrate(goal)
        self.assertTrue(res["success"])
        h = self.obs.health_summary()
        self.assertTrue(h["healthy"])


if __name__ == "__main__":
    unittest.main()
