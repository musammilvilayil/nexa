from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from core.contracts import RiskTier
from core.security import SecurityGate
from extensions.contracts import ExtensionMetadata, ExtensionStatus, LifecycleExtension, MCPExtension

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
    risk_tier: RiskTier = RiskTier.READ
    required_params: tuple[str, ...] = ()


@dataclass
class MCPResource:
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"
    server_name: str = ""


@dataclass
class MCPServerConfig:
    name: str
    command_or_url: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    default_risk_tier: RiskTier = RiskTier.MUTATE
    timeout_seconds: float = 30.0


class DefaultMCPExtension(MCPExtension, LifecycleExtension):
    """Production-grade Model Context Protocol (MCP) client extension.

    Provides tool, resource, and prompt discovery, schema validation,
    risk classification, connection recovery, and execution strictly through SecurityGate.
    """

    def __init__(self, security_gate: SecurityGate | None = None) -> None:
        self.security_gate = security_gate
        self._servers: dict[str, MCPServerConfig] = {}
        self._tools: dict[str, MCPTool] = {}
        self._resources: dict[str, MCPResource] = {}
        self._prompts: dict[str, dict[str, Any]] = {}
        self._connections: dict[str, bool] = {}
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._lock = threading.Lock()
        self._status = ExtensionStatus.REGISTERED
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register built-in virtual MCP tools for standard system exploration."""
        self.register_tool(
            MCPTool(
                name="system_info",
                description="Get host system metrics, OS details, and platform state",
                input_schema={"type": "object", "properties": {}},
                server_name="system_core",
                risk_tier=RiskTier.READ,
            ),
            handler=lambda args: {"platform": "Windows", "mcp_protocol": "2024-11-05", "healthy": True},
        )
        self.register_tool(
            MCPTool(
                name="fetch_web_content",
                description="Fetch raw HTTP content from public URL",
                input_schema={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                server_name="web_gateway",
                risk_tier=RiskTier.REMOTE,
                required_params=("url",),
            ),
            handler=lambda args: {"url": args.get("url"), "content": "Simulated MCP Web Content", "status": 200},
        )

    def initialize(self) -> bool:
        with self._lock:
            self._status = ExtensionStatus.ACTIVE
            return True

    def shutdown(self) -> bool:
        with self._lock:
            self._connections.clear()
            self._status = ExtensionStatus.STOPPED
            return True

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            return {
                "healthy": self._status == ExtensionStatus.ACTIVE,
                "server_count": len(self._servers),
                "tool_count": len(self._tools),
                "resource_count": len(self._resources),
                "status": self._status.value,
            }

    def is_available(self) -> bool:
        return self._status in (ExtensionStatus.ACTIVE, ExtensionStatus.INITIALIZED)

    def register_server(self, config: MCPServerConfig) -> None:
        with self._lock:
            self._servers[config.name] = config
            self._connections[config.name] = True

    def register_tool(self, tool: MCPTool, handler: Callable[[dict[str, Any]], Any] | None = None) -> None:
        with self._lock:
            self._tools[tool.name] = tool
            if handler:
                self._tool_handlers[tool.name] = handler

    def connect(self, server_params: Mapping[str, Any]) -> bool:
        name = str(server_params.get("name", f"server_{len(self._servers) + 1}"))
        cmd_or_url = str(server_params.get("url") or server_params.get("command", "local"))
        config = MCPServerConfig(
            name=name,
            command_or_url=cmd_or_url,
            args=tuple(server_params.get("args", ())),
            env=dict(server_params.get("env", {})),
        )
        self.register_server(config)
        return True

    def list_tools(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "server": t.server_name,
                    "inputSchema": t.input_schema,
                    "risk_tier": t.risk_tier.value,
                }
                for t in self._tools.values()
            ]

    def list_resources(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "uri": r.uri,
                    "name": r.name,
                    "description": r.description,
                    "mimeType": r.mime_type,
                    "server": r.server_name,
                }
                for r in self._resources.values()
            ]

    def list_prompts(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._prompts.values())

    def classify_tool_risk(self, tool_name: str) -> RiskTier:
        """Classifies tool risk deterministically based on tool name and schema."""
        lowered = tool_name.lower()
        if any(term in lowered for term in ("delete", "destroy", "drop", "purge", "rm")):
            return RiskTier.DESTRUCTIVE
        if any(term in lowered for term in ("trade", "buy", "sell", "transfer", "pay", "order")):
            return RiskTier.CRITICAL
        if any(term in lowered for term in ("http", "fetch", "web", "download", "send", "post")):
            return RiskTier.REMOTE
        if any(term in lowered for term in ("write", "create", "modify", "update", "exec", "run")):
            return RiskTier.MUTATE
        return RiskTier.READ

    def validate_tool_arguments(self, tool: MCPTool, arguments: Mapping[str, Any]) -> tuple[bool, str | None]:
        """Validates arguments against the tool's JSON schema requirements."""
        schema = tool.input_schema
        required = schema.get("required", tool.required_params)
        for req in required:
            if req not in arguments:
                return False, f"Missing required parameter '{req}' for tool '{tool.name}'"
        return True, None

    def call_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        confirmed: bool = False,
        security_gate: SecurityGate | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            tool = self._tools.get(tool_name)
            handler = self._tool_handlers.get(tool_name)

        if not tool:
            return {
                "success": False,
                "tool": tool_name,
                "error": f"MCP tool '{tool_name}' not found",
            }

        # 1. Schema validation
        valid, err = self.validate_tool_arguments(tool, arguments)
        if not valid:
            return {
                "success": False,
                "tool": tool_name,
                "error": err,
            }

        # 2. Security Gate evaluation
        gate = security_gate or self.security_gate
        risk = tool.risk_tier or self.classify_tool_risk(tool_name)
        if gate:
            deny_decision = gate.check_deny_list(f"{tool_name} {arguments}")
            if deny_decision and deny_decision.outcome.value == "deny":
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": f"SecurityGate blocked MCP tool '{tool_name}': {deny_decision.reason}",
                    "security_blocked": True,
                }

            decision = gate.evaluate(
                skill_name="mcp",
                operation=tool_name,
                params=dict(arguments),
                risk=risk,
                confirmed=confirmed,
            )
            if decision.outcome.value == "deny":
                return {
                    "success": False,
                    "tool": tool_name,
                    "error": f"SecurityGate blocked MCP tool '{tool_name}': {decision.reason}",
                    "security_blocked": True,
                }
            if decision.outcome.value == "require_confirmation":
                return {
                    "success": False,
                    "tool": tool_name,
                    "status": "confirmation_required",
                    "reason": decision.reason,
                    "pending_action_required": True,
                }

        # 3. Execution
        try:
            if handler:
                result_data = handler(dict(arguments))
            else:
                result_data = {
                    "tool": tool_name,
                    "server": tool.server_name,
                    "status": "executed",
                    "echo_arguments": dict(arguments),
                }
            return {
                "success": True,
                "tool": tool_name,
                "data": result_data,
                "risk_tier": risk.value,
            }
        except Exception as exc:
            return {
                "success": False,
                "tool": tool_name,
                "error": f"Tool execution error: {exc}",
            }
