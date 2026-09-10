from __future__ import annotations

import os
import re
import shlex
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
        self._bridge = SubprocessBridge(
            allowed_executables=list(self._safe | {"cmd", "powershell", "pwsh", "bash", "sh"}),
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

        # Direct command patterns
        m = _PATTERNS["run"].match(text_stripped)
        if m:
            command = m.group(1).strip()
            if not command:
                return None
            op, risk = self._classify_command(command)
            return SkillMatch(
                skill_name="terminal",
                operation=op,
                params={"command": command},
                confidence=0.9,
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

            result = self._bridge.run(
                args=parts,
                timeout=timeout,
            )

            stdout = self._truncate(result.get("stdout", ""))
            stderr = self._truncate(result.get("stderr", ""))
            exit_code = result.get("returncode", -1)

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
            return shlex.split(command, posix=os.name != "nt")
        except ValueError:
            # Fall back to simple split on parse error
            return command.strip().split()

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
