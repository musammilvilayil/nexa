from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.contracts import RiskTier
from core.security import SecurityGate
from extensions.contracts import ExtensionStatus
from extensions.mcp_extension import DefaultMCPExtension, MCPTool, MCPServerConfig
from skills.mcp_skill import MCPSkill


class TestLevel5MCP(unittest.TestCase):
    def setUp(self):
        self.gate = SecurityGate()
        self.mcp = DefaultMCPExtension(security_gate=self.gate)
        self.skill = MCPSkill(self.mcp)

    def test_default_tools_registered(self):
        tools = self.mcp.list_tools()
        tool_names = [t["name"] for t in tools]
        self.assertIn("system_info", tool_names)
        self.assertIn("fetch_web_content", tool_names)

    def test_tool_schema_validation_success(self):
        # 1. READ tool runs without confirmation
        res_info = self.mcp.call_tool("system_info", {})
        self.assertTrue(res_info["success"])
        self.assertIn("platform", res_info["data"])

        # 2. REMOTE tool requires confirmation, and succeeds when confirmed=True
        res_unconfirmed = self.mcp.call_tool("fetch_web_content", {"url": "https://example.com"})
        self.assertEqual(res_unconfirmed.get("status"), "confirmation_required")

        res_confirmed = self.mcp.call_tool("fetch_web_content", {"url": "https://example.com"}, confirmed=True)
        self.assertTrue(res_confirmed["success"])
        self.assertEqual(res_confirmed["data"]["url"], "https://example.com")

    def test_tool_schema_validation_missing_required(self):
        res = self.mcp.call_tool("fetch_web_content", {}, confirmed=True)
        self.assertFalse(res["success"])
        self.assertIn("Missing required parameter 'url'", res["error"])

    def test_security_gate_denial(self):
        # Register a tool that attempts destructive action
        self.mcp.register_tool(
            MCPTool(
                name="delete_database",
                description="Drop database tables",
                input_schema={"type": "object"},
                server_name="db_server",
                risk_tier=RiskTier.DESTRUCTIVE,
            ),
            handler=lambda args: {"deleted": True},
        )
        # SecurityGate will require confirmation or deny for destructive commands
        res = self.mcp.call_tool("delete_database", {})
        # Outcome is either confirmation_required or blocked
        self.assertFalse(res["success"])
        self.assertTrue(res.get("pending_action_required") or res.get("security_blocked"))

    def test_skill_match_and_execution(self):
        # Slash command
        m = self.skill.match("/mcp-list", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "list_tools")

        # Manglish command
        m_ml = self.skill.match("available MCP tools kaanikk", {})
        self.assertIsNotNone(m_ml)
        self.assertEqual(m_ml.operation, "list_tools")

        # Refresh
        m_ref = self.skill.match("available tools refresh cheyy", {})
        self.assertIsNotNone(m_ref)
        self.assertEqual(m_ref.operation, "refresh")

        # Connect
        m_conn = self.skill.match("GitHub MCP connect cheyy", {})
        self.assertIsNotNone(m_conn)
        self.assertEqual(m_conn.operation, "connect")
        self.assertEqual(m_conn.params["server"], "GitHub")

        # Execute list_tools
        exec_res = self.skill.execute("list_tools", {}, {})
        self.assertTrue(exec_res.success)
        self.assertIn("Available MCP Tools", exec_res.message)

        # Execute connect
        conn_res = self.skill.execute("connect", {"server": "github_mcp_server"}, {})
        self.assertTrue(conn_res.success)
        self.assertIn("Connected to MCP server", conn_res.message)


if __name__ == "__main__":
    unittest.main()
