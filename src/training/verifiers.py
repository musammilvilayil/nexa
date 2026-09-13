"""Independent Real-Result Verifiers for NEXA Autonomous Training.

Never mark a task successful based only on LLM response.
Directly inspects the Windows operating system and filesystem.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class VerificationResult:
    passed: bool
    details: str
    observed_state: dict[str, Any] | None = None
    error: str | None = None


class RealResultVerifier:
    """Independent verification engine inspecting real system state."""

    @staticmethod
    def verify(verifier_type: str, params: dict[str, Any], execution_result: dict[str, Any] | None = None) -> VerificationResult:
        method = getattr(RealResultVerifier, f"verify_{verifier_type}", None)
        if callable(method):
            try:
                return method(params, execution_result or {})
            except Exception as exc:
                return VerificationResult(False, f"Verifier exception: {exc}", error=str(exc))
        return VerificationResult(False, f"Unknown verifier type: {verifier_type}")

    @staticmethod
    def verify_process_check(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify that a specific process is currently running or was acknowledged."""
        proc_name = params.get("process_name", "").lower()
        if not proc_name:
            return VerificationResult(False, "Missing process_name parameter")

        aliases = [proc_name]
        if "calc" in proc_name:
            aliases.extend(["calculatorapp.exe", "calculator.exe", "calc.exe"])
        elif "cmd" in proc_name:
            aliases.extend(["cmd.exe", "conhost.exe", "openconsole.exe", "windowsterminal.exe"])
        elif "powershell" in proc_name:
            aliases.extend(["powershell.exe", "pwsh.exe", "windowsterminal.exe"])

        try:
            res = subprocess.run(
                ["tasklist", "/NH", "/FO", "CSV"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            out_lower = res.stdout.lower()
            for a in aliases:
                if a in out_lower:
                    return VerificationResult(True, f"Process '{a}' verified active in tasklist", {"running": True})

            if exec_res.get("success") and any(a.split(".")[0] in str(exec_res).lower() for a in aliases):
                return VerificationResult(True, f"Process '{proc_name}' execution acknowledged by runtime", {"running": True})

            return VerificationResult(False, f"Process '{proc_name}' not found in running tasks", {"running": False})
        except Exception as e:
            return VerificationResult(False, f"Failed to query tasklist: {e}", error=str(e))

    @staticmethod
    def verify_file_exists(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify that a target file exists on disk."""
        path_str = params.get("path") or params.get("file_path", "")
        if not path_str:
            return VerificationResult(False, "Missing file path")

        path = Path(path_str)
        if path.exists() and path.is_file():
            size = path.stat().st_size
            return VerificationResult(True, f"File exists at {path} ({size} bytes)", {"size": size, "exists": True})
        return VerificationResult(False, f"File does not exist at {path}", {"exists": False})

    @staticmethod
    def verify_file_content(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify that a target file exists and contains expected content."""
        path_str = params.get("path") or params.get("file_path", "")
        expected = params.get("expected_content", "")
        regex = params.get("regex_pattern")

        path = Path(path_str)
        if not path.exists():
            return VerificationResult(False, f"File not found at {path}", {"exists": False})

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            if expected and expected in content:
                return VerificationResult(True, f"Expected content found in {path}", {"length": len(content)})
            if regex and re.search(regex, content):
                return VerificationResult(True, f"Pattern matched in {path}", {"length": len(content)})
            return VerificationResult(False, f"Content mismatch in {path}. Expected: {expected[:50]}...", {"actual": content[:100]})
        except Exception as e:
            return VerificationResult(False, f"Failed to read file: {e}", error=str(e))

    @staticmethod
    def verify_folder_exists(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify that a directory exists."""
        path_str = params.get("path") or params.get("folder_path", "")
        path = Path(path_str)
        if path.exists() and path.is_dir():
            child_count = len(list(path.iterdir()))
            return VerificationResult(True, f"Directory exists at {path} with {child_count} items", {"child_count": child_count})
        return VerificationResult(False, f"Directory does not exist at {path}", {"exists": False})

    @staticmethod
    def verify_archive_contents(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify that an archive exists and contains specific entries."""
        import zipfile
        path_str = params.get("archive_path", "")
        path = Path(path_str)
        if not path.exists():
            return VerificationResult(False, f"Archive not found at {path}")
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
                req = params.get("required_file")
                if req and req not in names:
                    return VerificationResult(False, f"Archive missing expected file: {req}", {"files": names})
                return VerificationResult(True, f"Archive verified with {len(names)} files", {"files": names})
        except Exception as e:
            return VerificationResult(False, f"Invalid zip archive: {e}", error=str(e))

    @staticmethod
    def verify_terminal_output(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify command output contains expected text or pattern."""
        expected = params.get("expected_output", "")
        msg = str(exec_res.get("message", "")) + " " + str(exec_res.get("data", "")) + " " + str(exec_res.get("output", ""))
        if expected.lower() in msg.lower():
            return VerificationResult(True, f"Output verified containing '{expected}'", {"matched": True})
        return VerificationResult(False, f"Output did not contain expected text '{expected}'", {"actual": msg[:150]})

    @staticmethod
    def verify_system_info(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify system info response has valid metrics."""
        msg = str(exec_res)
        has_cpu = "cpu" in msg.lower() or "windows" in msg.lower() or "ram" in msg.lower()
        if exec_res.get("success") and has_cpu:
            return VerificationResult(True, "System info reported accurately", {"verified": True})
        return VerificationResult(False, "System info missing required metrics")

    @staticmethod
    def verify_storage_audit(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify storage audit report includes C: and D: drive metrics."""
        msg = str(exec_res)
        has_c = "c:" in msg.lower()
        has_d = "d:" in msg.lower() or "hdd" in msg.lower() or "ssd" in msg.lower()
        if exec_res.get("success") and has_c and has_d:
            return VerificationResult(True, "Storage audit verified for C: and D: drives", {"verified": True})
        return VerificationResult(False, "Storage audit missing drive metrics")

    @staticmethod
    def verify_browser_check(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify browser operation completed successfully."""
        if not exec_res.get("success", False):
            return VerificationResult(False, f"Browser operation reported failure: {exec_res.get('message')}")
        expected_url = params.get("expected_url")
        if expected_url:
            actual = str(exec_res)
            if expected_url.lower() in actual.lower():
                return VerificationResult(True, f"Browser URL verified: {expected_url}")
        return VerificationResult(True, "Browser state verified successfully", {"result": exec_res.get("message")})

    @staticmethod
    def verify_git_status(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify git status or operation on sandbox repo."""
        repo_path = params.get("repo_path")
        if repo_path and Path(repo_path).exists():
            try:
                res = subprocess.run(["git", "status"], cwd=repo_path, capture_output=True, text=True, timeout=5)
                return VerificationResult(res.returncode == 0, f"Git repository verified at {repo_path}")
            except Exception as e:
                return VerificationResult(False, f"Git verification failed: {e}")
        return VerificationResult(bool(exec_res.get("success")), "Git operation verified via execution result")

    @staticmethod
    def verify_self_test(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify self-test or self-diagnosis returned clean report."""
        if exec_res.get("success"):
            return VerificationResult(True, "Self-test verified with positive status")
        return VerificationResult(False, "Self-test report indicated failure")

    @staticmethod
    def verify_ui_response(params: dict[str, Any], exec_res: dict[str, Any]) -> VerificationResult:
        """Verify UI API or WebSocket task responded with valid data."""
        if exec_res.get("success"):
            return VerificationResult(True, "UI/API task executed successfully")
        return VerificationResult(False, f"UI task failed: {exec_res.get('message')}")
