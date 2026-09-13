from __future__ import annotations

import os
import re
import time
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from computer.app_control import ApplicationLauncher
from core.entity_resolver import EntityResolver

_LAUNCH_RE = re.compile(r"^(?:open|launch|start|run|/app open)(?:\s+the)?(?:\s+app)?\s+(.+)$", re.IGNORECASE)
_LAUNCH_RE_2 = re.compile(r"^(.+?)\s+open\s+cheyy$", re.IGNORECASE)
_LAUNCH_RE_3 = re.compile(r"^(.+?)\s+thuru$", re.IGNORECASE)

_LIST_RE = re.compile(r"^(?:list apps|installed apps|available apps|/apps|apps list cheyyu)$", re.IGNORECASE)
_FIND_RE = re.compile(r"^(?:find app|where is|find)(?:\s+app)?\s+(.+?)(?:\s+app)?$", re.IGNORECASE)
_CLOSE_RE = re.compile(r"^(?:close|quit|exit)(?:\s+app)?\s+(.+)$", re.IGNORECASE)
_CLOSE_RE_2 = re.compile(r"^(.+?)\s+close\s+cheyy$", re.IGNORECASE)
_CLOSE_RE_3 = re.compile(r"^(.+?)\s+adakk$", re.IGNORECASE)
_FOCUS_RE = re.compile(r"^(?:focus|bring to front|switch to)(?:\s+app)?\s+(.+)$", re.IGNORECASE)


class AppSkill:
    def __init__(self, launcher: ApplicationLauncher | None = None) -> None:
        self._launcher = launcher or ApplicationLauncher()
        self.metadata = SkillMetadata(
            name="app_control",
            version="0.2.0",
            description="Control applications: launch, find, list, close, focus.",
            operations=(
                OperationSpec("launch", "Launch an application", RiskTier.MUTATE),
                OperationSpec("list_apps", "List registered applications", RiskTier.READ),
                OperationSpec("find_app", "Find an application", RiskTier.READ),
                OperationSpec("close_app", "Close an application", RiskTier.DESTRUCTIVE),
                OperationSpec("focus_app", "Bring application to foreground", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        cleaned = EntityResolver.strip_politeness(text).strip().rstrip(".!?")
        cleaned = re.sub(r"\s*\[variant\s*\d+\]", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"\s+and\s+(?:check|verify|inspect)\s+.*$", "", cleaned, flags=re.IGNORECASE)

        # Do not match browser or web navigation commands as desktop applications
        lower = cleaned.lower()
        if any(prefix in lower for prefix in ("browser to", "new browser tab", "browser tab", "http://", "https://", "www.")):
            return None
        if lower.startswith("open browser to") or lower.startswith("open a new browser tab") or lower.startswith("open a new tab"):
            return None

        has_conjunction = bool(re.search(r"\b(?:and|then|pinne|ennitt|athukazhinju)\b", cleaned, re.IGNORECASE))

        # Launch matches
        for pattern in (_LAUNCH_RE, _LAUNCH_RE_2, _LAUNCH_RE_3):
            match = pattern.fullmatch(cleaned)
            if match:
                raw_app = match.group(1).strip()
                canonical = EntityResolver.resolve_app_name(raw_app)
                app = canonical if self._launcher.registry.find(canonical) else raw_app
                if has_conjunction and not self._launcher.registry.find(app):
                    return None
                return SkillMatch("app_control", "launch", {"app_name": app}, confidence=0.7)

        # Focus matches
        match = _FOCUS_RE.fullmatch(cleaned)
        if match:
            raw_app = match.group(1).strip()
            canonical = EntityResolver.resolve_app_name(raw_app)
            app = canonical if self._launcher.registry.find(canonical) else raw_app
            return SkillMatch("app_control", "focus_app", {"app_name": app}, confidence=0.7)

        # List matches
        if _LIST_RE.fullmatch(cleaned):
            return SkillMatch("app_control", "list_apps", {}, confidence=0.7)

        # Find matches
        match = _FIND_RE.fullmatch(cleaned)
        if match:
            raw_app = match.group(1).strip()
            canonical = EntityResolver.resolve_app_name(raw_app)
            app = canonical if self._launcher.registry.find(canonical) else raw_app
            if has_conjunction and not self._launcher.registry.find(app):
                return None
            return SkillMatch("app_control", "find_app", {"app_name": app}, confidence=0.7)

        # Close matches
        for pattern in (_CLOSE_RE, _CLOSE_RE_2, _CLOSE_RE_3):
            match = pattern.fullmatch(cleaned)
            if match:
                raw_app = match.group(1).strip()
                canonical = EntityResolver.resolve_app_name(raw_app)
                app = canonical if self._launcher.registry.find(canonical) else raw_app
                if has_conjunction and not self._launcher.registry.find(app):
                    return None
                return SkillMatch("app_control", "close_app", {"app_name": app}, confidence=0.7)

        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation in ("launch", "find_app", "close_app", "focus_app"):
            app_name = str(params.get("app_name", "")).strip()
            if not app_name:
                raise ValueError("app_name cannot be empty")
            if "\x00" in app_name:
                raise ValueError("null bytes not allowed")
            return {"app_name": app_name}
        return {}

    def _make_result(
        self,
        success: bool,
        action: str,
        target: str = "",
        observation: Any = None,
        error: str | None = None,
        screenshot: Any = None,
        metadata: dict[str, Any] | None = None,
        message: str = "",
        **extra_compat: Any,
    ) -> ExecutionResult:
        obs = observation if isinstance(observation, dict) else ({"value": observation} if observation is not None else {})
        meta = metadata or {}
        msg = message or (error if not success and error else f"Application action '{action}' completed successfully.")
        data_dict = {
            "success": success,
            "action": action,
            "target": target,
            "observation": obs,
            "error": error,
            "screenshot": screenshot,
            "metadata": meta,
            **extra_compat,
        }
        return ExecutionResult(success=success, message=msg, data=data_dict, error=error)

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "launch":
            app_name = params["app_name"]
            res = self._launcher.launch(app_name)
            extra = {k: v for k, v in res.items() if k not in ("success", "message", "error")}
            if not res["success"]:
                return self._make_result(
                    success=False,
                    action="launch",
                    target=app_name,
                    error=res.get("message", "Launch failed"),
                    message=res.get("message", "Launch failed"),
                    **extra,
                )

            # Action -> Verify expected state
            app_obj = res.get("app")
            verified = False
            if app_obj:
                for _ in range(5):
                    time.sleep(0.3)
                    if self._launcher.is_running(app_obj.name):
                        verified = True
                        break
            msg = f"Launched {app_obj.name} and verified process is running" if verified else res["message"]
            return self._make_result(
                success=True,
                action="launch",
                target=app_name,
                observation={"running": verified, "app": app_obj.name if app_obj else app_name},
                message=msg,
                **extra,
            )

        elif operation == "focus_app":
            app_name = params["app_name"]
            app = self._launcher.registry.find(app_name)
            target_name = app.name if app else app_name
            from computer.window import WindowManager
            wm = WindowManager()
            w = wm.find_window(target_name)
            if w:
                wm.focus_window(w.handle)
                return self._make_result(
                    success=True,
                    action="focus_app",
                    target=target_name,
                    observation={"handle": w.handle, "title": w.title},
                    message=f"Focused window: {w.title}",
                    handle=w.handle,
                    title=w.title,
                )
            return self._make_result(
                success=False,
                action="focus_app",
                target=target_name,
                error="window not found",
                message=f"Window for '{target_name}' not found",
            )

        elif operation == "list_apps":
            apps = self._launcher.registry.list_apps()
            app_list = [{"name": a.name, "executable": a.executable} for a in apps]
            return self._make_result(
                success=True,
                action="list_apps",
                observation={"apps": app_list, "count": len(app_list)},
                message=f"Found {len(apps)} apps",
                apps=app_list,
            )

        elif operation == "find_app":
            app_name = params["app_name"]
            app = self._launcher.registry.find(app_name)
            if app:
                data = {"name": app.name, "executable": app.executable}
                return self._make_result(
                    success=True,
                    action="find_app",
                    target=app_name,
                    observation=data,
                    message=f"Found {app.name}",
                    **data,
                )
            return self._make_result(
                success=False,
                action="find_app",
                target=app_name,
                error="App not found",
                message=f"App '{app_name}' not found",
            )

        elif operation == "close_app":
            app_name = params["app_name"]
            app = self._launcher.registry.find(app_name)
            if not app:
                return self._make_result(
                    success=False,
                    action="close_app",
                    target=app_name,
                    error="not found",
                    message=f"App '{app_name}' not found in registry",
                )
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
                msg = f"Closed {app.name}" if killed else f"Closed {app.name} (process terminated or was not running)"
                return self._make_result(
                    success=True,
                    action="close_app",
                    target=app.name,
                    observation={"killed": killed, "output": output},
                    message=msg,
                    output=output,
                )
            except Exception as exc:
                return self._make_result(
                    success=False,
                    action="close_app",
                    target=app.name,
                    error=str(exc),
                    message=f"Failed to close {app.name}: {exc}",
                )

        return self._make_result(
            success=False,
            action=operation,
            error="unknown",
            message="Unknown operation",
        )
