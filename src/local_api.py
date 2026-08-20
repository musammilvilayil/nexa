from __future__ import annotations

import argparse
import hmac
import json
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from threading import Event
from typing import Any

from control_plane import RuntimeControlPlane, health_payload, kernel_response_payload
from runtime import build_runtime


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local NEXA control/status API.")
    parser.add_argument("--host", default=os.getenv("NEXA_LOCAL_API_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("NEXA_LOCAL_API_PORT", "8765")),
    )
    return parser.parse_args()


def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _safe_json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")


def build_handler(control: RuntimeControlPlane, *, token: str | None = None):
    expected = token.strip() if token else ""

    class LocalNexaHandler(BaseHTTPRequestHandler):
        server_version = "NEXALocalAPI/0.1"

        def log_message(self, format: str, *args: object) -> None:
            # Keep the local API quiet by default; application logging can wrap it.
            return

        def _authorized(self) -> bool:
            if not expected:
                return True
            header = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not header.startswith(prefix):
                return False
            supplied = header[len(prefix) :]
            return hmac.compare_digest(supplied, expected)

        def _send(self, status_code: int, payload: Any) -> None:
            body = _safe_json(payload)
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _require_auth(self) -> bool:
            if self._authorized():
                return True
            self._send(401, {"status": "error", "message": "unauthorized"})
            return False

        def _read_json(self) -> dict[str, Any]:
            raw_length = self.headers.get("Content-Length", "0")
            length = int(raw_length)
            if length < 0 or length > 1_000_000:
                raise ValueError("invalid request size")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("JSON object required")
            return payload

        def do_GET(self) -> None:
            if not self._require_auth():
                return
            if self.path == "/health":
                snapshot = control.health()
                self._send(200 if snapshot.ok else 503, health_payload(snapshot))
                return
            if self.path == "/status":
                self._send(200, control.status())
                return
            self._send(404, {"status": "error", "message": "not found"})

        def do_POST(self) -> None:
            if not self._require_auth():
                return
            try:
                request = self._read_json()
                if self.path == "/command":
                    response = control.process(str(request.get("command", "")))
                    self._send(200, kernel_response_payload(response))
                    return
                if self.path == "/confirm":
                    response = control.confirm(str(request.get("action_id", "")))
                    self._send(200, kernel_response_payload(response))
                    return
                if self.path == "/cancel":
                    response = control.cancel(str(request.get("action_id", "")))
                    self._send(200, kernel_response_payload(response))
                    return
                self._send(404, {"status": "error", "message": "not found"})
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send(400, {"status": "error", "message": str(exc)})
            except RuntimeError as exc:
                self._send(409, {"status": "error", "message": str(exc)})
            except Exception:
                self._send(500, {"status": "error", "message": "internal server error"})

    return LocalNexaHandler


def main() -> int:
    args = _parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")

    token = os.getenv("NEXA_LOCAL_API_TOKEN", "").strip() or None
    if not _is_loopback_host(args.host) and token is None:
        raise SystemExit(
            "refusing non-loopback NEXA local API without NEXA_LOCAL_API_TOKEN"
        )

    runtime = build_runtime()
    control = RuntimeControlPlane(runtime)
    server = ThreadingHTTPServer((args.host, args.port), build_handler(control, token=token))
    server.daemon_threads = True
    server.timeout = 0.5
    stop = Event()

    def request_stop(*_args: object) -> None:
        # Do not call BaseServer.shutdown() from the signal handler because the
        # handler runs on the same thread as the server loop. A stop flag avoids
        # that documented deadlock while keeping shutdown bounded by server.timeout.
        control.shutdown()
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    try:
        while not stop.is_set():
            server.handle_request()
    finally:
        control.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
