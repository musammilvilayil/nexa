from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from computer.app_control import ApplicationLauncher

_LAUNCH_RE = re.compile(r"^(?:open|launch|start|/app open)(?:\s+app)?\s+(.+)$", re.IGNORECASE)
_LAUNCH_RE_2 = re.compile(r"^(.+?)\s+open\s+cheyy$", re.IGNORECASE)
_LAUNCH_RE_3 = re.compile(r"^(.+?)\s+thuru$", re.IGNORECASE)

_LIST_RE = re.compile(r"^(?:list apps|installed apps|available apps|/apps|apps list cheyyu)$", re.IGNORECASE)
_FIND_RE = re.compile(r"^(?:find app|where is|find)(?:\s+app)?\s+(.+?)(?:\s+app)?$", re.IGNORECASE)
_CLOSE_RE = re.compile(r"^(?:close|quit|exit)(?:\s+app)?\s+(.+)$", re.IGNORECASE)
_CLOSE_RE_2 = re.compile(r"^(.+?)\s+close\s+cheyy$", re.IGNORECASE)
_CLOSE_RE_3 = re.compile(r"^(.+?)\s+adakk$", re.IGNORECASE)

class AppSkill:
    def __init__(self, launcher: ApplicationLauncher | None = None) -> None:
        self._launcher = launcher or ApplicationLauncher()
        self.metadata = SkillMetadata(
            name="app_control",
            version="0.1.0",
            description="Control applications: launch, find, list, close.",
            operations=(
                OperationSpec("launch", "Launch an application", RiskTier.MUTATE),
                OperationSpec("list_apps", "List registered applications", RiskTier.READ),
                OperationSpec("find_app", "Find an application", RiskTier.READ),
                OperationSpec("close_app", "Close an application", RiskTier.DESTRUCTIVE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        text = text.strip().rstrip(".!?")
        
        # Launch matches
        match = _LAUNCH_RE.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "launch", {"app_name": app}, confidence=0.7)
        match = _LAUNCH_RE_2.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "launch", {"app_name": app}, confidence=0.7)
        match = _LAUNCH_RE_3.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "launch", {"app_name": app}, confidence=0.7)
            
        # List matches
        if _LIST_RE.fullmatch(text):
            return SkillMatch("app_control", "list_apps", {}, confidence=0.7)
            
        # Find matches
        match = _FIND_RE.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "find_app", {"app_name": app}, confidence=0.7)
            
        # Close matches
        match = _CLOSE_RE.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "close_app", {"app_name": app}, confidence=0.7)
        match = _CLOSE_RE_2.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "close_app", {"app_name": app}, confidence=0.7)
        match = _CLOSE_RE_3.fullmatch(text)
        if match:
            app = match.group(1)
            return SkillMatch("app_control", "close_app", {"app_name": app}, confidence=0.7)

        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation in ("launch", "find_app", "close_app"):
            app_name = str(params.get("app_name", "")).strip()
            if not app_name:
                raise ValueError("app_name cannot be empty")
            if "\x00" in app_name:
                raise ValueError("null bytes not allowed")
            return {"app_name": app_name}
        return {}

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "launch":
            res = self._launcher.launch(params["app_name"])
            if not res["success"]:
                return ExecutionResult(False, res["message"], error=res["message"])
            
            # Action -> Verify expected state
            app_obj = res.get("app")
            verified = False
            if app_obj:
                for _ in range(4):
                    time.sleep(0.3)
                    if self._launcher.is_running(app_obj.name):
                        verified = True
                        break
            if verified:
                return ExecutionResult(True, f"Launched {app_obj.name} and verified process is running", data=res)
            return ExecutionResult(True, res["message"], data=res)
        elif operation == "list_apps":
            apps = self._launcher.registry.list_apps()
            data = [{"name": a.name, "executable": a.executable} for a in apps]
            return ExecutionResult(True, f"Found {len(apps)} apps", data=data)
        elif operation == "find_app":
            app = self._launcher.registry.find(params["app_name"])
            if app:
                return ExecutionResult(True, f"Found {app.name}", data={"name": app.name, "executable": app.executable})
            return ExecutionResult(False, f"App '{params['app_name']}' not found")
        elif operation == "close_app":
            app = self._launcher.registry.find(params["app_name"])
            if not app:
                return ExecutionResult(False, f"App '{params['app_name']}' not found in registry", error="not found")
            import subprocess
            exe_name = os.path.basename(app.executable)
            if not exe_name.lower().endswith(".exe"):
                exe_name += ".exe"
            executables = [exe_name]
            if app.name.lower() == "calculator":
                executables.append("CalculatorApp.exe")
            try:
                killed = False
                output = ""
                for exe in executables:
                    sub_res = subprocess.run(["taskkill", "/IM", exe, "/F"], capture_output=True, text=True)
                    if sub_res.returncode == 0:
                        killed = True
                        output = sub_res.stdout.strip()
                        break
                if killed:
                    return ExecutionResult(True, f"Closed {app.name}", data={"output": output})
                return ExecutionResult(True, f"Closed {app.name} (process terminated or was not running)")
            except Exception as exc:
                return ExecutionResult(False, f"Failed to close {app.name}: {exc}", error=str(exc))
            
        return ExecutionResult(False, "Unknown operation", error="unknown")
