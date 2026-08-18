import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "nexa.db"

MEMORY_STOPWORDS = {
    "aanu",
    "aano",
    "ahno",
    "alle",
    "alla",
    "entha",
    "enthu",
    "ente",
    "njan",
    "njn",
    "nammal",
    "namukku",
    "ippo",
    "ith",
    "ithu",
    "athu",
    "oru",
    "pinne",
    "undo",
    "ille",
    "cheyyande",
    "cheyyam",
    "venam",
    "venda",
}

FACT_QUERY_PATTERNS = {
    "name": [
        r"\bente\s+(?:peru|peeru|name)\s+(?:entha|enthanu|enthaan|enthaa)\b",
        r"\bwhat\s+is\s+my\s+name\b",
        r"\bwhat(?:'s| is)\s+my\s+name\b",
    ],
    "favourite_color": [
        r"\bente\s+(?:favourite|favorite)\s+color\s+(?:entha|enthanu|enthaan|enthaa)\b",
        r"\bwhat\s+is\s+my\s+(?:favourite|favorite)\s+colou?r\b",
        r"\bwhat(?:'s| is)\s+my\s+(?:favourite|favorite)\s+colou?r\b",
    ],
}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL DEFAULT 'default',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS language_cache (
                source_text TEXT PRIMARY KEY,
                detected_language TEXT NOT NULL,
                normalized_malayalam TEXT,
                meaning_english TEXT,
                confidence REAL NOT NULL DEFAULT 0.0,
                provider TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.commit()


def save_message(role, content, conversation_id="default"):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (conversation_id, role, content, _utc_now()),
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
            (conversation_id, limit),
        ).fetchall()

    rows.reverse()
    return [{"role": role, "content": content} for role, content in rows]


def search_memory(query, limit=5):
    words = [
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", query)
        if len(word) >= 3 and word.lower() not in MEMORY_STOPWORDS
    ]

    if not words:
        return []

    normalized_query = query.strip().lower()

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
    minimum_score = 2 if len(set(words)) >= 2 else 1

    for role, content in rows:
        text = content.strip().lower()

        # The current message is saved before retrieval; never retrieve that same
        # message back as if it were older memory.
        if text == normalized_query:
            continue

        score = sum(1 for word in set(words) if word in text)

        if score >= minimum_score:
            scored.append((score, role, content))

    scored.sort(key=lambda item: item[0], reverse=True)

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
            (key, value, _utc_now()),
        )
        conn.commit()


def get_fact(key):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM facts WHERE key = ?",
            (key,),
        ).fetchone()

    return row[0] if row else None


def get_all_facts():
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT key, value FROM facts ORDER BY key"
        ).fetchall()

    return {key: value for key, value in rows}


def identify_fact_query(query):
    clean = " ".join(query.strip().lower().split())

    for key, patterns in FACT_QUERY_PATTERNS.items():
        if any(re.search(pattern, clean) for pattern in patterns):
            return key

    return None


def resolve_fact_query(query):
    # Explicit intent aliases are safer than word overlap. For example, the
    # Manglish word "peru" should resolve the stored "name" fact.
    explicit_key = identify_fact_query(query)

    if explicit_key:
        value = get_fact(explicit_key)
        return (explicit_key, value) if value is not None else None

    query_words = {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9]+", query)
        if len(word) >= 2
    }

    facts = get_all_facts()
    best_match = None
    best_score = 0

    for key, value in facts.items():
        key_words = set(key.lower().replace("_", " ").split())
        score = len(query_words.intersection(key_words))

        if score > best_score:
            best_score = score
            best_match = (key, value)

    # Keep fuzzy fallback conservative; explicit aliases above handle one-word
    # concepts such as name/peru without accidentally matching unrelated text.
    if best_score >= 2:
        return best_match

    return None


def normalize_fact_key(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def extract_fact(text):
    clean = text.strip().lower()

    patterns = [
        (
            r"^ente\s+(favourite color|favorite color)\s+(.+?)\s+aanu(?:[,\s].*)?$",
            "favourite_color",
        ),
        (
            r"^ente\s+(?:name|peru|peeru)\s+(.+?)\s+aanu(?:[,\s].*)?$",
            "name",
        ),
        (
            r"^my\s+(favourite color|favorite color)\s+is\s+(.+?)(?:[,.]|$)",
            "favourite_color",
        ),
        (
            r"^my\s+name\s+is\s+(.+?)(?:[,.]|$)",
            "name",
        ),
    ]

    for pattern, key in patterns:
        match = re.match(pattern, clean)

        if match:
            value = match.groups()[-1].strip()
            return key, value

    return None


def save_language_cache(
    source_text,
    detected_language,
    normalized_malayalam=None,
    meaning_english=None,
    confidence=0.0,
    provider="local",
):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO language_cache (
                source_text,
                detected_language,
                normalized_malayalam,
                meaning_english,
                confidence,
                provider,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_text)
            DO UPDATE SET
                detected_language = excluded.detected_language,
                normalized_malayalam = excluded.normalized_malayalam,
                meaning_english = excluded.meaning_english,
                confidence = excluded.confidence,
                provider = excluded.provider,
                updated_at = excluded.updated_at
            """,
            (
                source_text,
                detected_language,
                normalized_malayalam,
                meaning_english,
                float(confidence),
                provider,
                _utc_now(),
            ),
        )
        conn.commit()


def get_language_cache(source_text):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                detected_language,
                normalized_malayalam,
                meaning_english,
                confidence,
                provider
            FROM language_cache
            WHERE source_text = ?
            """,
            (source_text,),
        ).fetchone()

    if not row:
        return None

    return {
        "detected_language": row[0],
        "normalized_malayalam": row[1],
        "meaning_english": row[2],
        "confidence": float(row[3]),
        "provider": row[4],
    }


if __name__ == "__main__":
    init_db()
    print(f"NEXA structured memory ready: {DB_PATH}")
