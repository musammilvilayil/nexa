from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from core.failures import AuthenticationRequired


@dataclass(frozen=True)
class AuthChallenge:
    """Represents a detected authentication challenge (login, MFA, CAPTCHA, OTP)."""
    challenge_type: str  # login, mfa, captcha, otp, biometric
    target_url_or_app: str
    message: str
    fields_detected: tuple[str, ...] = ()
    user_action_required: bool = True


class AuthenticationHandler:
    """Manages safe, privacy-preserving authentication and interactive security challenges.
    
    Invariants:
    1. NEVER log, store, or serialize plaintext passwords in memory, logs, or state databases.
    2. NEVER attempt to guess credentials or bypass CAPTCHA / MFA / OTP / biometrics.
    3. When an authentication barrier is detected, PAUSE execution and raise AuthenticationRequired
       to prompt the user to complete authentication interactively.
    """

    MFA_CAPTCHA_PATTERNS = (
        re.compile(r"\b(?:captcha|recaptcha|hcaptcha|turnstile)\b", re.IGNORECASE),
        re.compile(r"\b(?:two[ -]?factor|2fa|mfa|verification\s+code|authenticator\s+app)\b", re.IGNORECASE),
        re.compile(r"\b(?:one[ -]?time\s+password|otp|security\s+key|passkey)\b", re.IGNORECASE),
    )

    LOGIN_PATTERNS = (
        re.compile(r"\b(?:sign\s*in|log\s*in|login|enter\s*password)\b", re.IGNORECASE),
    )

    def detect_auth_challenge(self, page_text_or_title: str, url: str = "") -> AuthChallenge | None:
        """Inspect visible text or URL to detect authentication barriers."""
        text = page_text_or_title

        # Check CAPTCHA / MFA / OTP first
        for pat in self.MFA_CAPTCHA_PATTERNS:
            if pat.search(text) or pat.search(url):
                return AuthChallenge(
                    challenge_type="mfa_or_captcha",
                    target_url_or_app=url or page_text_or_title,
                    message="Security checkpoint detected (MFA/CAPTCHA/OTP). Please complete authentication in your browser or application.",
                    user_action_required=True,
                )

        # Check standard login prompt
        for pat in self.LOGIN_PATTERNS:
            if pat.search(text) or "/login" in url.lower() or "/signin" in url.lower():
                return AuthChallenge(
                    challenge_type="login",
                    target_url_or_app=url or page_text_or_title,
                    message="Login required. NEXA will pause for user authentication handoff.",
                    user_action_required=True,
                )

        return None

    def pause_for_user_auth(self, challenge: AuthChallenge) -> None:
        """Pause task execution and raise AuthenticationRequired for interactive user handoff."""
        raise AuthenticationRequired(
            f"Authentication Required: {challenge.message} (Target: {challenge.target_url_or_app})",
            details={"challenge_type": challenge.challenge_type, "target": challenge.target_url_or_app},
        )
