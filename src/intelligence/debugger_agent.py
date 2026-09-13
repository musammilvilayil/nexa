from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger("nexa.intelligence.debugger")


class ErrorCategory(str, Enum):
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    STALE_ELEMENT = "STALE_ELEMENT"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    PROCESS_NOT_RUNNING = "PROCESS_NOT_RUNNING"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    NETWORK_OFFLINE = "NETWORK_OFFLINE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    UNKNOWN_COMMAND = "UNKNOWN_COMMAND"
    UNKNOWN = "UNKNOWN"


PROTECTED_SECURITY_PATHS = frozenset({
    "src/core/security.py",
    "src/core/failsafe.py",
    "core/security.py",
    "core/failsafe.py",
    "src/auth",
    "auth",
})


@dataclass(frozen=True)
class DiagnosisReport:
    category: ErrorCategory
    root_cause: str
    target_identifier: str
    suggested_strategy: str
    recoverable: bool
    requires_code_patch: bool
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodePatch:
    file_path: str
    original_code: str
    proposed_code: str
    rationale: str


class DebuggerAgent:
    """Autonomous error analysis and self-debugging engine for NEXA.
    
    Responsibilities:
    1. Error Capture & Classification
    2. Root Cause Diagnosis
    3. Safe Recovery Strategy Selection
    4. Guarded Non-Security Code Patch Generation
    5. Test-Driven Verification
    """

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = Path(project_root or Path.cwd()).resolve()

    def diagnose(self, error_text: str, context: Mapping[str, Any] | None = None) -> DiagnosisReport:
        ctx = dict(context or {})
        err = str(error_text).strip()
        err_lower = err.lower()

        category = ErrorCategory.UNKNOWN
        root_cause = err
        target_id = ""
        strategy = "retry"
        recoverable = True
        code_patch = False

        if "not found" in err_lower and ("selector" in err_lower or "element" in err_lower or "#" in err or "." in err):
            category = ErrorCategory.SELECTOR_NOT_FOUND
            root_cause = "Target DOM selector was not found in active browser viewport."
            m_sel = re.search(r"['\"]([#\.][a-zA-Z0-9_\-]+)['\"]", err)
            target_id = m_sel.group(1) if m_sel else ctx.get("target", "")
            strategy = "wait_for_network_idle_and_reobserve"
            recoverable = True

        elif "stale" in err_lower:
            category = ErrorCategory.STALE_ELEMENT
            root_cause = "DOM mutated between observation and interaction."
            strategy = "reobserve_and_reattempt"
            recoverable = True

        elif "window" in err_lower and ("not found" in err_lower or "cannot find" in err_lower):
            category = ErrorCategory.WINDOW_NOT_FOUND
            root_cause = "Target desktop application window is not active or minimized."
            target_id = ctx.get("app", "") or ctx.get("app_name", "")
            strategy = "launch_or_focus_window"
            recoverable = True

        elif "process" in err_lower and ("not running" in err_lower or "stopped" in err_lower):
            category = ErrorCategory.PROCESS_NOT_RUNNING
            root_cause = "Target process terminated prematurely."
            strategy = "relaunch_process"
            recoverable = True

        elif "file" in err_lower and ("not found" in err_lower or "no such file" in err_lower):
            category = ErrorCategory.FILE_NOT_FOUND
            root_cause = "Target file or directory path does not exist."
            target_id = ctx.get("path", "")
            strategy = "create_parent_directory_or_verify_path"
            recoverable = True

        elif "timeout" in err_lower or "timed out" in err_lower:
            category = ErrorCategory.TIMEOUT
            root_cause = "Operation exceeded allowable execution deadline."
            strategy = "exponential_backoff_retry"
            recoverable = True

        elif "syntaxerror" in err_lower:
            category = ErrorCategory.SYNTAX_ERROR
            root_cause = "Syntax error in dynamically generated or executed code."
            strategy = "parse_ast_and_patch"
            recoverable = False
            code_patch = True

        return DiagnosisReport(
            category=category,
            root_cause=root_cause,
            target_identifier=target_id,
            suggested_strategy=strategy,
            recoverable=recoverable,
            requires_code_patch=code_patch,
            context=ctx,
        )

    def is_safe_to_patch(self, file_path: str | Path) -> bool:
        """Enforces absolute security barrier preventing automated modification of security components."""
        norm_path = str(file_path).replace("\\", "/").lower()
        for protected in PROTECTED_SECURITY_PATHS:
            if protected in norm_path:
                logger.critical("SECURITY GUARD: Automated patch blocked on protected path %s", file_path)
                return False
        return True

    def propose_code_patch(
        self,
        file_path: str | Path,
        original_chunk: str,
        replacement_chunk: str,
        rationale: str,
    ) -> CodePatch:
        if not self.is_safe_to_patch(file_path):
            raise PermissionError(f"SecurityGate prohibits autonomous modification of protected file: {file_path}")

        return CodePatch(
            file_path=str(file_path),
            original_code=original_chunk,
            proposed_code=replacement_chunk,
            rationale=rationale,
        )

    def verify_fix(self, test_args: list[str]) -> bool:
        """Run a test command to deterministically confirm the fix."""
        try:
            cmd = [sys.executable, "-m", "unittest"] + test_args
            res = subprocess.run(cmd, cwd=str(self.project_root), capture_output=True, text=True, timeout=30)
            return res.returncode == 0
        except Exception as exc:
            logger.warning("Verification test execution failed: %s", exc)
            return False

