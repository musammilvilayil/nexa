from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from aiohttp import WSMsgType, web

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import heapq
from control_plane import RuntimeControlPlane
from core.contracts import RiskTier
from planner.long_running import LongRunningTaskState
from runtime import NexaRuntime, build_runtime

from .autostart import disable_autostart, enable_autostart, is_autostart_enabled
from .conversation_store import ConversationStore
from .event_bus import UIEvent, UIEventBus, UIEventType, get_event_bus


from dataclasses import asdict, is_dataclass

def make_json_safe(obj: Any) -> Any:
    """Recursively converts bytes, paths, and non-serializable objects to JSON-safe values."""
    if obj is None or isinstance(obj, (int, float, bool, str)):
        return obj
    if isinstance(obj, bytes):
        return f"<bytes: {len(obj)} bytes>"
    if isinstance(obj, (Path, os.PathLike)):
        return str(obj)
    if hasattr(obj, "__dataclass_fields__") or is_dataclass(obj):
        try:
            return make_json_safe(asdict(obj))
        except Exception:
            return str(obj)
    if isinstance(obj, dict):
        return {str(k): make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [make_json_safe(x) for x in obj]
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        try:
            return make_json_safe(obj.to_dict())
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return make_json_safe(vars(obj))
        except Exception:
            return str(obj)
    return str(obj)


def get_system_metrics() -> dict[str, Any]:
    """Collects real hardware metrics (CPU, RAM, C: SSD, D: HDD, Network)."""
    # 1. Drives
    drives = {}
    for letter in ["C:", "D:"]:
        path = f"{letter}\\" if sys.platform == "win32" else letter
        try:
            usage = shutil.disk_usage(path)
            total_gb = round(usage.total / (1024**3), 1)
            used_gb = round(usage.used / (1024**3), 1)
            free_gb = round(usage.free / (1024**3), 1)
            free_pct = round((usage.free / usage.total) * 100, 1) if usage.total > 0 else 0.0
            drives[letter] = {
                "total_gb": total_gb,
                "used_gb": used_gb,
                "free_gb": free_gb,
                "free_percent": free_pct,
            }
        except Exception:
            pass

    # 2. Memory (RAM)
    ram_metrics = {"total_gb": 16.0, "used_gb": 8.0, "free_gb": 8.0, "used_percent": 50.0}
    if sys.platform == "win32":
        try:
            import ctypes

            class MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MemoryStatusEx()
            stat.dwLength = ctypes.sizeof(MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                tot = round(stat.ullTotalPhys / (1024**3), 1)
                avail = round(stat.ullAvailPhys / (1024**3), 1)
                used = round(tot - avail, 1)
                ram_metrics = {
                    "total_gb": tot,
                    "used_gb": used,
                    "free_gb": avail,
                    "used_percent": float(stat.dwMemoryLoad),
                }
        except Exception:
            pass

    # 3. CPU info
    cpu_count = os.cpu_count() or 4

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cpu": {
            "cores": cpu_count,
            "architecture": sys.platform,
        },
        "ram": ram_metrics,
        "drives": drives,
    }


@web.middleware
async def cors_middleware(request: web.Request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPRedirection:
            raise
        except web.HTTPException as ex:
            response = ex
        except Exception as ex:
            response = web.json_response(
                {
                    "success": False,
                    "status": "failed",
                    "error": str(ex),
                    "message": f"Internal server error: {ex}",
                },
                status=500,
            )
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    return response


class NexaUIServer:
    """Async WebSocket and HTTP REST backend for NEXA Level 5 Desktop UI."""

    def __init__(
        self,
        control: RuntimeControlPlane | None = None,
        event_bus: UIEventBus | None = None,
        host: str = "127.0.0.1",
        port: int = 8765,
    ) -> None:
        if control is None:
            self.control = RuntimeControlPlane(build_runtime())
            self.runtime = self.control.runtime
        elif isinstance(control, RuntimeControlPlane):
            self.control = control
            self.runtime = control.runtime
        else:
            self.runtime = control
            self.control = getattr(control, "control", None) or RuntimeControlPlane(control)
        self.event_bus = event_bus or get_event_bus()
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[cors_middleware])
        self.runner: web.AppRunner | None = None
        self._pending_plans: dict[str, Any] = {}
        self.conversation_store = ConversationStore()
        self._training_controller: Any | None = None
        self._training_thread: threading.Thread | None = None
        self._setup_routes()

    def _setup_routes(self) -> None:
        # WebSocket
        self.app.router.add_get("/ws", self.ws_handler)

        # Core Command & Control REST APIs
        self.app.router.add_get("/api/health", self.handle_health)
        self.app.router.add_post("/api/command", self.handle_command)
        self.app.router.add_post("/api/confirm", self.handle_confirm)
        self.app.router.add_post("/api/cancel", self.handle_cancel)
        self.app.router.add_get("/api/status", self.handle_status)
        self.app.router.add_get("/api/metrics", self.handle_metrics)

        # Conversations API
        self.app.router.add_get("/api/conversations", self.handle_get_conversations)
        self.app.router.add_post("/api/conversations", self.handle_post_conversations)
        self.app.router.add_get("/api/conversations/{conv_id}", self.handle_get_conversation)
        self.app.router.add_delete("/api/conversations/{conv_id}", self.handle_delete_conversation)

        # Tasks API
        self.app.router.add_get("/api/tasks", self.handle_get_tasks)
        self.app.router.add_post("/api/tasks", self.handle_post_task)
        self.app.router.add_post("/api/task/start", self.handle_post_task)
        self.app.router.add_post("/api/task-start", self.handle_post_task)
        self.app.router.add_post("/api/tasks/{task_id}/pause", self.handle_task_pause)
        self.app.router.add_post("/api/task/{task_id}/pause", self.handle_task_pause)
        self.app.router.add_post("/api/task-pause", self.handle_task_pause)

        self.app.router.add_post("/api/tasks/{task_id}/resume", self.handle_task_resume)
        self.app.router.add_post("/api/task/{task_id}/resume", self.handle_task_resume)
        self.app.router.add_post("/api/task-resume", self.handle_task_resume)

        self.app.router.add_post("/api/tasks/{task_id}/cancel", self.handle_task_cancel)
        self.app.router.add_post("/api/task/{task_id}/cancel", self.handle_task_cancel)
        self.app.router.add_post("/api/task-cancel", self.handle_task_cancel)

        self.app.router.add_post("/api/tasks/{task_id}/retry", self.handle_task_retry)
        self.app.router.add_post("/api/task/{task_id}/retry", self.handle_task_retry)
        self.app.router.add_post("/api/task-retry", self.handle_task_retry)

        # Subsystems & Level 5 APIs
        self.app.router.add_get("/api/memory", self.handle_get_memory)
        self.app.router.add_get("/api/extensions", self.handle_get_extensions)
        self.app.router.add_get("/api/mcp", self.handle_get_mcp)
        self.app.router.add_get("/api/activity", self.handle_get_activity)
        self.app.router.add_get("/api/autostart", self.handle_get_autostart)
        self.app.router.add_post("/api/autostart", self.handle_post_autostart)
        self.app.router.add_post("/api/failsafe/stop", self.handle_failsafe_stop)
        self.app.router.add_post("/api/failsafe/reset", self.handle_failsafe_reset)

        # Voice APIs
        self.app.router.add_post("/api/voice/speak", self.handle_voice_speak)

        # Training API
        self.app.router.add_get("/api/training/status", self.handle_training_status)
        self.app.router.add_post("/api/training/start", self.handle_training_start)
        self.app.router.add_post("/api/training/pause", self.handle_training_pause)
        self.app.router.add_post("/api/training/resume", self.handle_training_resume)
        self.app.router.add_post("/api/training/stop", self.handle_training_stop)

        # Static assets
        web_dir = Path(__file__).resolve().parent / "web"
        if web_dir.is_dir():
            self.app.router.add_static("/static/", path=str(web_dir), name="static")
            self.app.router.add_get("/", self.handle_index)
            self.app.router.add_get("/index.html", self.handle_index)
            self.app.router.add_get("/style.css", self.handle_style_css)
            self.app.router.add_get("/app.js", self.handle_app_js)

    async def handle_index(self, request: web.Request) -> web.Response:
        index_file = Path(__file__).resolve().parent / "web" / "index.html"
        if index_file.exists():
            return web.FileResponse(str(index_file))
        return web.Response(text="NEXA OS Desktop UI Webroot ready.", content_type="text/html")

    async def handle_style_css(self, request: web.Request) -> web.Response:
        css_file = Path(__file__).resolve().parent / "web" / "style.css"
        if css_file.exists():
            return web.FileResponse(str(css_file))
        return web.Response(status=404)

    async def handle_app_js(self, request: web.Request) -> web.Response:
        js_file = Path(__file__).resolve().parent / "web" / "app.js"
        if js_file.exists():
            return web.FileResponse(str(js_file))
        return web.Response(status=404)

    async def ws_handler(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        queue = self.event_bus.register_async_queue()

        # Send initial state snapshot safely
        await ws.send_json(make_json_safe({
            "type": "init",
            "status": self.get_status_payload(),
            "metrics": get_system_metrics(),
            "recent_events": [e.to_dict() for e in self.event_bus.get_recent_events(limit=30)],
        }))

        async def reader():
            try:
                async for msg in ws:
                    if msg.type == WSMsgType.TEXT:
                        try:
                            payload = json.loads(msg.data)
                            action = payload.get("action") or payload.get("type")
                            if action == "command":
                                text = payload.get("text") or payload.get("command") or ""
                                mode = payload.get("mode", "")
                                auto_confirm = bool(payload.get("auto_confirm", False) or (mode == "auto"))
                                asyncio.create_task(self.dispatch_command_async(text, ws, auto_confirm=auto_confirm))
                            elif action == "confirm":
                                aid = payload.get("action_id", "")
                                asyncio.create_task(self.dispatch_confirm_async(aid, ws))
                            elif action == "cancel":
                                aid = payload.get("action_id", "")
                                asyncio.create_task(self.dispatch_cancel_async(aid, ws))
                            elif action in ("pause_task", "task_pause"):
                                tid = payload.get("task_id", "")
                                if tid:
                                    if getattr(self.runtime, "long_running_manager", None):
                                        self.runtime.long_running_manager.pause_task(tid)
                                    if getattr(self.runtime, "task_store", None):
                                        self.runtime.task_store.pause_task(tid)
                                    self.event_bus.emit(UIEventType.TASK_PAUSED, "Task Paused", f"Task '{tid}' paused", task_id=tid)
                            elif action in ("resume_task", "task_resume"):
                                tid = payload.get("task_id", "")
                                if tid:
                                    if getattr(self.runtime, "long_running_manager", None):
                                        self.runtime.long_running_manager.resume_task(tid)
                                    if getattr(self.runtime, "task_store", None):
                                        self.runtime.task_store.resume_task(tid)
                                    self.event_bus.emit(UIEventType.TASK_RESUMED, "Task Resumed", f"Task '{tid}' resumed", task_id=tid)
                            elif action in ("cancel_task", "task_cancel"):
                                tid = payload.get("task_id", "")
                                if tid:
                                    if getattr(self.runtime, "long_running_manager", None):
                                        self.runtime.long_running_manager.cancel_task(tid)
                                    if getattr(self.runtime, "task_store", None):
                                        self.runtime.task_store.cancel_task(tid)
                                    self.event_bus.emit(UIEventType.TASK_CANCELLED, "Task Cancelled", f"Task '{tid}' cancelled", task_id=tid)
                            elif action == "ping":
                                await ws.send_json({"type": "pong", "time": time.time()})
                            elif action == "failsafe_stop":
                                if self.runtime.failsafe:
                                    self.runtime.failsafe.stop()
                                    self.event_bus.emit(UIEventType.SYSTEM_HEALTH_CHANGED, "Failsafe Stopped", "Emergency Stop Triggered")
                            elif action == "failsafe_reset":
                                if self.runtime.failsafe:
                                    self.runtime.failsafe.reset()
                                    self.event_bus.emit(UIEventType.SYSTEM_HEALTH_CHANGED, "Failsafe Reset", "Normal Operations Restored")
                        except Exception as e:
                            await ws.send_json({"type": "error", "message": str(e)})
            except Exception:
                pass

        async def writer():
            try:
                while not ws.closed:
                    event = await queue.get()
                    await ws.send_json(make_json_safe({"type": "event", "event": event.to_dict()}))
            except Exception:
                pass

        reader_task = asyncio.create_task(reader())
        writer_task = asyncio.create_task(writer())

        try:
            done, pending = await asyncio.wait(
                [reader_task, writer_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for p in pending:
                p.cancel()
        finally:
            self.event_bus.unregister_async_queue(queue)

        return ws

    async def dispatch_command_async(
        self,
        text: str,
        ws: web.WebSocketResponse | None = None,
        *,
        auto_confirm: bool = False,
    ) -> dict[str, Any]:
        """Runs command through the standard NEXA cascade without blocking."""
        clean = text.strip()
        if not clean:
            return {"success": False, "message": "Empty command"}

        self.event_bus.emit(
            UIEventType.TASK_CREATED,
            "Command Received",
            clean,
            {"raw_command": clean},
        )

        # Execute in threadpool
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, self._execute_command_pipeline, clean, auto_confirm)
        safe_res = make_json_safe(res)

        if ws and not ws.closed:
            await ws.send_json({
                "type": "command_result",
                "command": clean,
                "result": safe_res,
            })

        return safe_res

    def _execute_command_pipeline(self, text: str, auto_confirm: bool = False) -> dict[str, Any]:
        """Unified command pipeline: delegates to RuntimeControlPlane."""
        return self.control.execute_pipeline(text, auto_confirm=auto_confirm)

    async def dispatch_confirm_async(self, action_id: str, ws: web.WebSocketResponse | None = None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, self._execute_confirm, action_id)
        safe_res = make_json_safe(res)
        if ws and not ws.closed:
            await ws.send_json({"type": "confirm_result", "action_id": action_id, "result": safe_res})
        return safe_res

    def _execute_confirm(self, action_id: str) -> dict[str, Any]:
        return self.control.confirm_plan_or_action(action_id)

    async def dispatch_cancel_async(self, action_id: str, ws: web.WebSocketResponse | None = None) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(None, self._execute_cancel, action_id)
        safe_res = make_json_safe(res)
        if ws and not ws.closed:
            await ws.send_json({"type": "cancel_result", "action_id": action_id, "result": safe_res})
        return safe_res

    def _execute_cancel(self, action_id: str) -> dict[str, Any]:
        return self.control.cancel_plan_or_action(action_id)

    # REST Endpoint Handlers
    async def handle_command(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            try:
                raw_text = await request.text()
                data = {"command": raw_text}
            except Exception:
                data = {}

        text = str(data.get("command") or data.get("text") or "").strip()
        conv_id = data.get("conversation_id", "")
        if not conv_id:
            conv_id = self.conversation_store.create_conversation(title=text[:30].strip() or "Chat")
        
        self.conversation_store.add_message(conv_id, "user", text)

        mode = data.get("mode", "")
        auto_confirm = bool(data.get("auto_confirm", False) or (mode == "auto"))
        res = await self.dispatch_command_async(text, auto_confirm=auto_confirm)

        msg_text = res.get("message", "")
        self.conversation_store.add_message(
            conv_id,
            "assistant",
            msg_text,
            intent=res.get("intent", res.get("status", "")),
            metadata={"status": res.get("status"), "success": res.get("success")},
        )

        safe_res = make_json_safe(res)
        safe_res["conversation_id"] = conv_id
        return web.json_response(safe_res)

    async def handle_get_conversations(self, request: web.Request) -> web.Response:
        convs = self.conversation_store.list_conversations()
        return web.json_response({"conversations": convs})

    async def handle_post_conversations(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            title = data.get("title", "New Chat")
        except Exception:
            title = "New Chat"
        conv_id = self.conversation_store.create_conversation(title=title)
        return web.json_response({"conversation_id": conv_id, "title": title})

    async def handle_get_conversation(self, request: web.Request) -> web.Response:
        conv_id = request.match_info.get("conv_id", "")
        conv = self.conversation_store.get_conversation(conv_id)
        if not conv:
            return web.json_response({"error": "Conversation not found"}, status=404)
        return web.json_response(conv)

    async def handle_delete_conversation(self, request: web.Request) -> web.Response:
        conv_id = request.match_info.get("conv_id", "")
        self.conversation_store.delete_conversation(conv_id)
        return web.json_response({"success": True, "deleted": conv_id})

    async def handle_confirm(self, request: web.Request) -> web.Response:
        data = await request.json()
        action_id = data.get("action_id", "")
        res = await self.dispatch_confirm_async(action_id)
        return web.json_response(make_json_safe(res))

    async def handle_cancel(self, request: web.Request) -> web.Response:
        data = await request.json()
        action_id = data.get("action_id", "")
        res = await self.dispatch_cancel_async(action_id)
        return web.json_response(make_json_safe(res))

    async def handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({
            "status": "healthy",
            "service": "NEXA Level 5 OS",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "0.3.0",
        })

    async def handle_status(self, request: web.Request) -> web.Response:
        return web.json_response(self.get_status_payload())

    async def handle_metrics(self, request: web.Request) -> web.Response:
        return web.json_response(get_system_metrics())

    async def _extract_task_id(self, request: web.Request) -> str:
        tid = request.match_info.get("task_id", "")
        if not tid:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    tid = body.get("task_id", "") or body.get("id", "")
            except Exception:
                pass
        if not tid:
            tid = request.query.get("task_id", "") or request.query.get("id", "")
        return str(tid or "").strip()

    async def handle_post_task(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            data = {}
        goal = data.get("goal") or data.get("command") or data.get("text", "")
        if not goal:
            return web.json_response({"success": False, "error": "Missing goal or command"}, status=400)

        task_id = f"task_{int(time.time()*1000)}"
        if getattr(self.runtime, "task_store", None) is not None:
            from planner.contracts import TaskPlan, TaskRecord, PlanStatus
            plan = TaskPlan(plan_id=task_id, description=goal, steps=[], status=PlanStatus.IN_PROGRESS)
            rec = TaskRecord(
                task_id=task_id,
                goal=goal,
                plan=plan,
                state="in_progress",
                started_at=datetime.now(timezone.utc).isoformat(),
                updated_at=datetime.now(timezone.utc).isoformat(),
            )
            self.runtime.task_store.save_task(rec)

        self.event_bus.emit(
            UIEventType.TASK_STARTED,
            "Task Started",
            f"Goal: {goal}",
            {"task_id": task_id, "goal": goal},
        )

        asyncio.create_task(self.dispatch_command_async(goal))
        return web.json_response({"success": True, "task_id": task_id, "goal": goal, "status": "started"})

    async def handle_get_tasks(self, request: web.Request) -> web.Response:
        tasks_map: dict[str, dict[str, Any]] = {}
        # 1. From persistent task store
        if getattr(self.runtime, "task_store", None) is not None:
            records = self.runtime.task_store.list_tasks(limit=50)
            for r in records:
                tasks_map[r.task_id] = {
                    "task_id": r.task_id,
                    "goal": r.goal,
                    "state": r.state,
                    "current_step": r.current_step,
                    "total_steps": len(r.plan.steps) if r.plan else 0,
                    "started_at": r.started_at,
                    "updated_at": r.updated_at,
                    "recovery_count": r.recovery_count,
                }
        # 2. From in-memory long-running manager
        if getattr(self.runtime, "long_running_manager", None) is not None:
            lr_tasks = self.runtime.long_running_manager.list_tasks()
            for t in lr_tasks:
                state_val = t.state.value if hasattr(t.state, "value") else str(t.state)
                tasks_map[t.task_id] = {
                    "task_id": t.task_id,
                    "goal": t.goal,
                    "state": state_val,
                    "current_step": t.current_step_idx,
                    "total_steps": len(t.plan.steps) if t.plan and hasattr(t.plan, "steps") else 0,
                    "started_at": t.started_at or t.created_at,
                    "updated_at": t.updated_at,
                    "recovery_count": len(t.checkpoints),
                }
        tasks = list(tasks_map.values())
        return web.json_response({"tasks": tasks})

    async def handle_task_pause(self, request: web.Request) -> web.Response:
        tid = await self._extract_task_id(request)
        if not tid:
            return web.json_response({"success": False, "error": "Missing task_id"}, status=400)
        ok = False
        if getattr(self.runtime, "long_running_manager", None) is not None:
            ok = self.runtime.long_running_manager.pause_task(tid) or ok
        if getattr(self.runtime, "task_store", None) is not None:
            ok = self.runtime.task_store.pause_task(tid) or ok
        if ok:
            self.event_bus.emit(UIEventType.TASK_PAUSED, "Task Paused", f"Task '{tid}' paused", task_id=tid)
        return web.json_response({"success": ok, "task_id": tid})

    async def handle_task_resume(self, request: web.Request) -> web.Response:
        tid = await self._extract_task_id(request)
        if not tid:
            return web.json_response({"success": False, "error": "Missing task_id"}, status=400)
        ok = False
        if getattr(self.runtime, "long_running_manager", None) is not None:
            ok = self.runtime.long_running_manager.resume_task(tid) or ok
        if getattr(self.runtime, "task_store", None) is not None:
            ok = self.runtime.task_store.resume_task(tid) or ok
        if ok:
            self.event_bus.emit(UIEventType.TASK_RESUMED, "Task Resumed", f"Task '{tid}' resumed", task_id=tid)
        return web.json_response({"success": ok, "task_id": tid})

    async def handle_task_cancel(self, request: web.Request) -> web.Response:
        tid = await self._extract_task_id(request)
        if not tid:
            return web.json_response({"success": False, "error": "Missing task_id"}, status=400)
        ok = False
        if getattr(self.runtime, "long_running_manager", None) is not None:
            ok = self.runtime.long_running_manager.cancel_task(tid) or ok
        if getattr(self.runtime, "task_store", None) is not None:
            ok = self.runtime.task_store.cancel_task(tid) or ok
        if ok:
            self.event_bus.emit(UIEventType.TASK_CANCELLED, "Task Cancelled", f"Task '{tid}' cancelled", task_id=tid)
        return web.json_response({"success": ok, "task_id": tid})

    async def handle_task_retry(self, request: web.Request) -> web.Response:
        tid = await self._extract_task_id(request)
        if not tid:
            return web.json_response({"success": False, "error": "Missing task_id"}, status=400)
        ok = False
        if getattr(self.runtime, "task_store", None) is not None:
            rec = self.runtime.task_store.get_task(tid)
            if rec:
                rec.state = "pending"
                rec.attempt_count += 1
                rec.recovery_count += 1
                self.runtime.task_store.save_task(rec)
                ok = True
        if getattr(self.runtime, "long_running_manager", None) is not None:
            t = self.runtime.long_running_manager.get_task(tid)
            if t:
                t.state = LongRunningTaskState.PENDING
                t.error = None
                heapq.heappush(self.runtime.long_running_manager._queue, t)
                ok = True
        if ok:
            self.event_bus.emit(UIEventType.TASK_STARTED, "Task Retried", f"Task '{tid}' retried", task_id=tid)
        return web.json_response({"success": ok, "task_id": tid})

    async def handle_get_memory(self, request: web.Request) -> web.Response:
        """Returns safe summary of 10-layer memory system without exposing secrets."""
        mem = {
            "layers": [
                {"id": 1, "name": "Conversation", "status": "Active", "summary": "Active turn buffer loaded"},
                {"id": 2, "name": "Preferences", "status": "Active", "summary": "User defaults & mandates"},
                {"id": 3, "name": "Task State", "status": "Active", "summary": "Persistent task engine"},
                {"id": 4, "name": "Capabilities", "status": "Active", "summary": "Dynamic discovered tools"},
                {"id": 5, "name": "Application Context", "status": "Active", "summary": "Windows desktop handles"},
                {"id": 6, "name": "Browser Context", "status": "Active", "summary": "Playwright session tabs"},
                {"id": 7, "name": "Device Context", "status": "Active", "summary": "Monitors and displays"},
                {"id": 8, "name": "Episodic Memory", "status": "Active", "summary": "Chronological history"},
                {"id": 9, "name": "Semantic Memory", "status": "Active", "summary": "Knowledge triples"},
                {"id": 10, "name": "Procedural Memory", "status": "Active", "summary": "Execution playbooks"},
            ],
            "total_layers": 10,
        }
        return web.json_response(mem)

    async def handle_get_extensions(self, request: web.Request) -> web.Response:
        exts = []
        if getattr(self.runtime, "extension_registry", None) is not None:
            for e in self.runtime.extension_registry.list_extensions():
                exts.append({
                    "name": e.name,
                    "version": e.version,
                    "status": e.status.value,
                    "description": e.description,
                    "category": e.category,
                })
        return web.json_response({"extensions": exts})

    async def handle_get_mcp(self, request: web.Request) -> web.Response:
        tools = []
        if getattr(self.runtime, "mcp_extension", None) is not None:
            tools = self.runtime.mcp_extension.list_tools()
        return web.json_response({"tools": tools, "count": len(tools)})

    async def handle_get_activity(self, request: web.Request) -> web.Response:
        activities = []
        if getattr(self.runtime, "observability", None) is not None:
            activities = self.runtime.observability.get_recent_activity(limit=40)
        return web.json_response({"activities": activities})

    async def handle_get_autostart(self, request: web.Request) -> web.Response:
        return web.json_response({"enabled": is_autostart_enabled()})

    async def handle_post_autostart(self, request: web.Request) -> web.Response:
        data = await request.json()
        enable = data.get("enable", True)
        if enable:
            ok = enable_autostart()
        else:
            ok = disable_autostart()
        return web.json_response({"success": ok, "enabled": is_autostart_enabled()})

    async def handle_failsafe_stop(self, request: web.Request) -> web.Response:
        if self.runtime.failsafe:
            self.runtime.failsafe.stop()
            self.event_bus.emit(UIEventType.SYSTEM_HEALTH_CHANGED, "Emergency Stop", "Failsafe Emergency Stop Triggered")
        return web.json_response({"stopped": True})

    async def handle_failsafe_reset(self, request: web.Request) -> web.Response:
        if self.runtime.failsafe:
            self.runtime.failsafe.reset()
            self.event_bus.emit(UIEventType.SYSTEM_HEALTH_CHANGED, "Failsafe Reset", "Failsafe Reset to Active")
        return web.json_response({"stopped": False})

    async def handle_voice_speak(self, request: web.Request) -> web.Response:
        data = await request.json()
        text = data.get("text", "")
        # Return TTS instruction payload for browser SpeechSynthesis or offline TTS
        return web.json_response({"status": "ok", "text": text})

    def get_training_controller(self):
        if self._training_controller is None:
            from training.training_controller import TrainingController
            self._training_controller = TrainingController(runtime=self.runtime, control_plane=self.control)
        return self._training_controller

    async def handle_training_status(self, request: web.Request) -> web.Response:
        ctrl = self.get_training_controller()
        return web.json_response({
            "is_running": ctrl.is_running,
            "is_paused": ctrl.is_paused,
            "mode": ctrl.mode.value,
            "stats": asdict(ctrl.stats),
        })

    async def handle_training_start(self, request: web.Request) -> web.Response:
        ctrl = self.get_training_controller()
        if ctrl.is_running:
            return web.json_response({"success": False, "message": "Training is already running"})

        try:
            body = await request.json()
        except Exception:
            body = {}
        max_tasks = body.get("max_tasks")

        def _bg_run():
            ctrl.run_training(max_tasks=max_tasks)

        self._training_thread = threading.Thread(target=_bg_run, daemon=True)
        self._training_thread.start()
        return web.json_response({"success": True, "message": "Training started", "max_tasks": max_tasks})

    async def handle_training_pause(self, request: web.Request) -> web.Response:
        ctrl = self.get_training_controller()
        ctrl.pause()
        return web.json_response({"success": True, "message": "Training paused"})

    async def handle_training_resume(self, request: web.Request) -> web.Response:
        ctrl = self.get_training_controller()
        ctrl.resume()
        return web.json_response({"success": True, "message": "Training resumed"})

    async def handle_training_stop(self, request: web.Request) -> web.Response:
        ctrl = self.get_training_controller()
        ctrl.stop()
        return web.json_response({"success": True, "message": "Training stopped"})

    def get_status_payload(self) -> dict[str, Any]:
        """Generates the full status report payload for UI dashboard widgets."""
        skills = [m.name for m in self.runtime.registry.list_metadata()]
        failsafe_stopped = self.runtime.failsafe.is_stopped if self.runtime.failsafe else False
        failsafe_status = "STOPPED" if failsafe_stopped else "ACTIVE"

        mcp_count = len(self.runtime.mcp_extension.list_tools()) if getattr(self.runtime, "mcp_extension", None) else 0
        ext_count = len(self.runtime.extension_registry.list_extensions()) if getattr(self.runtime, "extension_registry", None) else 0
        agents_count = len(self.runtime.multi_agent_extension.list_agents()) if getattr(self.runtime, "multi_agent_extension", None) else 0
        gemini_ready = bool(os.getenv("GEMINI_API_KEY", "").strip())

        return {
            "online": True,
            "status": "ready",
            "failsafe": failsafe_status,
            "security_gate": "Strict (5 Tiers)",
            "skills_count": len(skills),
            "mcp_tools_count": mcp_count,
            "extensions_count": ext_count,
            "active_agents_count": agents_count,
            "gemini_ready": gemini_ready,
            "voice": {
                "mic": "Ready",
                "tts": "EdgeTTS / WebAudio",
                "stt": "Ready",
            },
        }

    async def start(self) -> None:
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()

    async def stop(self) -> None:
        if self.runner:
            await self.runner.cleanup()


def run_server_blocking(control: RuntimeControlPlane | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = NexaUIServer(control=control, host=host, port=port)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(server.start())
        loop.run_forever()
    finally:
        loop.run_until_complete(server.stop())
