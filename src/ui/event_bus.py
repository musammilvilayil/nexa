from __future__ import annotations

import asyncio
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Sequence


class UIEventType(str, Enum):
    TASK_CREATED = "TASK_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_STEP_STARTED = "TASK_STEP_STARTED"
    TASK_STEP_COMPLETED = "TASK_STEP_COMPLETED"
    TOOL_STARTED = "TOOL_STARTED"
    TOOL_COMPLETED = "TOOL_COMPLETED"
    CAPABILITY_DISCOVERED = "CAPABILITY_DISCOVERED"
    CAPABILITY_BUILDING = "CAPABILITY_BUILDING"
    CAPABILITY_VALIDATING = "CAPABILITY_VALIDATING"
    CAPABILITY_REGISTERED = "CAPABILITY_REGISTERED"
    BROWSER_ACTION = "BROWSER_ACTION"
    DESKTOP_ACTION = "DESKTOP_ACTION"
    SECURITY_CHECK = "SECURITY_CHECK"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_ACCEPTED = "CONFIRMATION_ACCEPTED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    TASK_RECOVERED = "TASK_RECOVERED"
    TASK_PAUSED = "TASK_PAUSED"
    TASK_RESUMED = "TASK_RESUMED"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    VOICE_LISTENING = "VOICE_LISTENING"
    VOICE_TRANSCRIBING = "VOICE_TRANSCRIBING"
    VOICE_RESPONSE = "VOICE_RESPONSE"
    SYSTEM_HEALTH_CHANGED = "SYSTEM_HEALTH_CHANGED"


SECRET_KEY_PATTERNS = re.compile(
    r"(?:password|passwd|token|secret|api_key|apikey|authorization|auth|bearer|otp|cookie|session_id|private_key|credential)",
    re.IGNORECASE,
)

BEARER_TOKEN_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE)


def sanitize_event_data(data: Any) -> Any:
    """Recursively redacts sensitive info and ensures all structures are JSON-safe."""
    if data is None or isinstance(data, (int, float, bool)):
        return data
    if isinstance(data, str):
        return BEARER_TOKEN_RE.sub(r"\1[REDACTED]", data)
    if hasattr(data, "__dataclass_fields__"):
        try:
            return sanitize_event_data(asdict(data))
        except Exception:
            return str(data)
    from pathlib import Path as _Path
    if isinstance(data, (_Path, uuid.UUID)):
        return str(data)
    if isinstance(data, Enum):
        return data.value
    if isinstance(data, Mapping):
        sanitized = {}
        for k, v in data.items():
            k_str = str(k)
            if SECRET_KEY_PATTERNS.search(k_str):
                sanitized[k_str] = "[REDACTED]"
            else:
                sanitized[k_str] = sanitize_event_data(v)
        return sanitized
    if isinstance(data, (list, tuple, set, frozenset)):
        return [sanitize_event_data(item) for item in data]
    if hasattr(data, "to_dict") and callable(data.to_dict):
        try:
            return sanitize_event_data(data.to_dict())
        except Exception:
            pass
    if hasattr(data, "__dict__"):
        try:
            return sanitize_event_data(vars(data))
        except Exception:
            return str(data)
    return str(data)


@dataclass(frozen=True)
class UIEvent:
    event_id: str
    event_type: UIEventType
    timestamp: str
    title: str
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    task_id: str | None = None
    step_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "title": self.title,
            "message": self.message,
            "data": self.data,
            "task_id": self.task_id,
            "step_id": self.step_id,
        }


class UIEventBus:
    """Thread-safe and async-compatible real-time event bus for NEXA UI."""

    def __init__(self, max_history: int = 1000) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[UIEvent], None]] = []
        self._async_queues: set[asyncio.Queue[UIEvent]] = set()
        self._history: list[UIEvent] = []
        self._max_history = max_history

    def emit(
        self,
        event_type: UIEventType | str,
        title: str,
        message: str = "",
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
        step_id: int | None = None,
    ) -> UIEvent:
        if isinstance(event_type, str):
            event_type = UIEventType(event_type)

        now = datetime.now(timezone.utc).isoformat()
        sanitized_data = sanitize_event_data(data or {})

        event = UIEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            timestamp=now,
            title=title,
            message=message,
            data=sanitized_data,
            task_id=task_id,
            step_id=step_id,
        )

        with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            sync_subs = list(self._subscribers)
            async_queues = list(self._async_queues)

        # Notify synchronous callbacks
        for sub in sync_subs:
            try:
                sub(event)
            except Exception:
                pass

        # Notify async queues
        for queue in async_queues:
            try:
                queue.put_nowait(event)
            except Exception:
                pass

        return event

    def subscribe(self, callback: Callable[[UIEvent], None]) -> None:
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[UIEvent], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def register_async_queue(self) -> asyncio.Queue[UIEvent]:
        queue: asyncio.Queue[UIEvent] = asyncio.Queue()
        with self._lock:
            self._async_queues.add(queue)
        return queue

    def unregister_async_queue(self, queue: asyncio.Queue[UIEvent]) -> None:
        with self._lock:
            self._async_queues.discard(queue)

    def get_recent_events(
        self,
        limit: int = 50,
        event_type: UIEventType | None = None,
        task_id: str | None = None,
    ) -> list[UIEvent]:
        with self._lock:
            filtered = self._history
            if event_type is not None:
                filtered = [e for e in filtered if e.event_type == event_type]
            if task_id is not None:
                filtered = [e for e in filtered if e.task_id == task_id]
            return filtered[-limit:]

    def clear_history(self) -> None:
        with self._lock:
            self._history.clear()


_GLOBAL_EVENT_BUS: UIEventBus | None = None
_GLOBAL_BUS_LOCK = threading.Lock()


def get_event_bus() -> UIEventBus:
    global _GLOBAL_EVENT_BUS
    with _GLOBAL_BUS_LOCK:
        if _GLOBAL_EVENT_BUS is None:
            _GLOBAL_EVENT_BUS = UIEventBus()
        return _GLOBAL_EVENT_BUS
