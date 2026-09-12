from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO

_LOCK_FILE_HANDLE: TextIO | None = None


def get_default_lock_path() -> Path:
    base = Path(__file__).resolve().parents[2] / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base / "nexa_ui.lock"


def acquire_instance_lock(lock_path: Path | str | None = None) -> bool:
    """Acquires a single instance lock. Returns True if this is the only instance, False otherwise."""
    global _LOCK_FILE_HANDLE

    if _LOCK_FILE_HANDLE is not None:
        return True  # Already acquired by this process

    path = Path(lock_path) if lock_path else get_default_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "win32":
            import msvcrt

            handle = open(path, "a+b")
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                handle.truncate(0)
                handle.write(f"{os.getpid()}\n".encode("utf-8"))
                handle.flush()
                _LOCK_FILE_HANDLE = handle
                return True
            except (OSError, IOError):
                handle.close()
                return False
        else:
            import fcntl

            handle = open(path, "a+b")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                handle.seek(0)
                handle.truncate(0)
                handle.write(f"{os.getpid()}\n".encode("utf-8"))
                handle.flush()
                _LOCK_FILE_HANDLE = handle
                return True
            except (OSError, IOError):
                handle.close()
                return False
    except Exception:
        return False


def release_instance_lock() -> None:
    """Releases the instance lock and cleans up."""
    global _LOCK_FILE_HANDLE
    if _LOCK_FILE_HANDLE is not None:
        try:
            if sys.platform == "win32":
                import msvcrt

                _LOCK_FILE_HANDLE.seek(0)
                msvcrt.locking(_LOCK_FILE_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(_LOCK_FILE_HANDLE.fileno(), fcntl.LOCK_UN)
            _LOCK_FILE_HANDLE.close()
        except Exception:
            pass
        finally:
            _LOCK_FILE_HANDLE = None


def is_another_instance_running(lock_path: Path | str | None = None) -> bool:
    """Checks if another instance currently holds the lock without acquiring it permanently."""
    acquired = acquire_instance_lock(lock_path)
    if acquired:
        release_instance_lock()
        return False
    return True
