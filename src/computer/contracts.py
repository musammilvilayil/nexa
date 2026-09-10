from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class MouseButton(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class ScreenshotResult:
    image_bytes: bytes
    width: int
    height: int
    monitor: int = 0
    format: str = "png"


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    process_name: str = ""
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h
    is_visible: bool = True
    is_focused: bool = False


@dataclass(frozen=True)
class ActionResult:
    success: bool
    message: str = ""
    data: Any = None
    error: str | None = None


class FailsafeTriggered(Exception):
    """Raised when a failsafe mechanism intercepts an action."""
    pass


class FailsafeMonitor(Protocol):
    def check_before_action(self, **kwargs: Any) -> None:
        """Check rules before allowing an action to proceed."""
        ...
