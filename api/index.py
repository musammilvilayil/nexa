from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import NexaKernel, SkillRegistry
from skills.dummy_skill import DummySkill


registry = SkillRegistry()
registry.register(DummySkill())
kernel = NexaKernel(registry=registry)


def _payload(response):
    data = {
        "status": response.status,
        "message": response.message,
    }
    if response.result is not None:
        data["result"] = {
            "success": response.result.success,
            "message": response.result.message,
            "data": response.result.data,
            "error": response.result.error,
        }
    if response.pending_action is not None:
        action = response.pending_action
        data["pending_action"] = {
            "action_id": action.action_id,
            "skill": action.skill_name,
            "operation": action.operation,
            "params": dict(action.params),
            "risk": action.risk.value,
            "created_at_utc": action.created_at_utc.isoformat(),
            "expires_at_utc": action.expires_at_utc.isoformat(),
        }
    return data


class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send_json(
            200,
            {
                "name": "NEXA Kernel demo",
                "status": "ready",
                "demo_skill": "dummy",
                "commands": ["system ping", "remember hello", "publish origin"],
                "note": "Hosted demo exposes only the safe DummySkill. Local Git, files, trading, Ollama, and secrets are not exposed.",
            },
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            request = json.loads(raw.decode("utf-8"))

            if request.get("confirm"):
                response = kernel.confirm(str(request["confirm"]))
            elif request.get("cancel"):
                response = kernel.cancel(str(request["cancel"]))
            else:
                command = str(request.get("command", "")).strip()
                if not command:
                    self._send_json(400, {"status": "error", "message": "command required"})
                    return
                response = kernel.process(command)

            self._send_json(200, _payload(response))
        except (ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"status": "error", "message": str(exc)})
        except Exception:
            self._send_json(500, {"status": "error", "message": "internal server error"})
