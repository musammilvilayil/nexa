import re

import httpx

from language import prepare_user_input
from memory import (
    extract_fact,
    get_fact,
    get_teacher_stats,
    identify_fact_query,
    init_db,
    load_recent_messages,
    resolve_fact_query,
    save_message,
    search_memory,
    set_fact,
)

MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")

SYSTEM_PROMPT = """
You are NEXA, a local personal AI assistant.

Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Language rules:
- Manglish means Malayalam spoken language written using Latin letters.
- When the user writes Manglish, understand the Malayalam meaning and answer in natural Latin-script Manglish.
- Manglish output should use natural Malayalam conversational grammar written in Latin letters. English technical words are fine.
- Do not output Malayalam Unicode/script for a Manglish user unless they explicitly ask for Malayalam script.
- Normalized Malayalam and English meaning supplied by the language layer are interpretation metadata only.
- Never answer by merely translating, echoing, or restating the current user message.
- Answer the user's actual request or question directly.
- If the language layer provides normalized Malayalam or an English meaning, use it only to understand intent.

Memory rules:
- Use retrieved memory when it contains the answer.
- Do not ask for information already present in memory.
- Preserve user facts accurately.
- If a requested personal fact is not stored, say that it is not stored instead of guessing.
""".strip()


def ask_ollama(messages):
    response = httpx.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "think": False,
        },
        timeout=180,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


def _normalized_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_translation_echo(reply, language_result):
    reply_norm = _normalized_text(reply)

    if not reply_norm:
        return False

    candidates = [
        language_result.original,
        language_result.meaning_english,
    ]

    for candidate in candidates:
        if candidate and reply_norm == _normalized_text(candidate):
            return True

    return False


def _missing_fact_reply(key):
    replies = {
        "name": "Ninte peru ithuvare memory-il save cheythittilla.",
        "favourite_color": "Ninte favourite color ithuvare memory-il save cheythittilla.",
    }
    return replies.get(key, "Aa detail ithuvare memory-il save cheythittilla.")


def _contextual_next_step_reply(language_result, relevant_memory):
    if relevant_memory:
        return None

    meaning = _normalized_text(language_result.meaning_english or "")
    original = _normalized_text(language_result.original)

    next_step_questions = {
        "what should we do now",
        "what do we do now",
        "nammal ippo entha cheyyande",
    }

    if meaning in next_step_questions or original in next_step_questions:
        return (
            "Ippo exact task context enikku memory-il illa. "
            "Eth task/project aanu continue cheyyendath enn parayu."
        )

    return None


def repair_manglish_reply(reply, language_result, messages):
    if language_result.detected_language != "manglish":
        return reply

    normalized = (language_result.normalized_malayalam or "").strip()
    reply_clean = reply.strip()

    used_malayalam_script = bool(MALAYALAM_RE.search(reply_clean))
    merely_repeated_normalization = bool(
        normalized and reply_clean.rstrip(".!?") == normalized.rstrip(".!?")
    )
    translation_echo = _is_translation_echo(reply_clean, language_result)

    if not used_malayalam_script and not merely_repeated_normalization and not translation_echo:
        return reply

    correction = f"""
Your previous draft failed NEXA's Manglish response rule.

ORIGINAL USER MESSAGE:
{language_result.original}

INTENDED MEANING (interpretation only):
{language_result.meaning_english or 'Use the original Manglish message.'}

Now answer the ORIGINAL user's request directly.
Do NOT translate, paraphrase, or repeat the user's question.
Write conversational Malayalam using LATIN letters only: natural Manglish.
English technical words are allowed, but the sentence grammar should sound like spoken Malayalam.
Do not use Malayalam Unicode/script.

Good style examples:
- "Athe, nammal ath cheyyam."
- "Ippo next step testing aanu."
- "Nammal adyam issue check cheythittu fix cheyyam."

Return only the corrected answer.
""".strip()

    repair_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": correction},
    ]

    return ask_ollama(repair_messages)


def _record_reply(messages, user, reply):
    save_message("assistant", reply)
    messages.append({"role": "user", "content": user})
    messages.append({"role": "assistant", "content": reply})
    print(f"\nNEXA: {reply}\n")


def _print_teacher_stats():
    stats = get_teacher_stats()
    print(
        "\nNEXA Teacher-Student: "
        f"{stats['lessons']} learned lesson(s), "
        f"{stats['reuses']} local reuse(s), "
        f"avg teacher confidence {stats['average_confidence']:.2f}.\n"
    )


def main():
    init_db()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(load_recent_messages(limit=12))

    print(
        "NEXA ONLINE - Auto Memory + Teacher-Student Language Layer Enabled. "
        "Type /teacher-stats or /exit.\n"
    )

    while True:
        user = input("You: ").strip()

        if user.lower() in {"/exit", "exit", "quit"}:
            print("NEXA: Shutting down.")
            break

        if user.lower() == "/teacher-stats":
            _print_teacher_stats()
            continue

        if not user:
            continue

        save_message("user", user)

        new_fact = extract_fact(user)

        if new_fact:
            key, value = new_fact
            set_fact(key, value)
            reply = f"Orma vechu: {key} = {value}"
            _record_reply(messages, user, reply)
            continue

        fact_key = identify_fact_query(user)

        if fact_key:
            value = get_fact(fact_key)
            reply = value if value is not None else _missing_fact_reply(fact_key)
            _record_reply(messages, user, reply)
            continue

        fact = resolve_fact_query(user)

        if fact:
            _, value = fact
            _record_reply(messages, user, value)
            continue

        relevant = search_memory(user, limit=5)
        memory_context = ""

        if relevant:
            memory_context = "\nRelevant memory:\n"

            for item in relevant:
                memory_context += f"- {item['role']}: {item['content']}\n"

        language_result = prepare_user_input(user)

        context_reply = _contextual_next_step_reply(language_result, relevant)

        if context_reply:
            _record_reply(messages, user, context_reply)
            continue

        model_input = language_result.model_text()
        current_message = memory_context + "\nCurrent user message:\n" + model_input
        messages.append({"role": "user", "content": current_message})

        try:
            reply = ask_ollama(messages)
            reply = repair_manglish_reply(reply, language_result, messages)
        except httpx.HTTPError as exc:
            reply = f"Local model error: {exc}"

        messages.append({"role": "assistant", "content": reply})
        save_message("assistant", reply)

        print(f"\nNEXA: {reply}\n")


if __name__ == "__main__":
    main()
