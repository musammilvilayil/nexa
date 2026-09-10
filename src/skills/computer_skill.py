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
            
        m = re.search(r'type "(.+)"|type text|/type', command)
        if m:
            if m.group(1):
                return SkillMatch(skill_name=name, operation="type_text", params={"text": m.group(1)})
            return SkillMatch(skill_name=name, operation="type_text", params={"text": ""})

        m = re.search(r'press (ctrl|alt|shift|win)[+\s](\w+)|hotkey|/hotkey', cmd)
        if m:
            if m.group(1) and m.group(2):
                return SkillMatch(skill_name=name, operation="hotkey", params={"keys": f"{m.group(1)}+{m.group(2)}"})
            return SkillMatch(skill_name=name, operation="hotkey", params={"keys": ""})
            
        m = re.search(r'move mouse to (\d+)[,\s]+(\d+)|/mouse move', cmd)
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

        if re.search(r'(list windows|windows list|/windows|window list cheyyu)', cmd):
            return SkillMatch(skill_name=name, operation="window_list", params={})
            
        m = re.search(r'focus window (.+)|focus (.+) window|/window focus', cmd)
        if m:
            title = m.group(1) or m.group(2) or ""
            return SkillMatch(skill_name=name, operation="window_focus", params={"title": title})

        if re.search(r'(clipboard get|read clipboard|paste|/clipboard$)', cmd):
            return SkillMatch(skill_name=name, operation="clipboard_get", params={})
            
        m = re.search(r'clipboard set (.+)|copy (.+)|/clipboard set', command)
        if m:
            text = m.group(1) or m.group(2) or ""
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

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any] = None) -> ExecutionResult:
        try:
            valid_params = self.validate(operation, params, context)
            
            self._failsafe.check_before_action()
            if operation == "screenshot":
                if not self._screen:
                    raise RuntimeError("ScreenCapture module not available")
                data = self._screen.capture()
                msg = "Screenshot captured"
                if self._screen_analyzer and self._screen_analyzer.is_available:
                    analysis = self._screen_analyzer.analyze(data, prompt=valid_params.get("prompt", "Describe what is currently visible."))
                    if analysis.description:
                        msg = f"Screenshot captured: {analysis.description}"
                return ExecutionResult(success=True, message=msg, data={"bytes": data})

            elif operation == "find_element":
                if not self._screen or not self._screen_analyzer:
                    raise RuntimeError("ScreenCapture or ScreenAnalyzer module not available")
                screenshot = self._screen.capture()
                result = self._screen_analyzer.find_element(screenshot, valid_params.get("description", ""))
                if result:
                    return ExecutionResult(success=True, message="Element found", data=result)
                return ExecutionResult(success=False, message="Element not found")

            elif operation == "window_list":
                if not self._window_manager:
                    raise RuntimeError("WindowManager module not available")
                windows = self._window_manager.list_windows()
                return ExecutionResult(success=True, message="Windows listed", data={"windows": windows})

            elif operation == "window_focus":
                if not self._window_manager:
                    raise RuntimeError("WindowManager module not available")
                title = valid_params.get("title", "")
                success = self._window_manager.focus_window(title)
                return ExecutionResult(success=success, message=f"Focus window {title}", data={"success": success})

            elif operation == "clipboard_get":
                if not self._clipboard:
                    raise RuntimeError("ClipboardManager module not available")
                text = self._clipboard.get_text()
                return ExecutionResult(success=True, message="Clipboard text read", data={"text": text})

            elif operation == "clipboard_set":
                if not self._clipboard:
                    raise RuntimeError("ClipboardManager module not available")
                text = valid_params.get("text", "")
                self._clipboard.set_text(text)
                return ExecutionResult(success=True, message="Clipboard text set")

            elif operation == "move_mouse":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                x, y = valid_params.get("x", 0), valid_params.get("y", 0)
                self._mouse.move_to(x, y)
                return ExecutionResult(success=True, message=f"Mouse moved to {x},{y}")

            elif operation == "click":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                x, y = valid_params.get("x", 0), valid_params.get("y", 0)
                self._mouse.click(x, y)
                return ExecutionResult(success=True, message=f"Clicked at {x},{y}")

            elif operation == "type_text":
                if not self._keyboard:
                    raise RuntimeError("KeyboardController module not available")
                text = valid_params.get("text", "")
                self._keyboard.type_text(text)
                return ExecutionResult(success=True, message="Text typed")

            elif operation == "hotkey":
                if not self._keyboard:
                    raise RuntimeError("KeyboardController module not available")
                keys = valid_params.get("keys", "")
                self._keyboard.hotkey(keys)
                return ExecutionResult(success=True, message=f"Hotkey {keys} pressed")

            elif operation == "scroll":
                if not self._mouse:
                    raise RuntimeError("MouseController module not available")
                direction = valid_params.get("direction", "down")
                clicks = valid_params.get("clicks", 1)
                self._mouse.scroll(direction, clicks)
                return ExecutionResult(success=True, message=f"Scrolled {direction}")
                
            return ExecutionResult(success=False, message="Unknown operation", error="Unknown operation")

        except FailsafeTriggered as exc:
            return ExecutionResult(success=False, message=f"Failsafe triggered: {exc.reason}", error=str(exc))
        except RuntimeError as exc:
            return ExecutionResult(success=False, message=str(exc), error=str(exc))
        except Exception as exc:
            return ExecutionResult(success=False, message=str(exc), error=str(exc))
