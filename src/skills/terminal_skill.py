from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Mapping

from core.contracts import (
    ExecutionResult,
    OperationSpec,
    RiskTier,
    SkillMatch,
    SkillMetadata,
)
from bridges.subprocess_bridge import SubprocessBridge, SubprocessBridgeError


# Commands that are always safe (READ-tier)
SAFE_COMMANDS: frozenset[str] = frozenset({
    "dir", "ls", "echo", "type", "cat", "more", "head", "tail",
    "whoami", "hostname", "date", "time",
    "get-date", "get-location", "get-process", "get-childitem", "get-command", "get-service",
    "python", "python3", "node", "npm", "npx",
    "git", "gh",
    "where", "which",
    "systeminfo", "tasklist", "wmic",
    "ping", "ipconfig", "ifconfig", "netstat",
    "tree",
})

# Commands that are NEVER allowed (unconditional DENY)
DENY_COMMANDS: frozenset[str] = frozenset({
    "format", "diskpart", "bcdedit",
    "shutdown", "restart",
    "reg", "regedit",
    "mkfs", "fdisk", "parted",
    "dd",
    "chmod", "chown",  # not useful on Windows, risky on Linux
})

# Regex patterns for destructive argument patterns
DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\brm\s+(-\w+\s+)*-rf\s+/", re.IGNORECASE),
    re.compile(r"\bdel\s+/[sq]", re.IGNORECASE),
    re.compile(r"\brmdir\s+/[sq]", re.IGNORECASE),
    re.compile(r"\brd\s+/[sq]", re.IGNORECASE),
)

# Match patterns for terminal commands
_PATTERNS = {
    "run": re.compile(
        r"^(?:/(?:terminal|run|exec|cmd|command)\s+|"
        r"run\s+|execute\s+|terminal\s+run\s+)"
        r"(.+)$",
        re.IGNORECASE | re.DOTALL,
    ),
    "run_safe": re.compile(
        r"^(?:check\s+|show\s+|list\s+|what\s+is\s+)"
        r"(.+)$",
        re.IGNORECASE,
    ),
}


class TerminalSkill:
    """Controlled terminal command execution with security gating.

    Safe commands (dir, ls, echo, git, python, etc.) execute at MUTATE tier.
    Unknown commands execute at CRITICAL tier (requires confirmation).
    Denied commands are unconditionally blocked.

    Every command runs through SubprocessBridge (shell=False, env isolated)
    with configurable timeout. Output is captured and truncated if too large.
    """

    MAX_OUTPUT_BYTES = 50_000
    DEFAULT_TIMEOUT = 60.0

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
        additional_safe_commands: frozenset[str] | None = None,
        additional_deny_commands: frozenset[str] | None = None,
    ) -> None:
        self._timeout = max(1.0, float(timeout))
        self._max_output = max(1000, int(max_output_bytes))
        self._safe = SAFE_COMMANDS | (additional_safe_commands or frozenset())
        self._deny = DENY_COMMANDS | (additional_deny_commands or frozenset())

        extra_allowed = {
            "cmd", "cmd.exe",
            "powershell", "powershell.exe",
            "pwsh", "pwsh.exe",
            "bash", "sh",
            "ping", "ping.exe",
            "python", "python.exe", "python3", "python3.exe",
            Path(sys.executable).name.lower(),
        }
        for item in list(self._safe):
            extra_allowed.add(item.lower())
            if not item.lower().endswith(".exe"):
                extra_allowed.add(f"{item.lower()}.exe")

        self._bridge = SubprocessBridge(
            allowed_executables=list(extra_allowed),
            default_timeout=self._timeout,
            inherit_environment=False,
        )

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="terminal",
            version="0.1.0",
            description="Controlled terminal command execution with security gating",
            operations=(
                OperationSpec("run", "Execute a command (requires confirmation for unsafe commands)", RiskTier.CRITICAL),
                OperationSpec("run_safe", "Execute a known-safe command", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        text_stripped = text.strip()

        # Terminal run command wrapped in quotes or explicit prefix
        # e.g.: run terminal command 'echo 'Hello NEXA'' or run terminal command 'Get-Date'
        m_tc = re.match(r"^run\s+terminal\s+command\s+['\"]?(.*?)['\"]?$", text_stripped, re.IGNORECASE)
        if m_tc:
            cmd_inner = m_tc.group(1).strip()
            if (cmd_inner.startswith("'") and cmd_inner.endswith("'")) or (cmd_inner.startswith('"') and cmd_inner.endswith('"')):
                cmd_inner = cmd_inner[1:-1].strip()
            op, risk = self._classify_command(cmd_inner)
            return SkillMatch(skill_name="terminal", operation=op, params={"command": cmd_inner}, confidence=0.95)

        # Python execution: execute python code "..." or run python code "..."
        m_py = re.match(r"^(?:execute|run)\s+python\s+code\s+['\"]?(.*?)['\"]?$", text_stripped, re.IGNORECASE | re.DOTALL)
        if m_py:
            code_inner = m_py.group(1).strip()
            if (code_inner.startswith("'") and code_inner.endswith("'")) or (code_inner.startswith('"') and code_inner.endswith('"')):
                code_inner = code_inner[1:-1].strip()
            return SkillMatch(skill_name="terminal", operation="run_safe", params={"command": f'python -c "{code_inner}"', "python_code": code_inner}, confidence=0.95)

        # Network diagnostics: check network connectivity and ping 127.0.0.1
        m_ping = re.match(r"^(?:check\s+network\s+(?:connectivity\s+)?(?:and\s+)?ping\s+(\S+)|ping\s+(\S+))$", text_stripped, re.IGNORECASE)
        if m_ping:
            target = m_ping.group(1) or m_ping.group(2)
            return SkillMatch(skill_name="terminal", operation="run_safe", params={"command": f"ping {target}"}, confidence=0.95)

        # Direct command patterns
        m = _PATTERNS["run"].match(text_stripped)
        if m:
            command = m.group(1).strip().rstrip(".")
            if not command:
                return None
            op, risk = self._classify_command(command)
            return SkillMatch(
                skill_name="terminal",
                operation=op,
                params={"command": command},
                confidence=0.9,
            )

        m = _PATTERNS["run_safe"].match(text_stripped)
        if m:
            cand = m.group(1).strip().rstrip(".")
            base = self._extract_base_command(cand).lower()
            if base in self._safe and not any(w in cand.lower() for w in ("window", "file", "folder", "desktop", "repo")):
                op, risk = self._classify_command(cand)
                return SkillMatch(
                    skill_name="terminal",
                    operation=op,
                    params={"command": cand},
                    confidence=0.8,
                )

        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        command = str(params.get("command", "")).strip()
        if not command:
            raise ValueError("Command is required")
        if len(command) > 10_000:
            raise ValueError("Command too long (max 10,000 characters)")
        if "\x00" in command:
            raise ValueError("Command contains null bytes")

        # Check deny list
        base_cmd = self._extract_base_command(command)
        if base_cmd.lower() in self._deny:
            raise ValueError(f"Command '{base_cmd}' is permanently blocked for safety")

        # Check destructive patterns
        for pattern in DESTRUCTIVE_PATTERNS:
            if pattern.search(command):
                raise ValueError(f"Destructive command pattern detected")

        # Check for secret exposure
        if self._contains_secret_pattern(command):
            raise ValueError("Command appears to contain or expose secrets/credentials")

        return {"command": command, "base_command": base_cmd, "timeout": self._timeout}

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        command = params["command"]
        timeout = params.get("timeout", self._timeout)

        try:
            # Parse command for subprocess execution
            parts = self._parse_command(command)
            if not parts:
                return ExecutionResult(
                    success=False,
                    message="Could not parse command",
                    error="Empty command after parsing",
                )

            py_code = params.get("python_code")
            base_low = parts[0].lower()
            if py_code:
                executable = sys.executable
                args = ["-c", py_code]
            elif os.name == "nt" and (base_low.startswith("get-") or base_low.startswith("set-") or base_low.startswith("select-") or base_low.startswith("where-")):
                executable = "powershell.exe"
                args = ["-NoProfile", "-Command", command]
            elif os.name == "nt" and base_low in ("echo", "dir", "type", "cls", "vol", "ver", "copy", "del", "ren", "md", "rd"):
                executable = "cmd.exe"
                args = ["/c", command]
            elif base_low in ("python", "python3"):
                executable = sys.executable
                args = parts[1:]
            else:
                executable = parts[0]
                args = parts[1:]

            result = self._bridge.run(
                executable=executable,
                args=args,
                timeout=timeout,
            )

            if isinstance(result, dict):
                stdout = self._truncate(result.get("stdout", ""))
                stderr = self._truncate(result.get("stderr", ""))
                exit_code = result.get("returncode", -1)
            else:
                stdout = self._truncate(getattr(result, "stdout", ""))
                stderr = self._truncate(getattr(result, "stderr", ""))
                exit_code = getattr(result, "returncode", -1)

            if exit_code == 0:
                return ExecutionResult(
                    success=True,
                    message=f"Command completed successfully (exit code 0)",
                    data={
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": exit_code,
                        "command": command,
                    },
                )
            else:
                return ExecutionResult(
                    success=False,
                    message=f"Command failed with exit code {exit_code}",
                    data={
                        "stdout": stdout,
                        "stderr": stderr,
                        "exit_code": exit_code,
                        "command": command,
                    },
                    error=stderr[:500] if stderr else f"Exit code {exit_code}",
                )
        except SubprocessBridgeError as exc:
            return ExecutionResult(
                success=False,
                message=f"Command execution error: {exc}",
                error=str(exc),
            )
        except Exception as exc:
            return ExecutionResult(
                success=False,
                message=f"Unexpected error: {exc}",
                error=str(exc),
            )

    def _classify_command(self, command: str) -> tuple[str, RiskTier]:
        """Classify a command as safe or unsafe based on the base command."""
        base_cmd = self._extract_base_command(command)
        if base_cmd.lower() in self._safe:
            return ("run_safe", RiskTier.MUTATE)
        return ("run", RiskTier.CRITICAL)

    @staticmethod
    def _extract_base_command(command: str) -> str:
        """Extract the base executable name from a command string."""
        parts = command.strip().split()
        if not parts:
            return ""
        base = parts[0]
        # Strip path and extension
        base = os.path.basename(base)
        if base.lower().endswith(".exe"):
            base = base[:-4]
        return base

    @staticmethod
    def _parse_command(command: str) -> list[str]:
        """Parse command string into argument list for subprocess."""
        try:
            parts = shlex.split(command, posix=os.name != "nt")
        except ValueError:
            # Fall back to simple split on parse error
            parts = command.strip().split()

        # On non-posix mode (Windows), shlex keeps outer quotes on tokens.
        # Strip outer quotes so subprocess does not double-quote them.
        cleaned = []
        for p in parts:
            if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'"):
                cleaned.append(p[1:-1])
            else:
                cleaned.append(p)
        return cleaned

    def _truncate(self, text: str) -> str:
        """Truncate output to max bytes."""
        if len(text.encode("utf-8", errors="replace")) <= self._max_output:
            return text
        truncated = text.encode("utf-8", errors="replace")[:self._max_output].decode(
            "utf-8", errors="replace"
        )
        return truncated + f"\n... (output truncated at {self._max_output} bytes)"

    @staticmethod
    def _contains_secret_pattern(command: str) -> bool:
        """Check if a command appears to contain or expose secrets."""
        secret_patterns = (
            re.compile(r"(?:API_KEY|SECRET|PASSWORD|TOKEN|CREDENTIAL)\s*=\s*\S+", re.IGNORECASE),
            re.compile(r"(?:curl|wget|http)\s.*(?:Authorization|Bearer)\s+\S+", re.IGNORECASE),
        )
        return any(pattern.search(command) for pattern in secret_patterns)
