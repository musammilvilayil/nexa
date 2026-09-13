from __future__ import annotations

import json
import logging
import os
import random
import secrets
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from ui.event_bus import get_event_bus, UIEventType

logger = logging.getLogger("nexa.remote.lan")

MOBILE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>NEXA Mobile Remote</title>
<style>
  :root {
    --bg: #0d1117;
    --card: #161b22;
    --border: #30363d;
    --primary: #58a6ff;
    --success: #2ea043;
    --danger: #da3633;
    --text: #c9d1d9;
    --text-bright: #ffffff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  body { background: var(--bg); color: var(--text); padding: 16px; min-height: 100vh; display: flex; flex-direction: column; }
  header { display: flex; justify-content: space-between; align-items: center; padding-bottom: 12px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  h1 { font-size: 1.25rem; color: var(--text-bright); display: flex; align-items: center; gap: 8px; }
  .badge { background: #238636; color: #fff; font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; font-weight: bold; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; margin-bottom: 14px; }
  .form-group { display: flex; flex-direction: column; gap: 8px; }
  input[type="text"], input[type="password"] {
    background: #090d13; border: 1px solid var(--border); color: #fff; padding: 12px; border-radius: 8px; font-size: 1rem; width: 100%;
  }
  button {
    background: var(--primary); color: #000; border: none; padding: 12px 16px; border-radius: 8px; font-size: 1rem; font-weight: bold; cursor: pointer; display: flex; justify-content: center; align-items: center; gap: 6px;
  }
  button:active { opacity: 0.8; transform: scale(0.98); }
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 14px; }
  .btn-danger { background: var(--danger); color: #fff; }
  .btn-secondary { background: #21262d; color: var(--text); border: 1px solid var(--border); }
  .log-box {
    background: #090d13; border: 1px solid var(--border); border-radius: 8px; padding: 10px; font-family: monospace; font-size: 0.82rem; height: 160px; overflow-y: auto; white-space: pre-wrap; color: #8b949e;
  }
  #pair-section { display: block; }
  #remote-section { display: none; }
</style>
</head>
<body>
<header>
  <h1><span>⚡</span> NEXA Mobile Remote</h1>
  <span class="badge" id="conn-status">LAN</span>
</header>

<div id="pair-section" class="card">
  <div class="form-group">
    <label>Enter 6-Digit Laptop Pairing PIN:</label>
    <input type="password" id="pin-input" placeholder="e.g. 123456" maxlength="6" inputmode="numeric">
    <button onclick="pairDevice()">Connect to Laptop</button>
  </div>
</div>

<div id="remote-section">
  <div class="card">
    <div class="form-group">
      <input type="text" id="cmd-input" placeholder="Say or type command...">
      <button onclick="sendCommand()">Send Command</button>
    </div>
  </div>

  <div class="grid-2">
    <button class="btn-secondary" onclick="quickCmd('Take a screenshot')">📸 Screenshot</button>
    <button class="btn-secondary" onclick="quickCmd('Analyze my storage')">💾 Storage</button>
    <button class="btn-secondary" onclick="quickCmd('Show system status')">📊 Status</button>
    <button class="btn-secondary" onclick="quickCmd('Run capability verification')">🧪 Self Test</button>
  </div>

  <div style="margin-bottom: 14px;">
    <button class="btn-danger" style="width: 100%;" onclick="emergencyStop()">🛑 EMERGENCY STOP</button>
  </div>

  <div class="card">
    <div style="font-size: 0.85rem; font-weight: bold; margin-bottom: 6px;">Live Execution Output</div>
    <div class="log-box" id="output-box">Ready.</div>
  </div>
</div>

<script>
let authToken = localStorage.getItem('nexa_remote_token') || '';

if (authToken) {
  validateToken();
}

async function pairDevice() {
  const pin = document.getElementById('pin-input').value.trim();
  if (!pin) return;
  try {
    const res = await fetch('/api/pair', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin })
    });
    const data = await res.json();
    if (data.success && data.token) {
      authToken = data.token;
      localStorage.setItem('nexa_remote_token', authToken);
      showRemote();
      log("Paired securely with laptop.");
    } else {
      alert(data.message || "Invalid PIN");
    }
  } catch (e) {
    alert("Connection failed: " + e.message);
  }
}

async function validateToken() {
  try {
    const res = await fetch('/api/status', {
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    if (res.ok) {
      showRemote();
    } else {
      showPair();
    }
  } catch(e) {
    showPair();
  }
}

function showRemote() {
  document.getElementById('pair-section').style.display = 'none';
  document.getElementById('remote-section').style.display = 'block';
  document.getElementById('conn-status').textContent = 'CONNECTED';
  document.getElementById('conn-status').style.background = '#2ea043';
}

function showPair() {
  document.getElementById('pair-section').style.display = 'block';
  document.getElementById('remote-section').style.display = 'none';
  document.getElementById('conn-status').textContent = 'UNPAIRED';
  document.getElementById('conn-status').style.background = '#da3633';
}

async function sendCommand() {
  const input = document.getElementById('cmd-input');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  await executeRemote(text);
}

async function quickCmd(text) {
  await executeRemote(text);
}

async function emergencyStop() {
  try {
    log("SENDING EMERGENCY STOP TO LAPTOP...");
    const res = await fetch('/api/emergency_stop', {
      method: 'POST',
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    const data = await res.json();
    log("EMERGENCY STOP EXECUTED: " + data.message);
  } catch(e) {
    log("Error triggering emergency stop: " + e.message);
  }
}

async function executeRemote(command) {
  log("> " + command);
  try {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken
      },
      body: JSON.stringify({ command })
    });
    const data = await res.json();
    log(data.message || JSON.stringify(data));
  } catch (e) {
    log("Error: " + e.message);
  }
}

function log(msg) {
  const box = document.getElementById('output-box');
  box.textContent += "\\n" + msg;
  box.scrollTop = box.scrollHeight;
}
</script>
</body>
</html>
"""


class LANRemoteHandler(BaseHTTPRequestHandler):
    server: LANRemoteServer

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(MOBILE_HTML.encode("utf-8"))
            return

        if parsed.path == "/api/status":
            if not self._check_auth():
                return
            status_data = {
                "ok": True,
                "server_time": datetime.now(timezone.utc).isoformat(),
                "hostname": socket.gethostname(),
                "failsafe_stopped": bool(getattr(self.server.failsafe, "is_stopped", False)),
            }
            self._json_response(200, status_data)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b"{}"

        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            payload = {}

        if parsed.path == "/api/pair":
            pin = str(payload.get("pin", "")).strip()
            if pin == self.server.pairing_pin:
                token = secrets.token_hex(16)
                self.server.active_tokens.add(token)
                self._json_response(200, {"success": True, "token": token})
            else:
                self._json_response(401, {"success": False, "message": "Invalid pairing PIN"})
            return

        if not self._check_auth():
            return

        if parsed.path == "/api/emergency_stop":
            if getattr(self.server.failsafe, "stop", None):
                self.server.failsafe.stop()
            self._json_response(200, {"success": True, "message": "Failsafe emergency stop triggered"})
            return

        if parsed.path == "/api/command":
            cmd = str(payload.get("command", "")).strip()
            if not cmd:
                self._json_response(400, {"success": False, "message": "Empty command"})
                return

            if self.server.control_plane:
                try:
                    res = self.server.control_plane.execute_pipeline(cmd, auto_confirm=True)
                    self._json_response(200, res)
                except Exception as exc:
                    self._json_response(500, {"success": False, "message": str(exc)})
            else:
                self._json_response(503, {"success": False, "message": "No control plane bound"})
            return

        self.send_response(404)
        self.end_headers()

    def _check_auth(self) -> bool:
        auth_header = self.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "").strip()
        if token in self.server.active_tokens:
            return True
        self._json_response(401, {"success": False, "message": "Unauthorized"})
        return False

    def _json_response(self, code: int, data: dict[str, Any]) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format, *args):
        pass  # Suppress noisy standard output logs


class LANRemoteServer(HTTPServer):
    """Secure LAN mobile remote control server operating on port 8766."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8766,
        control_plane: Any | None = None,
        failsafe: Any | None = None,
        pairing_pin: str | None = None,
    ) -> None:
        self.control_plane = control_plane
        self.failsafe = failsafe
        self.pairing_pin = pairing_pin or str(random.randint(100000, 999999))
        self.active_tokens: set[str] = set()
        self._thread: threading.Thread | None = None
        super().__init__((host, port), LANRemoteHandler)
        logger.info("LANRemoteServer initialized on port %d with PIN %s", port, self.pairing_pin)

    def start_in_thread(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True, name="LANRemoteServerThread")
        self._thread.start()

    def stop_server(self) -> None:
        self.shutdown()
        self.server_close()

