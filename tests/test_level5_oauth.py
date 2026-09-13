from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from auth.contracts import OAuthState, OAuthToken
from auth.oauth_manager import OAuthManager
from auth.token_store import TokenStore


class TestLevel5OAuth(unittest.TestCase):
    def setUp(self):
        self.store = TokenStore(":memory:", master_key="test-secure-master-key-xyz-12345")
        self.oauth = OAuthManager(token_store=self.store)

    def test_oauth_token_redaction(self):
        token = OAuthToken(
            service="github",
            access_token="gho_secret_password_token_1234567890",
            refresh_token="ghr_secret_refresh_12345",
        )
        rep = repr(token)
        s = str(token)
        d = token.to_dict()

        self.assertNotIn("gho_secret", rep)
        self.assertNotIn("ghr_secret", rep)
        self.assertIn("[REDACTED]", rep)

        self.assertNotIn("gho_secret", s)
        self.assertEqual(d["access_token"], "[REDACTED]")
        self.assertEqual(d["refresh_token"], "[REDACTED]")

        # Explicit retrieval
        self.assertEqual(token.get_secret(), "gho_secret_password_token_1234567890")

    def test_token_store_encryption_roundtrip(self):
        tok = OAuthToken(
            service="google",
            access_token="ya29.very_secret_google_access_token",
            refresh_token="1//google_refresh",
            scopes=("openid", "email"),
        )
        self.store.store_token(tok)

        loaded = self.store.get_token("google")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.service, "google")
        self.assertEqual(loaded.get_secret(), "ya29.very_secret_google_access_token")
        self.assertEqual(loaded.get_refresh_secret(), "1//google_refresh")
        self.assertEqual(loaded.scopes, ("openid", "email"))

    def test_token_store_tamper_detection(self):
        tok = OAuthToken(service="test_svc", access_token="secret")
        self.store.store_token(tok)

        # Tamper directly in SQLite
        conn = self.store._get_conn()
        conn.execute("UPDATE tokens SET ciphertext = 'corrupted' WHERE service = 'test_svc'")
        conn.commit()

        with self.assertRaises(ValueError):
            self.store.get_token("test_svc")

    def test_oauth_manager_pkce_flow_and_callback(self):
        # 1. Start flow
        event = self.oauth.start_auth_flow("github")
        self.assertEqual(event.service, "github")
        self.assertEqual(event.state, OAuthState.HUMAN_HANDOFF)
        self.assertIn("code_challenge=", event.authorize_url)
        self.assertIn("code_challenge_method=S256", event.authorize_url)
        self.assertEqual(self.oauth.current_state("github"), OAuthState.HUMAN_HANDOFF)

        # 2. Extract state parameter
        import urllib.parse
        parsed = urllib.parse.urlparse(event.authorize_url)
        params = urllib.parse.parse_qs(parsed.query)
        csrf_state = params["state"][0]

        # 3. Simulate callback
        token = self.oauth.handle_callback(event.session_id, "simulated_code_123", csrf_state)
        self.assertEqual(token.service, "github")
        self.assertEqual(self.oauth.current_state("github"), OAuthState.AUTHENTICATED)

        # 4. Token persisted
        loaded = self.oauth.get_token("github")
        self.assertIsNotNone(loaded)

    def test_oauth_manager_csrf_mismatch(self):
        event = self.oauth.start_auth_flow("google")
        with self.assertRaises(ValueError):
            self.oauth.handle_callback(event.session_id, "code", "wrong_csrf_state")

    def test_oauth_barrier_detection_and_handoff(self):
        event = self.oauth.check_auth_barrier(
            "Please solve this Turnstile CAPTCHA to continue",
            url="https://github.com/login",
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.state, OAuthState.HUMAN_HANDOFF)
        self.assertIn("CAPTCHA", event.prompt_for_user)


if __name__ == "__main__":
    unittest.main()
