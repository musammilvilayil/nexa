from __future__ import annotations

import re
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: str = field(default_factory=_utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class ConversationMemory:
    """Stores multi-turn conversational history with metadata."""

    def __init__(self, max_turns: int = 100) -> None:
        self.max_turns = max_turns
        self._turns: list[ConversationTurn] = []
        self._lock = threading.Lock()

    def add_turn(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> ConversationTurn:
        turn = ConversationTurn(role=role, content=content, metadata=metadata or {})
        with self._lock:
            self._turns.append(turn)
            if len(self._turns) > self.max_turns:
                self._turns.pop(0)
        return turn

    def get_history(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            selected = self._turns[-limit:] if limit > 0 else self._turns
            return [asdict(t) for t in selected]

    def clear(self) -> None:
        with self._lock:
            self._turns.clear()


class UserPreferenceMemory:
    """Stores key-value user preferences (e.g. default browser, editor, language)."""

    def __init__(self, initial_prefs: Mapping[str, Any] | None = None) -> None:
        self._prefs: dict[str, Any] = dict(initial_prefs or {})
        self._lock = threading.Lock()

    def get_preference(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._prefs.get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        with self._lock:
            self._prefs[key] = value

    def delete_preference(self, key: str) -> None:
        with self._lock:
            self._prefs.pop(key, None)

    def list_preferences(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._prefs)


@dataclass
class TaskStep:
    description: str
    status: str = "completed"
    result: Any = None
    timestamp: str = field(default_factory=_utc_now)


@dataclass
class TaskRecord:
    task_id: str
    goal: str
    current_subgoal: str = ""
    status: str = "active"
    steps: list[TaskStep] = field(default_factory=list)
    start_time: str = field(default_factory=_utc_now)
    end_time: str | None = None
    error: str | None = None


class TaskMemory:
    """Tracks active task, goals, sub-goals, completed steps, and execution history."""

    def __init__(self) -> None:
        self._active_task: TaskRecord | None = None
        self._history: list[TaskRecord] = []
        self._lock = threading.Lock()

    def start_task(self, task_id: str, goal: str, planned_steps: list[str] | None = None) -> TaskRecord:
        with self._lock:
            if self._active_task and self._active_task.status == "active":
                self._active_task.status = "interrupted"
                self._active_task.end_time = _utc_now()
                self._history.append(self._active_task)

            record = TaskRecord(task_id=task_id, goal=goal)
            if planned_steps:
                record.current_subgoal = planned_steps[0]
            self._active_task = record
            return record

    def update_subgoal(self, current_subgoal: str) -> None:
        with self._lock:
            if self._active_task:
                self._active_task.current_subgoal = current_subgoal

    def record_step(self, step_description: str, status: str = "completed", result: Any = None) -> None:
        with self._lock:
            if self._active_task:
                self._active_task.steps.append(
                    TaskStep(description=step_description, status=status, result=result)
                )

    def complete_task(self, status: str = "success", error: str | None = None) -> TaskRecord | None:
        with self._lock:
            if not self._active_task:
                return None
            self._active_task.status = status
            self._active_task.error = error
            self._active_task.end_time = _utc_now()
            completed = self._active_task
            self._history.append(completed)
            self._active_task = None
            return completed

    def get_active_task(self) -> dict[str, Any] | None:
        with self._lock:
            return asdict(self._active_task) if self._active_task else None

    def get_task_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(t) for t in self._history]


class CapabilityMemory:
    """Tracks capability usage, dynamic gap encounters, and tool performance metrics."""

    def __init__(self) -> None:
        self._usage: dict[str, dict[str, int]] = {}  # cap_id -> {"success": int, "failure": int}
        self._gaps: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def record_usage(self, capability_id: str, success: bool) -> None:
        with self._lock:
            stats = self._usage.setdefault(capability_id, {"success": 0, "failure": 0})
            if success:
                stats["success"] += 1
            else:
                stats["failure"] += 1

    def record_gap(self, query: str, detected_gap: str) -> None:
        with self._lock:
            self._gaps.append({"query": query, "gap": detected_gap, "timestamp": _utc_now()})

    def get_usage_summary(self) -> dict[str, dict[str, int]]:
        with self._lock:
            return {k: dict(v) for k, v in self._usage.items()}

    def get_unresolved_gaps(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._gaps)


class ApplicationContext:
    """Tracks the state of local desktop applications and window focus."""

    def __init__(self) -> None:
        self._active_window: dict[str, Any] = {"title": "", "process_name": "", "handle": 0}
        self._running_apps: list[str] = []
        self._recent_apps: list[str] = []
        self._lock = threading.Lock()

    def set_active_window(self, title: str, process_name: str = "", handle: int = 0) -> None:
        with self._lock:
            self._active_window = {
                "title": title,
                "process_name": process_name,
                "handle": handle,
                "updated_at": _utc_now(),
            }
            if process_name and (not self._recent_apps or self._recent_apps[-1] != process_name):
                self._recent_apps.append(process_name)
                if len(self._recent_apps) > 20:
                    self._recent_apps.pop(0)

    def get_active_window(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._active_window)

    def set_running_apps(self, apps: list[str]) -> None:
        with self._lock:
            self._running_apps = list(apps)

    def get_running_apps(self) -> list[str]:
        with self._lock:
            return list(self._running_apps)


class BrowserContext:
    """Tracks active browser state, open tabs, search history, and resolves search continuation."""

    ORDINALS = {
        "first": 0, "1st": 0,
        "second": 1, "2nd": 1,
        "third": 2, "3rd": 2,
        "fourth": 3, "4th": 3,
        "fifth": 4, "5th": 4,
        "sixth": 5, "6th": 5,
        "seventh": 6, "7th": 6,
        "eighth": 7, "8th": 7,
        "ninth": 8, "9th": 8,
        "tenth": 9, "10th": 9,
    }

    CARDINALS = {
        "one": 0,
        "two": 1,
        "three": 2,
        "four": 3,
        "five": 4,
    }

    def __init__(self) -> None:
        self._current_page: dict[str, str] = {"url": "", "title": ""}
        self._open_tabs: list[dict[str, Any]] = []
        self._search_results: list[dict[str, str]] = []  # ordered search links
        self._lock = threading.Lock()

    def set_current_page(self, url: str, title: str = "") -> None:
        with self._lock:
            self._current_page = {"url": url, "title": title, "timestamp": _utc_now()}

    def get_current_page(self) -> dict[str, str]:
        with self._lock:
            return dict(self._current_page)

    def record_search_results(self, results: list[dict[str, str] | str]) -> None:
        """Stores ordered search result links (e.g. from Google or internal search)."""
        normalized: list[dict[str, str]] = []
        for item in results:
            if isinstance(item, str):
                normalized.append({"title": item, "url": item})
            elif isinstance(item, dict):
                normalized.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("snippet", ""),
                })
        with self._lock:
            self._search_results = normalized

    def get_search_results(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(r) for r in self._search_results]

    def resolve_search_continuation(self, reference: str) -> dict[str, str] | None:
        """Resolves continuation references like 'the second one', 'open the first link', 'result 3'."""
        with self._lock:
            if not self._search_results:
                return None

            ref_lower = reference.lower().strip()

            # Check special 'last'
            if "last" in ref_lower:
                idx = len(self._search_results) - 1
                res = dict(self._search_results[idx])
                res["index"] = idx
                return res

            # Scan for explicit ordinal words first ("first", "second", etc.)
            for pattern, idx in self.ORDINALS.items():
                if re.search(rf"\b{pattern}\b", ref_lower):
                    if idx < len(self._search_results):
                        res = dict(self._search_results[idx])
                        res["index"] = idx
                        return res

            # Check explicit digit match like "result 2", "#2", or "link 2"
            num_match = re.search(r"(?:result|number|#|\blink\b)\s*(\d+)", ref_lower)
            if num_match:
                idx = int(num_match.group(1)) - 1
                if 0 <= idx < len(self._search_results):
                    res = dict(self._search_results[idx])
                    res["index"] = idx
                    return res

            # Check named cardinal after prefix: "result two", "link three"
            for word, idx in self.CARDINALS.items():
                if re.search(rf"(?:result|number|#|\blink\b)\s+{word}\b", ref_lower):
                    if idx < len(self._search_results):
                        res = dict(self._search_results[idx])
                        res["index"] = idx
                        return res

            return None


class DeviceContext:
    """Tracks physical and graphical display device properties."""

    def __init__(
        self,
        screen_width: int = 1920,
        screen_height: int = 1080,
        dpi_scale: float = 1.0,
        os_info: str = "Windows",
        monitors_count: int = 1,
    ) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.dpi_scale = dpi_scale
        self.os_info = os_info
        self.monitors_count = monitors_count
        self._lock = threading.Lock()

    def update_resolution(self, width: int, height: int, dpi_scale: float = 1.0) -> None:
        with self._lock:
            self.screen_width = width
            self.screen_height = height
            self.dpi_scale = dpi_scale

    def get_device_info(self) -> dict[str, Any]:
        with self._lock:
            return {
                "screen_width": self.screen_width,
                "screen_height": self.screen_height,
                "dpi_scale": self.dpi_scale,
                "os_info": self.os_info,
                "monitors_count": self.monitors_count,
            }


class UnifiedMemory:
    """Central unified multi-layer memory coordinating all 7 specialized memory layers."""

    def __init__(self) -> None:
        self.conversation = ConversationMemory()
        self.user_preferences = UserPreferenceMemory()
        self.task = TaskMemory()
        self.capabilities = CapabilityMemory()
        self.application = ApplicationContext()
        self.browser = BrowserContext()
        self.device = DeviceContext()

    def snapshot(self) -> dict[str, Any]:
        """Provides a composite serializable snapshot of all memory layers."""
        return {
            "conversation_history": self.conversation.get_history(limit=5),
            "user_preferences": self.user_preferences.list_preferences(),
            "active_task": self.task.get_active_task(),
            "application_context": self.application.get_active_window(),
            "browser_page": self.browser.get_current_page(),
            "search_results_count": len(self.browser.get_search_results()),
            "device_info": self.device.get_device_info(),
        }
