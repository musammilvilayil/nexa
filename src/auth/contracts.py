from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class OAuthState(str, Enum):
    IDLE = "idle"
    AUTH_REQUIRED = "auth_required"
    HUMAN_HANDOFF = "human_handoff"
    AUTHENTICATING = "authenticating"
    AUTHENTICATED = "authenticated"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class OAuthServiceConfig:
    name: str
    client_id: str
    authorize_url: str
    token_url: str
    client_secret: str = ""
    scopes: tuple[str, ...] = ()
    redirect_uri: str = "http://127.0.0.1:8989/callback"
    use_pkce: bool = True


class OAuthToken:
    """Safe token container that prevents accidental logging or serialization."""

    def __init__(
        self,
        service: str,
        access_token: str,
        refresh_token: str | None = None,
        token_type: str = "Bearer",
        expires_in: int = 3600,
        scopes: tuple[str, ...] = (),
        created_at: float | None = None,
    ) -> None:
        self._service = service
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_type = token_type
        self._expires_in = expires_in
        self._scopes = tuple(scopes)
        self._created_at = created_at if created_at is not None else time.time()

    @property
    def service(self) -> str:
        return self._service

    @property
    def token_type(self) -> str:
        return self._token_type

    @property
    def scopes(self) -> tuple[str, ...]:
        return self._scopes

    @property
    def created_at(self) -> float:
        return self._created_at

    @property
    def expires_in(self) -> int:
        return self._expires_in

    @property
    def is_expired(self) -> bool:
        return time.time() > (self._created_at + self._expires_in)

    def get_secret(self) -> str:
        """Explicit getter for secret token. Must be called intentionally."""
        return self._access_token

    def get_refresh_secret(self) -> str | None:
        return self._refresh_token

    def to_dict(self, include_secrets: bool = False) -> dict[str, Any]:
        d = {
            "service": self._service,
            "token_type": self._token_type,
            "expires_in": self._expires_in,
            "scopes": list(self._scopes),
            "created_at": self._created_at,
            "is_expired": self.is_expired,
        }
        if include_secrets:
            d["access_token"] = self._access_token
            if self._refresh_token:
                d["refresh_token"] = self._refresh_token
        else:
            d["access_token"] = "[REDACTED]"
            if self._refresh_token:
                d["refresh_token"] = "[REDACTED]"
        return d

    def __repr__(self) -> str:
        return (
            f"OAuthToken(service={self._service!r}, token_type={self._token_type!r}, "
            f"access_token='[REDACTED]', is_expired={self.is_expired})"
        )

    def __str__(self) -> str:
        return f"OAuthToken[{self._service}](valid={not self.is_expired})"


@dataclass(frozen=True)
class AuthHandoffEvent:
    service: str
    state: OAuthState
    authorize_url: str
    session_id: str
    message: str = ""
    prompt_for_user: str = "Please complete sign-in in your browser."
    created_at: float = field(default_factory=time.time)
