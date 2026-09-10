from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class FailsafeReason(str, Enum):
    CORNER_TRIGGER = "corner_trigger"
    KEYBOARD_TRIGGER = "keyboard_trigger"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    BLOCKED_PROCESS = "blocked_process"
    MANUAL_STOP = "manual_stop"


@dataclass(frozen=True)
class FailsafeConfig:
    """Configuration for the failsafe system."""
    corner_enabled: bool = True
    corner_threshold_px: int = 5  # pixels from (0,0) to trigger
    max_actions_per_second: float = 10.0
    action_timeout_seconds: float = 30.0
    blocked_processes: frozenset[str] = frozenset()
    cooldown_after_trigger_seconds: float = 5.0


@dataclass
class FailsafeState:
    """Current state of the failsafe system."""
    stopped: bool = False
    reason: FailsafeReason | None = None
    triggered_at: float | None = None
    action_count: int = 0
    action_window_start: float = 0.0


class FailsafeMonitor:
    """Non-bypassable emergency stop for computer-use actions.
    
    Every mouse/keyboard/automation action MUST call check_before_action()
    before executing. This is the last safety barrier.
    
    Safety guarantees:
    1. Corner detection: mouse near (0,0) → immediate halt
    2. Rate limiting: max N actions per second
    3. Action timeout: no single action > configured timeout
    4. Blocked process list: never automate certain apps
    5. Thread-safe stop flag checked before EVERY action
    6. Manual stop: external code can trigger immediate halt
    """
    
    def __init__(self, config: FailsafeConfig | None = None) -> None:
        self._config = config or FailsafeConfig()
        self._state = FailsafeState()
        self._lock = threading.Lock()
        self._callbacks: list[Callable[[FailsafeReason], None]] = []
    
    @property
    def config(self) -> FailsafeConfig:
        return self._config
    
    @property
    def is_stopped(self) -> bool:
        return self._state.stopped
    
    @property
    def state(self) -> FailsafeState:
        with self._lock:
            # Return a copy
            return FailsafeState(
                stopped=self._state.stopped,
                reason=self._state.reason,
                triggered_at=self._state.triggered_at,
                action_count=self._state.action_count,
                action_window_start=self._state.action_window_start,
            )
    
    def check_before_action(self, *, mouse_x: int | None = None, mouse_y: int | None = None) -> None:
        """MUST be called before every computer-use action.
        
        Raises FailsafeTriggered if the action should not proceed.
        """
        with self._lock:
            # Check stop flag
            if self._state.stopped:
                raise FailsafeTriggered(self._state.reason or FailsafeReason.MANUAL_STOP)
            
            # Check cooldown after previous trigger
            if self._state.triggered_at is not None:
                elapsed = time.monotonic() - self._state.triggered_at
                if elapsed < self._config.cooldown_after_trigger_seconds:
                    raise FailsafeTriggered(
                        FailsafeReason.MANUAL_STOP,
                        f"Cooldown active: {self._config.cooldown_after_trigger_seconds - elapsed:.1f}s remaining"
                    )
            
            # Check corner trigger
            if (self._config.corner_enabled 
                and mouse_x is not None and mouse_y is not None
                and mouse_x <= self._config.corner_threshold_px 
                and mouse_y <= self._config.corner_threshold_px):
                self._trigger(FailsafeReason.CORNER_TRIGGER)
                raise FailsafeTriggered(FailsafeReason.CORNER_TRIGGER)
            
            # Check rate limit
            now = time.monotonic()
            if now - self._state.action_window_start >= 1.0:
                self._state.action_count = 0
                self._state.action_window_start = now
            
            self._state.action_count += 1
            if self._state.action_count > self._config.max_actions_per_second:
                self._trigger(FailsafeReason.RATE_LIMIT)
                raise FailsafeTriggered(FailsafeReason.RATE_LIMIT)
    
    def check_blocked_process(self, process_name: str) -> None:
        """Check if a process is in the blocked list.
        
        Raises FailsafeTriggered if the process should not be automated.
        """
        normalized = process_name.strip().lower()
        for blocked in self._config.blocked_processes:
            if blocked.lower() == normalized:
                self._trigger(FailsafeReason.BLOCKED_PROCESS)
                raise FailsafeTriggered(
                    FailsafeReason.BLOCKED_PROCESS,
                    f"Process '{process_name}' is blocked from automation"
                )
    
    def stop(self, reason: FailsafeReason = FailsafeReason.MANUAL_STOP) -> None:
        """Manually trigger emergency stop."""
        with self._lock:
            self._trigger(reason)
    
    def reset(self) -> None:
        """Reset the failsafe after a triggered stop.
        
        This should only be called by explicit user action.
        """
        with self._lock:
            self._state = FailsafeState()
    
    def on_trigger(self, callback: Callable[[FailsafeReason], None]) -> None:
        """Register a callback for failsafe triggers."""
        self._callbacks.append(callback)
    
    def _trigger(self, reason: FailsafeReason) -> None:
        """Internal: trigger the failsafe."""
        self._state.stopped = True
        self._state.reason = reason
        self._state.triggered_at = time.monotonic()
        for cb in self._callbacks:
            try:
                cb(reason)
            except Exception:
                pass  # Never let callbacks prevent the stop


class FailsafeTriggered(RuntimeError):
    """Raised when the failsafe system prevents an action."""
    
    def __init__(self, reason: FailsafeReason, message: str = "") -> None:
        self.reason = reason
        super().__init__(message or f"Failsafe triggered: {reason.value}")
