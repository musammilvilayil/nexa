from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Add src to sys.path
SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from control_plane import RuntimeControlPlane
from runtime import build_runtime
from ui.autostart import is_autostart_enabled
from ui.event_bus import UIEventType, get_event_bus
from ui.instance_lock import acquire_instance_lock, release_instance_lock
from ui.server import NexaUIServer


def find_browser_app_executable() -> str | None:
    """Finds Microsoft Edge or Google Chrome for native App Mode rendering."""
    candidates = [
        # Microsoft Edge
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        # Google Chrome
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def launch_native_app_window(url: str) -> subprocess.Popen | None:
    """Launches an isolated native desktop window without browser URL bar."""
    exe = find_browser_app_executable()
    if exe:
        profile_dir = Path(__file__).resolve().parents[2] / "data" / "ui_profile"
        profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            exe,
            f"--app={url}",
            f"--user-data-dir={profile_dir}",
            "--window-size=1280,840",
            "--window-position=100,60",
            "--disable-features=Translate",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        try:
            return subprocess.Popen(args)
        except Exception:
            pass

    # Fallback to default browser
    webbrowser.open(url)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXA Level 5 Desktop UI Launcher")
    parser.add_argument("--host", default="127.0.0.1", help="Server host")
    parser.add_argument("--port", type=int, default=8765, help="Server port")
    parser.add_argument("--background", action="store_true", help="Run background server only")
    parser.add_argument("--no-browser", action="store_true", help="Do not launch browser window")
    args = parser.parse_args()

    # 1. Enforce single instance lock
    if not acquire_instance_lock():
        print("[NEXA UI] Another instance is already running. Opening existing window...")
        webbrowser.open(f"http://{args.host}:{args.port}/")
        return 0

    print("=" * 65)
    print("NEXA LEVEL 5 AUTONOMOUS PERSONAL AI OS — DESKTOP UI")
    print("=" * 65)
    print(f"Server binding: http://{args.host}:{args.port}/")
    print(f"Auto-start status: {'Enabled' if is_autostart_enabled() else 'Disabled'}")

    try:
        # 2. Build runtime & control plane
        print("[1/3] Initializing NEXA Level 5 Runtime...")
        runtime = build_runtime()
        control = RuntimeControlPlane(runtime)
        event_bus = get_event_bus()

        # 3. Start async server in dedicated thread
        print("[2/3] Starting UI WebSocket & REST API Server...")
        server = NexaUIServer(control=control, event_bus=event_bus, host=args.host, port=args.port)

        loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.start())
            loop.run_forever()

        t = threading.Thread(target=run_loop, daemon=True)
        t.start()

        # Wait for server to bind with active socket polling
        import socket
        start_t = time.time()
        bound = False
        while time.time() - start_t < 10.0:
            try:
                with socket.create_connection((args.host, args.port), timeout=0.2):
                    bound = True
                    break
            except (OSError, ConnectionRefusedError):
                time.sleep(0.05)
        if not bound:
            print(f"[NEXA UI] Warning: Server failed to bind within 10s on {args.host}:{args.port}")

        url = f"http://{args.host}:{args.port}/"
        app_proc = None

        if not args.background and not args.no_browser:
            print(f"[3/3] Launching Native Desktop Window: {url}")
            app_proc = launch_native_app_window(url)
            print("NEXA Desktop UI is ready. Press Ctrl+C to stop.")
        else:
            print("Running in background mode. Press Ctrl+C to stop.")

        event_bus.emit(
            UIEventType.SYSTEM_HEALTH_CHANGED,
            "NEXA Online",
            f"Desktop UI connected to kernel at {url}",
        )

        # Main thread wait: Keep server running until interrupted (browser app-mode processes
        # often exit immediately after handing off the tab to the running browser instance)
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[NEXA UI] Interrupted by user. Shutting down cleanly...")

        # Graceful cleanup
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)

    finally:
        release_instance_lock()
        print("[NEXA UI] Single instance lock released. Shutdown complete.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
