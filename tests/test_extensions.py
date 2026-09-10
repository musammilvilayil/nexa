from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from extensions.contracts import (
    CloudExtension,
    DatabaseExtension,
    DiscordExtension,
    ExtensionMetadata,
    ExtensionStatus,
    GitHubExtension,
    GmailExtension,
    GoogleDriveExtension,
    MCPExtension,
    MultiAgentExtension,
    NotionExtension,
    SchedulerExtension,
    SlackExtension,
)
from extensions.registry import ExtensionRegistry


class DummyMCPExtension:
    def connect(self, server_params: dict[str, Any]) -> bool:
        return True

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "read_doc"}]

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"result": "ok"}

    def list_resources(self) -> list[dict[str, Any]]:
        return []

    def is_available(self) -> bool:
        return True


class DummySchedulerExtension:
    def schedule_task(self, task_id: str, cron_or_delay: str, task_payload: dict[str, Any]) -> bool:
        return True

    def cancel_task(self, task_id: str) -> bool:
        return True

    def list_scheduled(self) -> list[dict[str, Any]]:
        return []

    def is_available(self) -> bool:
        return True


class DummyMultiAgentExtension:
    def spawn_agent(self, role: str, goal: str) -> str:
        return "subagent_123"

    def send_message(self, agent_id: str, message: str) -> None:
        pass

    def wait_for_completion(self, agent_id: str, timeout_seconds: float = 60.0) -> dict[str, Any]:
        return {"status": "success"}

    def is_available(self) -> bool:
        return True


class ExtensionsTests(unittest.TestCase):
    def test_extension_registry_lifecycle(self):
        reg = ExtensionRegistry()
        mcp = DummyMCPExtension()
        meta_mcp = ExtensionMetadata(
            name="mcp",
            version="1.0.0",
            category="protocol",
            description="MCP Client",
            status=ExtensionStatus.INITIALIZED,
            supported_operations=("call_tool", "list_tools"),
        )
        reg.register("mcp", mcp, meta_mcp)
        self.assertTrue(reg.has("mcp"))
        self.assertEqual(reg.get("mcp"), mcp)
        self.assertEqual(reg.get_metadata("mcp").version, "1.0.0")

        # Duplicate without replace raises
        with self.assertRaises(ValueError):
            reg.register("mcp", mcp, meta_mcp)

        # Update status
        self.assertTrue(reg.update_status("mcp", ExtensionStatus.ACTIVE))
        self.assertEqual(reg.get_metadata("mcp").status, ExtensionStatus.ACTIVE)

        # Filter by category
        by_cat = reg.list_extensions(category="protocol")
        self.assertEqual(len(by_cat), 1)
        self.assertEqual(len(reg.list_extensions(category="cloud")), 0)

        # Level 5 readiness check
        self.assertFalse(reg.is_level5_ready(["mcp", "scheduler", "multi_agent"]))

        sched = DummySchedulerExtension()
        reg.register("scheduler", sched, ExtensionMetadata(
            name="scheduler", version="1.0.0", category="core", description="Task scheduler",
            status=ExtensionStatus.ACTIVE
        ))

        agent = DummyMultiAgentExtension()
        reg.register("multi_agent", agent, ExtensionMetadata(
            name="multi_agent", version="1.0.0", category="orchestration", description="Agent orchestrator",
            status=ExtensionStatus.ACTIVE
        ))

        self.assertTrue(reg.is_level5_ready(["mcp", "scheduler", "multi_agent"]))

        # Unregister
        self.assertTrue(reg.unregister("mcp"))
        self.assertFalse(reg.has("mcp"))
        self.assertFalse(reg.is_level5_ready(["mcp", "scheduler", "multi_agent"]))


if __name__ == "__main__":
    unittest.main()
