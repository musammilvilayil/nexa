from __future__ import annotations

import json
import re
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from extensions.contracts import ExtensionStatus
from extensions.mcp_extension import DefaultMCPExtension


_MCP_LIST_RE = re.compile(
    r"^(?:/(?:mcp-list|mcp\s+list)|mcp\s+list|available\s+mcp\s+tools\s+kaanikk|list\s+mcp\s+tools|/mcp)$",
    re.IGNORECASE,
)
_MCP_STATUS_RE = re.compile(
    r"^(?:/(?:mcp-status|mcp\s+status)|mcp\s+status)$",
    re.IGNORECASE,
)
_MCP_REFRESH_RE = re.compile(
    r"^(?:/(?:mcp-refresh|mcp\s+refresh)|mcp\s+refresh|available\s+tools\s+refresh\s+cheyy|refresh\s+mcp\s+tools)$",
    re.IGNORECASE,
)
_MCP_CONNECT_RE = re.compile(
    r"^(?:/(?:mcp\s+connect)|connect\s+mcp|mcp\s+connect)\s+(.+)$|"
    r"^(.+?)\s+mcp\s+connect\s+cheyy$",
    re.IGNORECASE,
)
_MCP_CALL_RE = re.compile(
    r"^(?:/(?:mcp\s+call)|mcp\s+call)\s+([a-zA-Z0-9_\-\.]+)(?:\s+(.+))?$",
    re.IGNORECASE,
)
_MCP_RESOURCES_RE = re.compile(
    r"^(?:/(?:mcp\s+resources)|mcp\s+resources|mcp\s+resources\s+kaanikk|list\s+mcp\s+resources)$",
    re.IGNORECASE,
)


class MCPSkill:
    """Kernel skill exposing Model Context Protocol operations to natural language and CLI."""

    def __init__(self, mcp_extension: DefaultMCPExtension | None = None) -> None:
        self.mcp = mcp_extension or DefaultMCPExtension()
        self._metadata = SkillMetadata(
            name="mcp",
            version="1.0.0",
            description="Manage and execute Model Context Protocol (MCP) servers, tools, and resources",
            operations=(
                OperationSpec("list_tools", "List all discovered MCP tools", RiskTier.READ),
                OperationSpec("status", "Show MCP extension and server status", RiskTier.READ),
                OperationSpec("refresh", "Refresh and rediscover MCP tools from connected servers", RiskTier.MUTATE),
                OperationSpec("connect", "Connect to an MCP server endpoint", RiskTier.REMOTE),
                OperationSpec("call", "Execute an authorized MCP tool", RiskTier.MUTATE),
                OperationSpec("list_resources", "List all discovered MCP resources", RiskTier.READ),
            ),
        )

    @property
    def metadata(self) -> SkillMetadata:
        return self._metadata

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        clean = text.strip()
        if _MCP_LIST_RE.match(clean):
            return SkillMatch("mcp", "list_tools", {})
        if _MCP_STATUS_RE.match(clean):
            return SkillMatch("mcp", "status", {})
        if _MCP_REFRESH_RE.match(clean):
            return SkillMatch("mcp", "refresh", {})
        if _MCP_RESOURCES_RE.match(clean):
            return SkillMatch("mcp", "list_resources", {})

        m_conn = _MCP_CONNECT_RE.match(clean)
        if m_conn:
            server = (m_conn.group(1) or m_conn.group(2) or "").strip()
            return SkillMatch("mcp", "connect", {"server": server})

        m_call = _MCP_CALL_RE.match(clean)
        if m_call:
            tool_name = m_call.group(1).strip()
            raw_args = (m_call.group(2) or "{}").strip()
            try:
                args = json.loads(raw_args) if raw_args.startswith("{") else {"arg": raw_args}
            except Exception:
                args = {"raw": raw_args}
            return SkillMatch("mcp", "call", {"tool_name": tool_name, "arguments": args})

        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation == "connect":
            server = str(params.get("server", "")).strip()
            if not server:
                raise ValueError("Server name/URL is required")
            return {"server": server}
        if operation == "call":
            tool_name = str(params.get("tool_name", "")).strip()
            if not tool_name:
                raise ValueError("tool_name is required")
            args = dict(params.get("arguments", {}))
            return {"tool_name": tool_name, "arguments": args}
        return dict(params)

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        try:
            if operation == "list_tools":
                tools = self.mcp.list_tools()
                lines = [f"Available MCP Tools ({len(tools)}):"]
                for t in tools:
                    lines.append(f"  - {t['name']} [{t['risk_tier'].upper()}]: {t['description']} (server: {t['server']})")
                return ExecutionResult(True, "\n".join(lines), data={"tools": tools})

            if operation == "status":
                hc = self.mcp.health_check()
                msg = f"MCP Subsystem: status={hc['status']}, healthy={hc['healthy']}, servers={hc['server_count']}, tools={hc['tool_count']}"
                return ExecutionResult(True, msg, data=hc)

            if operation == "refresh":
                tools = self.mcp.list_tools()
                return ExecutionResult(True, f"MCP tools refreshed. {len(tools)} tools discovered.", data={"tools": tools})

            if operation == "connect":
                server = params["server"]
                ok = self.mcp.connect({"name": server, "url": server})
                return ExecutionResult(ok, f"Connected to MCP server: {server}" if ok else f"Failed to connect to {server}")

            if operation == "list_resources":
                resources = self.mcp.list_resources()
                return ExecutionResult(True, f"Discovered {len(resources)} MCP resource(s)", data={"resources": resources})

            if operation == "call":
                tool_name = params["tool_name"]
                arguments = params["arguments"]
                confirmed = bool(params.get("confirmed", False)) or bool(context.get("confirmed", False))
                res = self.mcp.call_tool(tool_name, arguments, confirmed=confirmed, context=context)
                if res.get("status") == "confirmation_required":
                    return ExecutionResult(
                        success=False,
                        message=f"Confirmation required for MCP tool '{tool_name}' ({res.get('reason')})",
                        data=res,
                    )
                if not res.get("success"):
                    return ExecutionResult(False, res.get("error", "Execution failed"), error=res.get("error"))
                return ExecutionResult(True, f"MCP tool '{tool_name}' executed successfully", data=res.get("data"))

            return ExecutionResult(False, f"Unknown operation: {operation}", error="unknown_operation")
        except Exception as exc:
            return ExecutionResult(False, f"MCP skill error: {exc}", error=str(exc))
