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


@dataclass
class EpisodeRecord:
    episode_id: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)
    outcome: str = "success"
    timestamp: str = field(default_factory=_utc_now)


class EpisodicMemory:
    """Layer 8: Stores chronological episodic memories of user interactions, task executions, and outcomes."""

    def __init__(self, max_episodes: int = 500) -> None:
        self.max_episodes = max_episodes
        self._episodes: list[EpisodeRecord] = []
        self._lock = threading.Lock()

    def store_episode(
        self,
        summary: str,
        details: Mapping[str, Any] | None = None,
        outcome: str = "success",
        timestamp: str | None = None,
    ) -> EpisodeRecord:
        with self._lock:
            ep = EpisodeRecord(
                episode_id=f"ep_{len(self._episodes) + 1}",
                summary=summary,
                details=dict(details or {}),
                outcome=outcome,
                timestamp=timestamp or _utc_now(),
            )
            self._episodes.append(ep)
            if len(self._episodes) > self.max_episodes:
                self._episodes.pop(0)
            return ep

    def recall_episodes(self, query: str = "", limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            q = query.lower().strip()
            matches = [
                asdict(e)
                for e in self._episodes
                if not q or q in e.summary.lower() or any(q in str(v).lower() for v in e.details.values())
            ]
            return matches[-limit:] if limit > 0 else matches

    def get_timeline(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(e) for e in self._episodes[-limit:]]


@dataclass(frozen=True)
class FactRecord:
    subject: str
    predicate: str
    object_: str
    confidence: float = 1.0
    created_at: str = field(default_factory=_utc_now)


class SemanticMemory:
    """Layer 9: Stores structured knowledge graph facts (subject, predicate, object, confidence)."""

    def __init__(self) -> None:
        self._facts: list[FactRecord] = []
        self._lock = threading.Lock()

    def store_fact(
        self,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
    ) -> FactRecord:
        with self._lock:
            s_clean = subject.strip().lower()
            p_clean = predicate.strip().lower()
            self._facts = [
                f for f in self._facts
                if not (f.subject.lower() == s_clean and f.predicate.lower() == p_clean)
            ]
            fact = FactRecord(
                subject=subject.strip(),
                predicate=predicate.strip(),
                object_=object_.strip(),
                confidence=confidence,
            )
            self._facts.append(fact)
            return fact

    def query_facts(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object_: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for f in self._facts:
                if subject and subject.lower() not in f.subject.lower():
                    continue
                if predicate and predicate.lower() not in f.predicate.lower():
                    continue
                if object_ and object_.lower() not in f.object_.lower():
                    continue
                results.append({
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object_,
                    "confidence": f.confidence,
                    "created_at": f.created_at,
                })
            return results

    def find_related(self, entity: str) -> list[dict[str, Any]]:
        with self._lock:
            ent = entity.lower().strip()
            return [
                {
                    "subject": f.subject,
                    "predicate": f.predicate,
                    "object": f.object_,
                    "confidence": f.confidence,
                }
                for f in self._facts
                if ent in f.subject.lower() or ent in f.object_.lower()
            ]


@dataclass
class ProcedureRecord:
    task_type: str
    steps: list[dict[str, Any]]
    prerequisites: list[str] = field(default_factory=list)
    success_rate: float = 1.0
    use_count: int = 1
    created_at: str = field(default_factory=_utc_now)


class ProceduralMemory:
    """Layer 10: Stores reusable execution workflows and learned procedural playbooks."""

    def __init__(self) -> None:
        self._procedures: dict[str, ProcedureRecord] = {}
        self._lock = threading.Lock()

    def store_procedure(
        self,
        task_type: str,
        steps: list[dict[str, Any]],
        prerequisites: list[str] | None = None,
        success_rate: float = 1.0,
    ) -> ProcedureRecord:
        with self._lock:
            key = task_type.strip().lower()
            existing = self._procedures.get(key)
            if existing:
                existing.steps = list(steps)
                existing.prerequisites = list(prerequisites or [])
                existing.success_rate = (existing.success_rate + success_rate) / 2.0
                existing.use_count += 1
                return existing

            rec = ProcedureRecord(
                task_type=task_type.strip(),
                steps=list(steps),
                prerequisites=list(prerequisites or []),
                success_rate=success_rate,
            )
            self._procedures[key] = rec
            return rec

    def recall_procedure(self, task_type: str) -> dict[str, Any] | None:
        with self._lock:
            rec = self._procedures.get(task_type.strip().lower())
            if not rec:
                return None
            return {
                "task_type": rec.task_type,
                "steps": [dict(s) for s in rec.steps],
                "prerequisites": list(rec.prerequisites),
                "success_rate": rec.success_rate,
                "use_count": rec.use_count,
            }

    def list_procedures(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "task_type": p.task_type,
                    "step_count": len(p.steps),
                    "success_rate": p.success_rate,
                    "use_count": p.use_count,
                }
                for p in self._procedures.values()
            ]


class UnifiedMemory:
    """Central unified multi-layer memory coordinating all 10 specialized memory layers."""

    def __init__(self) -> None:
        self.conversation = ConversationMemory()
        self.user_preferences = UserPreferenceMemory()
        self.task = TaskMemory()
        self.capabilities = CapabilityMemory()
        self.application = ApplicationContext()
        self.browser = BrowserContext()
        self.device = DeviceContext()
        # Level 5 Advanced Memory Layers:
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.procedural = ProceduralMemory()

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
            "episodic_count": len(self.episodic.get_timeline(limit=100)),
            "semantic_facts_count": len(self.semantic.query_facts()),
            "procedures_count": len(self.procedural.list_procedures()),
        }

    def unified_search(self, query: str, limit: int = 5) -> dict[str, list[Any]]:
        """Cross-layer semantic and textual query across all memory layers."""
        q = query.lower().strip()
        results: dict[str, list[Any]] = {
            "conversation": [
                t for t in self.conversation.get_history(limit=50)
                if q in t.get("content", "").lower()
            ][:limit],
            "preferences": [
                {"key": k, "value": v}
                for k, v in self.user_preferences.list_preferences().items()
                if q in k.lower() or q in str(v).lower()
            ][:limit],
            "episodes": self.episodic.recall_episodes(query, limit=limit),
            "facts": self.semantic.find_related(query)[:limit],
            "procedures": [
                p for p in self.procedural.list_procedures()
                if q in p["task_type"].lower()
            ][:limit],
        }
        return results
