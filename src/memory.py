import sqlite3
import re
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nexa.db"

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        conn.commit()

def save_message(role, content, conversation_id="default"):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                conversation_id,
                role,
                content,
                datetime.now(timezone.utc).isoformat()
            )
        )
        conn.commit()

def load_recent_messages(limit=20, conversation_id="default"):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (conversation_id, limit)
        ).fetchall()

    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]

def search_memory(query, limit=5):
    words = [
        w.lower()
        for w in re.findall(r"[A-Za-z0-9]+", query)
        if len(w) >= 3
    ]

    if not words:
        return []

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM messages
            ORDER BY id DESC
            LIMIT 200
            """
        ).fetchall()

    scored = []

    for role, content in rows:
        text = content.lower()
        score = sum(1 for word in words if word in text)

        if score > 0:
            scored.append((score, role, content))

    scored.sort(key=lambda x: x[0], reverse=True)

    return [
        {"role": role, "content": content}
        for _, role, content in scored[:limit]
    ]

def set_fact(key, value):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO facts (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key)
            DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

def get_fact(key):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM facts WHERE key = ?",
            (key,)
        ).fetchone()

    return row[0] if row else None

if __name__ == "__main__":
    init_db()
    print(f"NEXA structured memory ready: {DB_PATH}")

def get_all_facts():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM facts ORDER BY key"
        ).fetchall()

    return {key: value for key, value in rows}

def resolve_fact_query(query):
    query_words = set(
        w.lower()
        for w in re.findall(r"[A-Za-z0-9]+", query)
        if len(w) >= 2
    )

    facts = get_all_facts()

    best_match = None
    best_score = 0

    for key, value in facts.items():
        key_words = set(key.lower().replace("_", " ").split())

        score = len(query_words.intersection(key_words))

        if score > best_score:
            best_score = score
            best_match = (key, value)

    if best_score >= 2:
        return best_match

    return None

def normalize_fact_key(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

def extract_fact(text):
    clean = text.strip().lower()

    # Manglish pattern:
    # "ente favourite color green aanu"
    patterns = [
        (
            r"^ente\s+(favourite color|favorite color)\s+(.+?)\s+aanu(?:[,\s].*)?$",
            "favourite_color"
        ),
        (
            r"^ente\s+name\s+(.+?)\s+aanu(?:[,\s].*)?$",
            "name"
        ),
        (
            r"^my\s+(favourite color|favorite color)\s+is\s+(.+?)(?:[,.]|$)",
            "favourite_color"
        ),
        (
            r"^my\s+name\s+is\s+(.+?)(?:[,.]|$)",
            "name"
        ),
    ]

    for pattern, key in patterns:
        match = re.match(pattern, clean)

        if match:
            value = match.groups()[-1].strip()
            return key, value

    return None
