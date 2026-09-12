from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ConversationStore:
    """Persistent SQLite store for ChatGPT-style conversations in NEXA."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            db_path = Path(__file__).resolve().parents[2] / "data" / "conversations.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    intent TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            conn.commit()

    def create_conversation(self, title: str = "New Chat") -> str:
        conv_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conv_id, title, now, now),
            )
            conn.commit()
        return conv_id

    def list_conversations(self) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations WHERE id = ?",
                (conv_id,),
            ).fetchone()
            if not row:
                return None
            conv = dict(row)
            msg_rows = conn.execute(
                "SELECT id, role, content, created_at, intent, metadata FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conv_id,),
            ).fetchall()
            messages = []
            for m in msg_rows:
                d = dict(m)
                try:
                    d["metadata"] = json.loads(d["metadata"])
                except Exception:
                    d["metadata"] = {}
                messages.append(d)
            conv["messages"] = messages
            return conv

    def add_message(
        self,
        conv_id: str,
        role: str,
        content: str,
        *,
        intent: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        # If conversation doesn't exist, create it
        with self._get_conn() as conn:
            row = conn.execute("SELECT id, title FROM conversations WHERE id = ?", (conv_id,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if not row:
                title = content[:30].strip() or "Chat"
                conn.execute(
                    "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (conv_id, title, now, now),
                )
            else:
                # If first message and title is "New Chat", update title
                if row["title"] == "New Chat" and role == "user":
                    new_title = content[:30].strip() or "Chat"
                    conn.execute("UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?", (new_title, now, conv_id))
                else:
                    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conv_id))

            msg_id = str(uuid.uuid4())[:8]
            meta_json = json.dumps(metadata or {})
            conn.execute(
                "INSERT INTO messages (id, conversation_id, role, content, created_at, intent, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (msg_id, conv_id, role, content, now, intent, meta_json),
            )
            conn.commit()
            return msg_id

    def delete_conversation(self, conv_id: str) -> bool:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            conn.commit()
            return True
