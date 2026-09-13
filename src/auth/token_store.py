from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .contracts import OAuthToken


def _derive_keystream(key: bytes, length: int) -> bytes:
    """Generate deterministic keystream of given length using SHA256 counter mode."""
    blocks = []
    counter = 0
    generated = 0
    while generated < length:
        h = hashlib.sha256(key + counter.to_bytes(8, "big")).digest()
        blocks.append(h)
        generated += len(h)
        counter += 1
    return b"".join(blocks)[:length]


def _encrypt_payload(data: bytes, key: bytes) -> bytes:
    keystream = _derive_keystream(key, len(data))
    return bytes(b ^ k for b, k in zip(data, keystream))


def _decrypt_payload(ciphertext: bytes, key: bytes) -> bytes:
    return _encrypt_payload(ciphertext, key)  # symmetric XOR stream


class TokenStore:
    """Isolated, encrypted token store preventing token leakage in memory/logs."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        master_key: str | bytes | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self._lock = threading.Lock()

        # Derive 32-byte master key
        if master_key is None:
            # Derived from machine-specific or fallback seed
            env_key = os.getenv("NEXA_MASTER_AUTH_KEY", "nexa-autonomous-os-auth-vault-v1")
            raw_key = env_key.encode("utf-8")
        elif isinstance(master_key, str):
            raw_key = master_key.encode("utf-8")
        else:
            raw_key = master_key

        self._master_secret = hashlib.sha256(raw_key).digest()
        self._mem_conn: sqlite3.Connection | None = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            return self._mem_conn
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tokens (
                service TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                ciphertext TEXT NOT NULL,
                salt TEXT NOT NULL,
                hmac_tag TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()
        if self._db_path != ":memory:":
            conn.close()

    def _derive_keys(self, salt: bytes) -> tuple[bytes, bytes]:
        # PBKDF2 to derive (enc_key, mac_key)
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            self._master_secret,
            salt,
            iterations=10000,
            dklen=64,
        )
        return derived[:32], derived[32:]

    def store_token(self, token: OAuthToken, user_id: str = "default") -> None:
        with self._lock:
            salt = secrets.token_bytes(16)
            enc_key, mac_key = self._derive_keys(salt)

            payload_data = json.dumps(token.to_dict(include_secrets=True)).encode("utf-8")
            ciphertext = _encrypt_payload(payload_data, enc_key)

            tag = hmac.new(mac_key, ciphertext, hashlib.sha256).digest()

            ct_b64 = base64.b64encode(ciphertext).decode("ascii")
            salt_b64 = base64.b64encode(salt).decode("ascii")
            tag_b64 = base64.b64encode(tag).decode("ascii")

            conn = self._get_conn()
            try:
                conn.execute(
                    """
                    INSERT INTO tokens (service, user_id, ciphertext, salt, hmac_tag, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(service) DO UPDATE SET
                        user_id=excluded.user_id,
                        ciphertext=excluded.ciphertext,
                        salt=excluded.salt,
                        hmac_tag=excluded.hmac_tag,
                        updated_at=excluded.updated_at
                    """,
                    (token.service, user_id, ct_b64, salt_b64, tag_b64, time.time()),
                )
                conn.commit()
            finally:
                if self._db_path != ":memory:":
                    conn.close()

    def get_token(self, service: str, user_id: str = "default") -> OAuthToken | None:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "SELECT ciphertext, salt, hmac_tag FROM tokens WHERE service = ? AND user_id = ?",
                    (service, user_id),
                )
                row = cursor.fetchone()
            finally:
                if self._db_path != ":memory:":
                    conn.close()

            if not row:
                return None

            ct_b64, salt_b64, tag_b64 = row
            ciphertext = base64.b64decode(ct_b64)
            salt = base64.b64decode(salt_b64)
            expected_tag = base64.b64decode(tag_b64)

            enc_key, mac_key = self._derive_keys(salt)
            computed_tag = hmac.new(mac_key, ciphertext, hashlib.sha256).digest()

            if not hmac.compare_digest(expected_tag, computed_tag):
                raise ValueError(f"Integrity check failed for stored token of service '{service}'")

            decrypted_bytes = _decrypt_payload(ciphertext, enc_key)
            data = json.loads(decrypted_bytes.decode("utf-8"))

            return OAuthToken(
                service=data["service"],
                access_token=data["access_token"],
                refresh_token=data.get("refresh_token"),
                token_type=data.get("token_type", "Bearer"),
                expires_in=data.get("expires_in", 3600),
                scopes=tuple(data.get("scopes", ())),
                created_at=data.get("created_at"),
            )

    def revoke_token(self, service: str, user_id: str = "default") -> bool:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM tokens WHERE service = ? AND user_id = ?",
                    (service, user_id),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                if self._db_path != ":memory:":
                    conn.close()

    def list_services(self, user_id: str = "default") -> list[str]:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "SELECT service FROM tokens WHERE user_id = ?",
                    (user_id,),
                )
                return [row[0] for row in cursor.fetchall()]
            finally:
                if self._db_path != ":memory:":
                    conn.close()

    def __repr__(self) -> str:
        return f"<TokenStore path={self._db_path!r} services={self.list_services()}>"

    def __str__(self) -> str:
        return f"TokenStore({len(self.list_services())} services configured)"
