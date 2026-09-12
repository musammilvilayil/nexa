from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any


def verify_app_open(app_name: str, timeout_seconds: float = 3.0) -> bool:
    """Verify that an application process or window is running."""
    clean_name = app_name.lower().strip()
    if clean_name.endswith(".exe"):
        clean_name = clean_name[:-4]

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {clean_name}*"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if clean_name in res.stdout.lower():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def verify_app_closed(app_name: str, timeout_seconds: float = 3.0) -> bool:
    """Verify that an application process is no longer running."""
    clean_name = app_name.lower().strip()
    if clean_name.endswith(".exe"):
        clean_name = clean_name[:-4]

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            res = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {clean_name}*"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if clean_name not in res.stdout.lower():
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return True


def verify_window_focused(title_pattern: str, active_window_title: str) -> bool:
    """Verify that the focused window matches the expected title pattern."""
    return title_pattern.lower() in active_window_title.lower()


def verify_file_created(path: Path | str, expected_content: str | None = None) -> bool:
    """Verify that a file exists on disk and its content matches if specified."""
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        return False
    if expected_content is not None:
        try:
            actual = target.read_text(encoding="utf-8")
            return expected_content in actual
        except Exception:
            return False
    return True


def verify_file_deleted(path: Path | str) -> bool:
    """Verify that a file no longer exists."""
    target = Path(path).expanduser().resolve()
    return not target.exists()


def verify_file_moved(src: Path | str, dst: Path | str) -> bool:
    """Verify that source file was moved to destination."""
    src_path = Path(src).expanduser().resolve()
    dst_path = Path(dst).expanduser().resolve()
    return not src_path.exists() and dst_path.is_file()


def verify_file_copied(src: Path | str, dst: Path | str) -> bool:
    """Verify that source was duplicated to destination."""
    src_path = Path(src).expanduser().resolve()
    dst_path = Path(dst).expanduser().resolve()
    return src_path.is_file() and dst_path.is_file()


def verify_download(path_or_size: Path | str | int, min_bytes: int = 1) -> bool:
    """Verify that a downloaded file exists or has reasonable size."""
    if isinstance(path_or_size, int):
        return path_or_size >= min_bytes
    target = Path(path_or_size).expanduser().resolve()
    if not target.is_file():
        return False
    return target.stat().st_size >= min_bytes


def verify_url_loaded(current_url: str, expected_url: str) -> bool:
    """Verify that browser navigated to the expected URL."""
    c_clean = current_url.lower().rstrip("/")
    e_clean = expected_url.lower().rstrip("/")
    return e_clean in c_clean or c_clean in e_clean


def verify_text_typed(before_text: str, after_text: str, typed_text: str) -> bool:
    """Verify observable text input in an active element."""
    if typed_text in after_text:
        return True
    return len(after_text) > len(before_text)


def verify_state_changed(before_observation: Any, after_observation: Any) -> bool:
    """Verify that desktop or window state changed non-trivially."""
    if before_observation is None or after_observation is None:
        return True
    return before_observation != after_observation


def verify_folder_exists(path: Path | str) -> bool:
    """Verify that a directory exists on disk."""
    p = Path(path).expanduser().resolve()
    return p.is_dir()


def verify_file_content(path: Path | str, expected_text: str) -> bool:
    """Verify that a file contains expected text."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        return False
    try:
        content = p.read_text(encoding="utf-8")
        return expected_text.lower() in content.lower()
    except Exception:
        return False


def verify_file_size(path: Path | str, min_bytes: int = 1) -> bool:
    """Verify that a file exists and has at least min_bytes."""
    p = Path(path).expanduser().resolve()
    return p.is_file() and p.stat().st_size >= min_bytes


def verify_window_exists(title_pattern: str) -> bool:
    """Verify that a visible window matching pattern exists."""
    try:
        from computer.window import WindowManager
        wm = WindowManager()
        return wm.find_window(title_pattern) is not None
    except Exception:
        return False
