from __future__ import annotations

from typing import Any


class AgentError(Exception):
    """Base exception for all agent execution failures."""
    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ElementNotFound(AgentError):
    """Raised when a UI element cannot be located on the screen or DOM."""
    pass


class WindowNotFound(AgentError):
    """Raised when an application or window cannot be found."""
    pass


class BrowserNavigationFailure(AgentError):
    """Raised when browser page loading or navigation fails."""
    pass


class Timeout(AgentError):
    """Raised when an action or plan step exceeds its allowed duration."""
    pass


class PermissionDenied(AgentError):
    """Raised when an action is denied by user or access controls."""
    pass


class SecurityBlocked(AgentError):
    """Raised when an action is blocked by the SecurityGate."""
    pass


class CapabilityMissing(AgentError):
    """Raised when no skill or capability exists to fulfill the request."""
    pass


class ProviderUnavailable(AgentError):
    """Raised when a required provider (vision, STT, browser) is not configured."""
    pass


class AuthenticationRequired(AgentError):
    """Raised when an action hits a login, MFA, CAPTCHA, or biometric prompt."""
    pass


class VerificationFailed(AgentError):
    """Raised when post-action state verification does not match expectations."""
    pass


class UnexpectedState(AgentError):
    """Raised when the application or system is in an unhandled state."""
    pass
