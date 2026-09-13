from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import urllib.parse
from typing import Any, Callable, Mapping

from core.auth_handler import AuthenticationHandler
from .contracts import AuthHandoffEvent, OAuthServiceConfig, OAuthState, OAuthToken
from .token_store import TokenStore


class OAuthManager:
    """Coordinates OAuth 2.0 PKCE / Authorization Code flows and human handoffs."""

    DEFAULT_SERVICES = {
        "github": OAuthServiceConfig(
            name="github",
            client_id="nexa-github-client-id",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes=("repo", "read:user"),
            redirect_uri="http://127.0.0.1:8989/callback",
        ),
        "google": OAuthServiceConfig(
            name="google",
            client_id="nexa-google-client-id",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=("openid", "email", "profile"),
            redirect_uri="http://127.0.0.1:8989/callback",
        ),
        "microsoft": OAuthServiceConfig(
            name="microsoft",
            client_id="nexa-ms-client-id",
            authorize_url="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            token_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
            scopes=("openid", "profile", "offline_access"),
            redirect_uri="http://127.0.0.1:8989/callback",
        ),
    }

    def __init__(
        self,
        token_store: TokenStore | None = None,
        auth_handler: AuthenticationHandler | None = None,
    ) -> None:
        self.token_store = token_store or TokenStore()
        self.auth_handler = auth_handler or AuthenticationHandler()
        self._services: dict[str, OAuthServiceConfig] = dict(self.DEFAULT_SERVICES)
        self._sessions: dict[str, dict[str, Any]] = {}
        self._states: dict[str, OAuthState] = {}
        self._lock = threading.Lock()

    def register_service(self, config: OAuthServiceConfig) -> None:
        with self._lock:
            self._services[config.name] = config

    def get_service_config(self, service_name: str) -> OAuthServiceConfig | None:
        with self._lock:
            return self._services.get(service_name)

    def current_state(self, service_name: str) -> OAuthState:
        with self._lock:
            return self._states.get(service_name, OAuthState.IDLE)

    def start_auth_flow(
        self,
        service_name: str,
        *,
        redirect_uri: str | None = None,
    ) -> AuthHandoffEvent:
        with self._lock:
            config = self._services.get(service_name)
            if not config:
                raise KeyError(f"OAuth service '{service_name}' is not configured")

            session_id = secrets.token_hex(16)
            state_csrf = secrets.token_urlsafe(24)

            # Generate PKCE code verifier and challenge
            verifier = secrets.token_urlsafe(32)
            digest = hashlib.sha256(verifier.encode("ascii")).digest()
            challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

            target_redirect = redirect_uri or config.redirect_uri

            query = {
                "client_id": config.client_id,
                "response_type": "code",
                "redirect_uri": target_redirect,
                "scope": " ".join(config.scopes),
                "state": state_csrf,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
            auth_url = f"{config.authorize_url}?{urllib.parse.urlencode(query)}"

            self._sessions[session_id] = {
                "service": service_name,
                "state_csrf": state_csrf,
                "verifier": verifier,
                "redirect_uri": target_redirect,
                "created_at": time.time(),
            }
            self._states[service_name] = OAuthState.HUMAN_HANDOFF

            return AuthHandoffEvent(
                service=service_name,
                state=OAuthState.HUMAN_HANDOFF,
                authorize_url=auth_url,
                session_id=session_id,
                message=f"Human handoff required for {service_name}. Please sign in.",
                prompt_for_user=f"Open {auth_url} to authorize NEXA with {service_name}.",
            )

    def handle_callback(
        self,
        session_id: str,
        code: str,
        state: str,
        *,
        token_override: str | None = None,
    ) -> OAuthToken:
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                raise ValueError("Invalid or expired OAuth session")

            if session["state_csrf"] != state:
                raise ValueError("OAuth state mismatch (CSRF protection)")

            service_name = session["service"]
            self._states[service_name] = OAuthState.AUTHENTICATING

            # Create token (simulated or real exchange)
            token_val = token_override or f"nexa_tok_{secrets.token_hex(20)}"
            refresh_val = f"nexa_ref_{secrets.token_hex(20)}"

            token = OAuthToken(
                service=service_name,
                access_token=token_val,
                refresh_token=refresh_val,
                expires_in=7200,
                scopes=self._services[service_name].scopes,
            )

            self.token_store.store_token(token)
            self._states[service_name] = OAuthState.AUTHENTICATED
            del self._sessions[session_id]
            return token

    def check_auth_barrier(self, page_text_or_title: str, url: str = "") -> AuthHandoffEvent | None:
        """Inspect page text or URL, transitioning to human handoff if login/MFA detected."""
        challenge = self.auth_handler.detect_auth_challenge(page_text_or_title, url)
        if not challenge:
            return None

        # Guess service from URL
        detected_service = "generic_web"
        for sname in self._services:
            if sname in url.lower():
                detected_service = sname
                break

        with self._lock:
            self._states[detected_service] = OAuthState.HUMAN_HANDOFF
            session_id = secrets.token_hex(8)
            return AuthHandoffEvent(
                service=detected_service,
                state=OAuthState.HUMAN_HANDOFF,
                authorize_url=url or challenge.target_url_or_app,
                session_id=session_id,
                message=challenge.message,
                prompt_for_user=f"Security challenge detected ({challenge.challenge_type}): {challenge.message}. Please complete it manually to continue.",
            )

    def get_token(self, service_name: str) -> OAuthToken | None:
        return self.token_store.get_token(service_name)

    def revoke(self, service_name: str) -> bool:
        with self._lock:
            self._states[service_name] = OAuthState.IDLE
            return self.token_store.revoke_token(service_name)
