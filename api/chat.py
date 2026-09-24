from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from platform.agent import NexaAgent

agent = NexaAgent()


class handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self._json(200, {"ok": True})

    def do_GET(self):
        self._json(200, {"name": "NEXA Agent Platform v2", "status": "ready", "tools": agent.registry.catalog()})

    def do_POST(self):
        try:
            size = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(size) or b"{}")
            message = str(body.get("message", "")).strip()
            if not message:
                return self._json(400, {"error": "message required"})
            reply = agent.chat(message, body.get("session_id"))
            self._json(200, {"session_id": reply.session_id, "message": reply.message, "tool_calls": reply.tool_calls, "artifacts": reply.artifacts})
        except Exception as exc:
            self._json(500, {"error": str(exc)})
