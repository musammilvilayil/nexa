from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from core.contracts import RiskTier, PolicyOutcome
from core.security import SecurityGate
from core.failsafe import FailsafeMonitor, FailsafeTriggered
from core.failures import (
    AgentError,
    SecurityBlocked,
    BrowserNavigationFailure,
    VerificationFailed,
    Timeout as ActionTimeout,
)

logger = logging.getLogger("nexa.browsercontrol")

_URL_ALLOWED_PREFIXES = ("http://", "https://", "about:blank")
_URL_BLOCKED_SCHEMES = ("file:", "javascript:", "data:", "chrome:", "chrome-extension:")

_SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|password|passwd|auth[_-]?token|bearer\s+[a-zA-Z0-9_\-\.]{15,})", re.IGNORECASE),
]


class BrowserControlError(AgentError):
    """Base error for browserControl integration failures."""
    pass


class StaleObservationError(BrowserControlError):
    """Raised when an action is attempted with an expired, invalidated, or mismatched observationId."""
    def __init__(self, observation_id: str, message: str = ""):
        super().__init__(
            message or f"Observation '{observation_id}' is stale. Page state has mutated since capture; re-observe required.",
            details={"observation_id": observation_id, "recovery_action": "re_observe"},
        )


class CoordinateOutOfBoundsError(BrowserControlError):
    """Raised when coordinates exceed the active viewport boundaries."""
    def __init__(self, x: int, y: int, message: str = ""):
        super().__init__(
            message or f"Coordinates ({x}, {y}) are outside viewport bounds.",
            details={"x": x, "y": y, "recovery_action": "re_evaluate_target"},
        )


class TargetClosedError(BrowserControlError):
    """Raised when controlled tab/target is closed or detached."""
    def __init__(self, target_id: str | None = None, message: str = ""):
        super().__init__(
            message or f"Controlled browser target '{target_id}' was closed or detached.",
            details={"target_id": target_id, "recovery_action": "auto_recover_tab"},
        )


class DialogBlockingError(BrowserControlError):
    """Raised when a JavaScript alert, confirm, or prompt modal blocks the viewport."""
    def __init__(self, dialog_info: Any = None, message: str = ""):
        super().__init__(
            message or "A modal JavaScript dialog is blocking browser execution.",
            details={"dialog": dialog_info, "recovery_action": "handle_dialog"},
        )


@dataclass(frozen=True)
class ObservationResult:
    """Result of capturing a browserControl visual observation."""
    observation_id: str
    visual_epoch: int
    viewport_width: int
    viewport_height: int
    image_width: int
    image_height: int
    screenshot_bytes: bytes
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class BrowserActionResult:
    """Result of an action performed through browserControl."""
    success: bool
    action: str
    data: Any = None
    error: str | None = None
    error_code: str | None = None
    duration_ms: float = 0.0


class BrowserControlAdapter:
    """NEXA Foundation Adapter for browserControl.
    
    Adheres strictly to:
    1. Observation Contract: Every mutating action requires a valid, fresh observationId.
       Actions invalidate the observation token, requiring observe -> act -> observe -> act.
    2. Security Enforcement: Pass-through verification via NEXA SecurityGate and FailsafeMonitor.
    3. Error Intelligence: Automatic mapping of browserControl errors to structured NEXA diagnostics.
    """

    def __init__(
        self,
        *,
        security_gate: SecurityGate | None = None,
        failsafe: FailsafeMonitor | None = None,
        node_executable: str = "node",
        bridge_script: str | None = None,
        strict_observation: bool = True,
        auto_reobserve_on_stale: bool = False,
    ) -> None:
        self._security_gate = security_gate or SecurityGate()
        self._failsafe = failsafe or FailsafeMonitor()
        self._node_executable = node_executable
        self._strict_observation = strict_observation
        self._auto_reobserve_on_stale = auto_reobserve_on_stale

        base_dir = Path(__file__).resolve().parent
        self._bridge_script = bridge_script or str(base_dir / "browsercontrol_bridge.mjs")

        self._process: subprocess.Popen | None = None
        self._req_counter = 0
        self._current_observation_id: str | None = None
        self._current_epoch: int = 0
        self._connected = False
        self._active_target_id: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.poll() is None

    @property
    def current_observation_id(self) -> str | None:
        return self._current_observation_id

    # --------------------------------------------------------------------------
    # Subprocess Lifecycle & IPC
    # --------------------------------------------------------------------------

    def start(self, connect_options: dict[str, Any] | None = None) -> dict[str, Any]:
        """Launch the node bridge process and connect to Chrome."""
        if self.is_connected:
            return {"status": "already_connected", "targetId": self._active_target_id}

        opts = connect_options or {"mode": "auto"}

        if not Path(self._bridge_script).exists():
            raise FileNotFoundError(f"browserControl bridge script not found at {self._bridge_script}")

        self._process = subprocess.Popen(
            [self._node_executable, self._bridge_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
            encoding="utf-8",
        )

        res = self._send_request("connect", opts)
        if not res.get("success"):
            self.stop()
            raise BrowserControlError(f"Failed to connect browserControl bridge: {res.get('error')}")

        data = res.get("data", {})
        self._connected = True
        self._active_target_id = data.get("targetId")
        self._current_epoch = data.get("visualEpoch", 0)
        return data

    def stop(self) -> None:
        """Gracefully disconnect and terminate bridge process."""
        if self._process:
            try:
                self._send_request("exit", {}, timeout=2.0)
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=3.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        self._connected = False
        self._current_observation_id = None
        self._active_target_id = None

    def _send_request(self, action: str, params: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        """Send a JSON request line to the bridge and wait for the response line."""
        if not self._process or self._process.poll() is not None:
            raise BrowserControlError("browserControl bridge process is not running")

        self._req_counter += 1
        req_id = self._req_counter
        payload = json.dumps({"id": req_id, "action": action, "params": params})

        try:
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            self._process.stdin.write(payload + "\n")
            self._process.stdin.flush()

            raw_line = self._process.stdout.readline()
            if not raw_line:
                raise BrowserControlError("Received empty response from browserControl bridge (process terminated)")

            response = json.loads(raw_line.strip())
            return response
        except Exception as exc:
            logger.error("IPC error with browserControl bridge: %s", exc)
            raise

    # --------------------------------------------------------------------------
    # Security Checks
    # --------------------------------------------------------------------------

    def _assert_security_allowed(self, action: str, risk: RiskTier, params: dict[str, Any] | None = None) -> None:
        decision = self._security_gate.evaluate(skill_name="browsercontrol", operation=action, params=params, risk=risk)
        if decision.outcome == PolicyOutcome.DENY:
            raise SecurityBlocked(f"Action '{action}' blocked by SecurityGate policy: {decision.reason}")

    def _assert_failsafe(self, mouse_x: int | None = None, mouse_y: int | None = None) -> None:
        if self._failsafe:
            self._failsafe.check_before_action(mouse_x=mouse_x, mouse_y=mouse_y)

    def _validate_url(self, url: str) -> str:
        trimmed = url.strip()
        lower = trimmed.lower()
        for scheme in _URL_BLOCKED_SCHEMES:
            if lower.startswith(scheme):
                raise SecurityBlocked(f"Access to prohibited URL scheme '{scheme}' is denied")

        if not any(lower.startswith(p) for p in _URL_ALLOWED_PREFIXES):
            # Normalize plain domain/search query
            if "." in trimmed and not " " in trimmed:
                return "https://" + trimmed
            return trimmed
        return trimmed

    def _validate_type_text(self, text: str) -> None:
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                raise SecurityBlocked("Refusing to type text containing suspected credentials/tokens without explicit approval")

    # --------------------------------------------------------------------------
    # Observation Contract (observe -> act -> observe -> act)
    # --------------------------------------------------------------------------

    def observe(self, show_cursor: bool = True) -> ObservationResult:
        """Capture a visual observation.
        
        Returns an ObservationResult with observation_id and screenshot_bytes.
        Sets this observation_id as the current valid token.
        """
        self._assert_security_allowed("observe", RiskTier.READ)

        res = self._send_request("observe", {"showCursor": show_cursor})
        if not res.get("success"):
            self._translate_and_raise(res, "observe")

        data = res["data"]
        obs_id = data["observationId"]
        epoch = data["visualEpoch"]
        raw_b64 = data.get("image", "")
        img_bytes = base64.b64decode(raw_b64) if raw_b64 else b""

        self._current_observation_id = obs_id
        self._current_epoch = epoch

        return ObservationResult(
            observation_id=obs_id,
            visual_epoch=epoch,
            viewport_width=data.get("viewportWidth", 0),
            viewport_height=data.get("viewportHeight", 0),
            image_width=data.get("imageWidth", 0),
            image_height=data.get("imageHeight", 0),
            screenshot_bytes=img_bytes,
        )

    def _verify_observation_token(self, observation_id: str) -> None:
        """Enforces that an action is bound to a fresh, valid observation."""
        if not self._strict_observation:
            return

        if not observation_id:
            raise StaleObservationError(observation_id, "Action missing observationId. Fresh observation required.")

        if self._current_observation_id is None:
            raise StaleObservationError(observation_id, "No active observation token available. Page was already mutated; re-observe required.")

        if observation_id != self._current_observation_id:
            raise StaleObservationError(
                observation_id,
                f"Provided observationId '{observation_id}' does not match active token '{self._current_observation_id}'. Stale action rejected."
            )

    def _invalidate_observation(self) -> None:
        """Invalidate the current observation token following a mutating action."""
        self._current_observation_id = None

    # --------------------------------------------------------------------------
    # Actions
    # --------------------------------------------------------------------------

    def click(self, observation_id: str, x: int, y: int, button: str = "left") -> BrowserActionResult:
        """Execute a click at coordinates mapped from the provided observation."""
        self._assert_security_allowed("click", RiskTier.MUTATE, {"x": x, "y": y, "button": button})
        self._assert_failsafe(mouse_x=x, mouse_y=y)
        self._verify_observation_token(observation_id)

        res = self._send_request("click", {
            "observationId": observation_id,
            "x": x,
            "y": y,
            "button": button,
        })

        if not res.get("success"):
            self._translate_and_raise(res, "click", observation_id=observation_id, x=x, y=y)

        self._invalidate_observation()
        return BrowserActionResult(
            success=True,
            action="click",
            data=res.get("data"),
            duration_ms=res.get("durationMs", 0.0),
        )

    def double_click(self, observation_id: str, x: int, y: int) -> BrowserActionResult:
        """Execute a double click at coordinates."""
        self._assert_security_allowed("double_click", RiskTier.MUTATE, {"x": x, "y": y})
        self._assert_failsafe(mouse_x=x, mouse_y=y)
        self._verify_observation_token(observation_id)

        res = self._send_request("double_click", {
            "observationId": observation_id,
            "x": x,
            "y": y,
        })

        if not res.get("success"):
            self._translate_and_raise(res, "double_click", observation_id=observation_id, x=x, y=y)

        self._invalidate_observation()
        return BrowserActionResult(
            success=True,
            action="double_click",
            data=res.get("data"),
            duration_ms=res.get("durationMs", 0.0),
        )

    def type_text(self, observation_id: str, text: str) -> BrowserActionResult:
        """Type text into currently focused element."""
        self._assert_security_allowed("type", RiskTier.MUTATE, {"text": text})
        self._assert_failsafe()
        self._validate_type_text(text)
        self._verify_observation_token(observation_id)

        res = self._send_request("type", {
            "observationId": observation_id,
            "text": text,
        })

        if not res.get("success"):
            self._translate_and_raise(res, "type", observation_id=observation_id)

        self._invalidate_observation()
        return BrowserActionResult(
            success=True,
            action="type",
            data=res.get("data"),
            duration_ms=res.get("durationMs", 0.0),
        )

    def scroll(
        self,
        observation_id: str,
        x: int = 100,
        y: int = 100,
        delta_x: int = 0,
        delta_y: int = 150,
    ) -> BrowserActionResult:
        """Scroll the viewport or nested scroll container."""
        self._assert_security_allowed("scroll", RiskTier.MUTATE, {"delta_x": delta_x, "delta_y": delta_y})
        self._assert_failsafe(mouse_x=x, mouse_y=y)
        self._verify_observation_token(observation_id)

        res = self._send_request("scroll", {
            "observationId": observation_id,
            "x": x,
            "y": y,
            "deltaX": delta_x,
            "deltaY": delta_y,
        })

        if not res.get("success"):
            self._translate_and_raise(res, "scroll", observation_id=observation_id, x=x, y=y)

        self._invalidate_observation()
        return BrowserActionResult(
            success=True,
            action="scroll",
            data=res.get("data"),
            duration_ms=res.get("durationMs", 0.0),
        )

    def navigate(self, url: str) -> BrowserActionResult:
        """Navigate active tab to a sanitized URL."""
        validated_url = self._validate_url(url)
        self._assert_security_allowed("navigate", RiskTier.REMOTE, {"url": validated_url})

        res = self._send_request("navigate", {"url": validated_url})
        if not res.get("success"):
            self._translate_and_raise(res, "navigate")

        self._invalidate_observation()
        return BrowserActionResult(
            success=True,
            action="navigate",
            data=res.get("data"),
            duration_ms=res.get("durationMs", 0.0),
        )

    def back(self) -> BrowserActionResult:
        """Navigate backwards in page history."""
        self._assert_security_allowed("back", RiskTier.MUTATE)
        res = self._send_request("back", {})
        if not res.get("success"):
            self._translate_and_raise(res, "back")
        self._invalidate_observation()
        return BrowserActionResult(success=True, action="back")

    def forward(self) -> BrowserActionResult:
        """Navigate forward in page history."""
        self._assert_security_allowed("forward", RiskTier.MUTATE)
        res = self._send_request("forward", {})
        if not res.get("success"):
            self._translate_and_raise(res, "forward")
        self._invalidate_observation()
        return BrowserActionResult(success=True, action="forward")

    def reload(self) -> BrowserActionResult:
        """Reload active page."""
        self._assert_security_allowed("reload", RiskTier.MUTATE)
        res = self._send_request("reload", {})
        if not res.get("success"):
            self._translate_and_raise(res, "reload")
        self._invalidate_observation()
        return BrowserActionResult(success=True, action="reload")

    def tabs(self) -> list[dict[str, Any]]:
        """List open browser tabs."""
        self._assert_security_allowed("tabs", RiskTier.READ)
        res = self._send_request("tabs", {})
        if not res.get("success"):
            self._translate_and_raise(res, "tabs")
        return res.get("data", [])

    def new_tab(self, url: str = "about:blank") -> dict[str, Any]:
        """Open a new browser tab with safe URL."""
        safe_url = self._validate_url(url)
        self._assert_security_allowed("new_tab", RiskTier.REMOTE, {"url": safe_url})
        res = self._send_request("new_tab", {"url": safe_url})
        if not res.get("success"):
            self._translate_and_raise(res, "new_tab")
        self._invalidate_observation()
        data = res.get("data", {})
        if data.get("targetId"):
            self._active_target_id = data["targetId"]
        return data

    def switch_tab(self, target_id: str) -> BrowserActionResult:
        """Switch active focus and attachment to target tab."""
        self._assert_security_allowed("switch_tab", RiskTier.MUTATE, {"target_id": target_id})
        res = self._send_request("switch_tab", {"targetId": target_id})
        if not res.get("success"):
            self._translate_and_raise(res, "switch_tab")
        self._active_target_id = target_id
        self._invalidate_observation()
        return BrowserActionResult(success=True, action="switch_tab", data={"targetId": target_id})

    def close_tab(self, target_id: str) -> BrowserActionResult:
        """Close specified tab."""
        self._assert_security_allowed("close_tab", RiskTier.MUTATE, {"target_id": target_id})
        res = self._send_request("close_tab", {"targetId": target_id})
        if not res.get("success"):
            self._translate_and_raise(res, "close_tab")
        self._invalidate_observation()
        return BrowserActionResult(success=True, action="close_tab", data=res.get("data"))

    def evaluate(self, expression: str) -> Any:
        """Evaluate a JavaScript expression on the active page via CDP."""
        self._assert_security_allowed("evaluate", RiskTier.READ)
        res = self._send_request("evaluate", {"expression": expression})
        if not res.get("success"):
            self._translate_and_raise(res, "evaluate")
        return res.get("data")

    def doctor(self) -> dict[str, Any]:
        """Retrieve diagnostic doctor metrics from Chrome."""
        res = self._send_request("doctor", {})
        if not res.get("success"):
            self._translate_and_raise(res, "doctor")
        return res.get("data", {})

    # --------------------------------------------------------------------------
    # Error Translation & Diagnostics
    # --------------------------------------------------------------------------

    def _translate_and_raise(
        self,
        res: dict[str, Any],
        action: str,
        observation_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> None:
        err_code = res.get("errorCode") or "UNKNOWN_ERROR"
        err_msg = res.get("error") or f"Action {action} failed with {err_code}"

        if err_code == "STALE_OBSERVATION":
            raise StaleObservationError(observation_id or "", err_msg)
        elif err_code == "OUT_OF_BOUNDS":
            raise CoordinateOutOfBoundsError(x or 0, y or 0, err_msg)
        elif err_code in ("TARGET_CLOSED", "DETACHED"):
            raise TargetClosedError(self._active_target_id, err_msg)
        elif err_code == "DIALOG_BLOCKING":
            raise DialogBlockingError(res.get("data"), err_msg)
        elif "net::ERR_" in err_msg or err_code == "NAVIGATION_FAILED":
            raise BrowserNavigationFailure(err_msg, details={"action": action, "errorCode": err_code})
        else:
            raise BrowserControlError(err_msg, details={"action": action, "errorCode": err_code})
