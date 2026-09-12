from __future__ import annotations

import re
from typing import Any, Mapping, Protocol
from dataclasses import dataclass

from core.contracts import SkillMetadata, OperationSpec, SkillMatch, RiskTier, ExecutionResult
from core.failsafe import FailsafeMonitor, FailsafeTriggered, FailsafeReason
from computer.vision import ScreenAnalyzer

class ScreenCapture(Protocol):
    def capture(self) -> bytes: ...

class MouseController(Protocol):
    def move_to(self, x: int, y: int) -> None: ...
    def click(self, x: int, y: int) -> None: ...
    def scroll(self, direction: str, clicks: int) -> None: ...

class KeyboardController(Protocol):
    def type_text(self, text: str) -> None: ...
    def hotkey(self, keys: str) -> None: ...

class ClipboardManager(Protocol):
    def get_text(self) -> str: ...
    def set_text(self, text: str) -> None: ...

class WindowManager(Protocol):
    def list_windows(self) -> list[str]: ...
    def focus_window(self, title: str) -> bool: ...


class ComputerSkill:
    """Skill providing computer control operations."""
    
    def __init__(
        self,
        failsafe: FailsafeMonitor | None = None,
        screen: ScreenCapture | None = None,
        mouse: MouseController | None = None,
        keyboard: KeyboardController | None = None,
        clipboard: ClipboardManager | None = None,
        window_manager: WindowManager | None = None,
        screen_analyzer: ScreenAnalyzer | None = None,
    ):
        from core.failsafe import FailsafeMonitor as CoreFailsafe

        self._failsafe = failsafe or CoreFailsafe()
        self._screen = screen
        self._mouse = mouse
        self._keyboard = keyboard
        self._clipboard = clipboard
        self._window_manager = window_manager
        self._screen_analyzer = screen_analyzer

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="computer",
            description="Control the computer via mouse, keyboard, and screen.",
            version="1.0",
            operations=(
                OperationSpec("screenshot", "Capture a screenshot", RiskTier.READ),
                OperationSpec("find_element", "Find a UI element on screen", RiskTier.READ),
                OperationSpec("window_list", "List open windows", RiskTier.READ),
                OperationSpec("window_focus", "Focus a window", RiskTier.MUTATE),
                OperationSpec("clipboard_get", "Read clipboard text", RiskTier.READ),
                OperationSpec("clipboard_set", "Set clipboard text", RiskTier.MUTATE),
                OperationSpec("move_mouse", "Move mouse to position", RiskTier.MUTATE),
                OperationSpec("click", "Click at position", RiskTier.CRITICAL),
                OperationSpec("type_text", "Type text", RiskTier.CRITICAL),
                OperationSpec("hotkey", "Press key combination", RiskTier.CRITICAL),
                OperationSpec("scroll", "Scroll at position", RiskTier.MUTATE),
            )
        )

    def match(self, command: str, context: Mapping[str, Any] = None) -> SkillMatch | None:
        cmd = command.lower().strip()
        name = self.metadata.name
        
        if re.search(r'(/screenshot|take a screenshot|screen capture|capture screen|screenshot edukk)', cmd):
            return SkillMatch(skill_name=name, operation="screenshot", params={})
            
        m = re.search(r'click (?:at|on) (\d+)[,\s]+(\d+)|click at position|/click', cmd)
        if m:
            if m.group(1) and m.group(2):
                return SkillMatch(skill_name=name, operation="click", params={"x": int(m.group(1)), "y": int(m.group(2))})
            return SkillMatch(skill_name=name, operation="click", params={"x": 0, "y": 0})
            
        m_app_type = re.match(
            r'type\s+(?:in|into|to)\s+([a-zA-Z0-9_\-\s]+?)\s*[:=]\s*(?:\"([^\"]+)\"|([^\n\r]+))',
            command.strip(),
            re.IGNORECASE,
        )
        if m_app_type:
            target_app = m_app_type.group(1).strip()
            text = (m_app_type.group(2) or m_app_type.group(3) or "").strip()
            return SkillMatch(skill_name=name, operation="type_text", params={"text": text, "app": target_app})

        m = re.match(
            r'type\s+"([^"]+)"\s+(?:into|in|to)\s+([a-zA-Z0-9_\-\s]+)|'
            r'type\s+([^\n\r]+?)\s+(?:into|in|to)\s+([a-zA-Z0-9_\-\s]+)|'
            r'type\s+"([^"]+)"|type\s+([^\n\r]+)|type text|/type',
            command.strip(),
            re.IGNORECASE,
        )
        if m:
            if m.group(1) and m.group(2):
                text, target_app = m.group(1), m.group(2)
                return SkillMatch(skill_name=name, operation="type_text", params={"text": text.strip(), "app": target_app.strip()})
            elif m.group(3) and m.group(4):
                text, target_app = m.group(3), m.group(4)
                return SkillMatch(skill_name=name, operation="type_text", params={"text": text.strip(), "app": target_app.strip()})
            text = m.group(5) or m.group(6) or ""
            return SkillMatch(skill_name=name, operation="type_text", params={"text": text.strip()})

        m = re.search(r'press (ctrl|alt|shift|win)[+\s](\w+)|hotkey|/hotkey', cmd)
        if m:
            if m.group(1) and m.group(2):
                return SkillMatch(skill_name=name, operation="hotkey", params={"keys": f"{m.group(1)}+{m.group(2)}"})
            return SkillMatch(skill_name=name, operation="hotkey", params={"keys": ""})
            
        m = re.search(r'move mouse to (?:coordinates\s+)?(\d+)[,\s]+(\d+)|/mouse move', cmd)
        if m:
            if m.group(1) and m.group(2):
                return SkillMatch(skill_name=name, operation="move_mouse", params={"x": int(m.group(1)), "y": int(m.group(2))})
            return SkillMatch(skill_name=name, operation="move_mouse", params={"x": 0, "y": 0})
            
        m = re.search(r'scroll (up|down)(?:\s+(\d+))?|/scroll', cmd)
        if m:
            if m.group(1):
                clicks = int(m.group(2)) if m.group(2) else 1
                return SkillMatch(skill_name=name, operation="scroll", params={"direction": m.group(1), "clicks": clicks})
            return SkillMatch(skill_name=name, operation="scroll", params={"direction": "down", "clicks": 1})

        if re.search(r'(list\s+(?:all\s+)?(?:open\s+)?(?:desktop\s+)?windows|windows\s+list|/windows|window\s+list\s+cheyyu)', cmd):
            return SkillMatch(skill_name=name, operation="window_list", params={})
            
        m = re.search(r'focus window (.+)|focus (.+) window|/window focus', cmd)
        if m:
            title = m.group(1) or m.group(2) or ""
            return SkillMatch(skill_name=name, operation="window_focus", params={"title": title})

        if re.search(r'(clipboard get|read clipboard|paste|/clipboard$)', cmd):
            return SkillMatch(skill_name=name, operation="clipboard_get", params={})
            
        m = re.search(
            r'set\s+clipboard\s+to\s+[\'"](.+?)[\'"](?:\s+and\s+verify)?|'
            r'set\s+clipboard\s+to\s+(.+?)(?:\s+and\s+verify)?$|'
            r'clipboard\s+set\s+(.+)|copy\s+(.+)|/clipboard\s+set',
            command,
            re.IGNORECASE,
        )
        if m:
            text = m.group(1) or m.group(2) or m.group(3) or m.group(4) or ""
            return SkillMatch(skill_name=name, operation="clipboard_set", params={"text": text})

        m = re.search(r'find (.+) on screen|where is (.+)|locate (.+)', command, re.IGNORECASE)
        if m:
            desc = m.group(1) or m.group(2) or m.group(3)
            return SkillMatch(skill_name=name, operation="find_element", params={"description": desc})

        return None

    def validate(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any] = None) -> Mapping[str, Any]:
        if operation in ("click", "move_mouse"):
            x, y = params.get("x", -1), params.get("y", -1)
            if not isinstance(x, int) or not isinstance(y, int) or x < 0 or y < 0 or x > 10000 or y > 10000:
                raise ValueError("Coordinates must be non-negative integers and within bounds (0-10000)")
                
        elif operation == "type_text":
            text = params.get("text", "")
            if not text or len(text) > 10000:
                raise ValueError("Text must be non-empty and max 10000 chars")
                
        elif operation == "hotkey":
            keys = params.get("keys", "")
            if not keys:
                raise ValueError("Keys must be non-empty")
                
        elif operation == "window_focus":
            title = params.get("title", "")
            if not title:
                raise ValueError("Title must be non-empty")
                
        elif operation == "clipboard_set":
            text = params.get("text", "")
            if not text or len(text) > 100000:
                raise ValueError("Text must be non-empty and max 100000 chars")
                
        elif operation == "scroll":
            direction = params.get("direction", "")
            if direction not in ("up", "down"):
                raise ValueError("Direction must be up or down")

        return dict(params)

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
        msg = message or (error if not success and error else f"Computer action '{action}' completed successfully.")
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

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any] = None) -> ExecutionResult:
        try:
            valid_params = self.validate(operation, params, context)
            
            self._failsafe.check_before_action()
            if operation == "screenshot":
                if not self._screen:
                    raise RuntimeError("ScreenCapture module not available")
                active_only = valid_params.get("active_only", False)
                if hasattr(self._screen, "capture_active_window") and active_only:
                    res_shot = self._screen.capture_active_window(self._window_manager)
                    data = res_shot.image_bytes
                else:
                    data = self._screen.capture()
                msg = "Screenshot captured"
                if self._screen_analyzer and self._screen_analyzer.is_available:
                    analysis = self._screen_analyzer.analyze(data, prompt=valid_params.get("prompt", "Describe what is currently visible."))
                    if analysis.description:
                        msg = f"Screenshot captured: {analysis.description}"
                import base64
                b64_str = base64.b64encode(data).decode("utf-8") if data else None
                return self._make_result(
                    success=True,
                    action="screenshot",
                    target="active_window" if active_only else "full_screen",
                    observation={"bytes_length": len(data), "active_only": active_only},
                    screenshot=b64_str,
                    message=msg,
                    bytes=data,
                )

            elif operation == "find_element":
                if not self._screen or not self._screen_analyzer:
                    raise RuntimeError("ScreenCapture or ScreenAnalyzer module not available")
                screenshot = self._screen.capture()
                result = self._screen_analyzer.find_element(screenshot, valid_params.get("description", ""))
                if result:
                    return self._make_result(
                        success=True,
                        action="find_element",
                        target=valid_params.get("description", ""),
                        observation=result,
                        message="Element found",
                        **result,
                    )
                return self._make_result(
                    success=False,
                    action="find_element",
                    target=valid_params.get("description", ""),
                    error="Element not found",
                    message="Element not found",
                )

            elif operation == "window_list":
                if not self._window_manager:
                    raise RuntimeError("WindowManager module not available")
                windows = self._window_manager.list_windows()
                return self._make_result(
                    success=True,
                    action="window_list",
                    target="desktop",
                    observation={"windows": windows, "count": len(windows)},
                    message=f"Found {len(windows)} desktop window(s)",
                    windows=windows,
                )

            elif operation == "window_focus":
                if not self._window_manager:
                    raise RuntimeError("WindowManager module not available")
                title = valid_params.get("title", "")
                success = bool(self._window_manager.focus_window(title))
                return self._make_result(
                    success=success,
                    action="window_focus",
                    target=title,
                    observation={"focused": success, "title": title},
                    message=f"Focus window {title}",
                    success_flag=success,
                )

            elif operation == "clipboard_get":
                if not self._clipboard:
                    raise RuntimeError("ClipboardManager module not available")
                text = self._clipboard.get_text()
                return self._make_result(
                    success=True,
                    action="clipboard_get",
                    observation={"text": text},
                    message="Clipboard text read",
                    text=text,
                )

            elif operation == "clipboard_set":
                if not self._clipboard:
                    raise RuntimeError("ClipboardManager module not available")
                text = valid_params.get("text", "")
                self._clipboard.set_text(text)
                return self._make_result(
                    success=True,
                    action="clipboard_set",
                    observation={"text": text},
                    message=f"Clipboard text set to '{text}'",
                )

            elif operation == "move_mouse":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                x, y = valid_params.get("x", 0), valid_params.get("y", 0)
                self._mouse.move_to(x, y)
                return self._make_result(
                    success=True,
                    action="move_mouse",
                    target=f"{x},{y}",
                    observation={"x": x, "y": y},
                    message=f"Mouse moved to coordinates {x},{y}",
                )

            elif operation == "click":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                x, y = valid_params.get("x", 0), valid_params.get("y", 0)
                btn = str(valid_params.get("button", "left")).lower()
                if btn == "right" and hasattr(self._mouse, "right_click"):
                    self._mouse.right_click(x, y)
                elif btn == "double" and hasattr(self._mouse, "double_click"):
                    self._mouse.double_click(x, y)
                else:
                    self._mouse.click(x, y)
                return self._make_result(
                    success=True,
                    action="click",
                    target=f"{x},{y}",
                    observation={"x": x, "y": y, "button": btn},
                    message=f"Clicked at {x},{y}",
                )

            elif operation == "type_text":
                if not self._keyboard:
                    raise RuntimeError("KeyboardController module not available")
                text = valid_params.get("text", "")
                target_app = valid_params.get("app")
                if target_app and self._window_manager:
                    try:
                        w = self._window_manager.find_window(target_app)
                        if w:
                            self._window_manager.focus_window(w.handle)
                            import time
                            time.sleep(0.3)
                    except Exception:
                        pass
                self._keyboard.type_text(text)
                try:
                    from core.context import CURRENT_DEVICE_CONTEXT
                    CURRENT_DEVICE_CONTEXT.metadata["last_typed_text"] = text
                except Exception:
                    pass
                return self._make_result(
                    success=True,
                    action="type_text",
                    target=target_app or "active_window",
                    observation={"text_length": len(text), "app": target_app},
                    message=f"Typed text: '{text}'",
                )

            elif operation == "hotkey":
                if not self._keyboard:
                    raise RuntimeError("KeyboardController module not available")
                keys = valid_params.get("keys", "")
                self._keyboard.hotkey(keys)
                return self._make_result(
                    success=True,
                    action="hotkey",
                    target=keys,
                    observation={"keys": keys},
                    message=f"Hotkey {keys} pressed",
                )

            elif operation == "scroll":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                direction = valid_params.get("direction", "down")
                clicks = valid_params.get("clicks", 1)
                self._mouse.scroll(direction, clicks)
                return self._make_result(
                    success=True,
                    action="scroll",
                    target=direction,
                    observation={"direction": direction, "clicks": clicks},
                    message=f"Scrolled {direction}",
                )
                
            return self._make_result(
                success=False,
                action=operation,
                error="Unknown operation",
                message="Unknown operation",
            )

        except FailsafeTriggered as exc:
            return self._make_result(
                success=False,
                action=operation,
                error=str(exc),
                message=f"Failsafe triggered: {exc.reason}",
            )
        except RuntimeError as exc:
            return self._make_result(
                success=False,
                action=operation,
                error=str(exc),
                message=str(exc),
            )
        except Exception as exc:
            return self._make_result(
                success=False,
                action=operation,
                error=str(exc),
                message=str(exc),
            )
