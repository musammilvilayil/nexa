import re
from pathlib import Path

import httpx

from agent_runtime import AgentRuntime
from git_router import handle_git_command
from git_skill import GitSkill
from language import prepare_user_input
from memory import extract_fact, get_fact, get_teacher_stats, identify_fact_query, init_db, load_recent_messages, resolve_fact_query, save_message, search_memory, set_fact
from skill_registry import handle_skill_command

MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/chat"
MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
REPO_ROOT = Path(__file__).resolve().parents[1]

SYSTEM_PROMPT = """
You are NEXA, a local personal AI assistant.
Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Language rules:
- Manglish means Malayalam spoken language written using Latin letters.
- When the user writes Manglish, understand the Malayalam meaning and answer in natural Latin-script Manglish.
- Do not output Malayalam Unicode/script for a Manglish user unless explicitly asked.
- Never answer by merely translating, echoing, or restating the current user message.
- Use retrieved memory when it contains the answer and never invent missing personal facts.
""".strip()


def ask_ollama(messages):
    response = httpx.post(OLLAMA_URL, json={"model": MODEL, "messages": messages, "stream": False, "think": False}, timeout=180)
    response.raise_for_status()
    return response.json()["message"]["content"]


def _normalized_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_translation_echo(reply, language_result):
    reply_norm = _normalized_text(reply)
    if not reply_norm:
        return False
    for candidate in (language_result.original, language_result.meaning_english):
        if not candidate:
            continue
        candidate_norm = _normalized_text(candidate)
        if not candidate_norm:
            continue
        if reply_norm == candidate_norm or (len(candidate_norm.split()) >= 4 and candidate_norm in reply_norm):
            return True
        candidate_words = set(candidate_norm.split())
        reply_words = set(reply_norm.split())
        if len(candidate_words) >= 5 and len(candidate_words & reply_words) / len(candidate_words) >= 0.90:
            return True
    return False


def _missing_fact_reply(key):
    return {"name": "Ninte peru ithuvare memory-il save cheythittilla.", "favourite_color": "Ninte favourite color ithuvare memory-il save cheythittilla."}.get(key, "Aa detail ithuvare memory-il save cheythittilla.")


def _contextual_next_step_reply(language_result, relevant_memory):
    if relevant_memory:
        return None
    meaning = _normalized_text(language_result.meaning_english or "")
    original = _normalized_text(language_result.original)
    if meaning in {"what should we do now", "what do we do now", "nammal ippo entha cheyyande"} or original in {"what should we do now", "what do we do now", "nammal ippo entha cheyyande"}:
        return "Ippo exact task context enikku memory-il illa. Eth task/project aanu continue cheyyendath enn parayu."
    return None


def repair_manglish_reply(reply, language_result, messages):
    if language_result.detected_language != "manglish":
        return reply
    normalized = (language_result.normalized_malayalam or "").strip()
    reply_clean = reply.strip()
    if not MALAYALAM_RE.search(reply_clean) and reply_clean.rstrip(".!?") != normalized.rstrip(".!?") and not _is_translation_echo(reply_clean, language_result):
        return reply
    correction = f"""Answer the ORIGINAL user's request directly. Do not translate, copy, or repeat it. Write natural conversational Malayalam in LATIN letters only (Manglish). English technical words are fine.\n\nOriginal: {language_result.original}\nMeaning: {language_result.meaning_english or 'use original'}\nReturn only the corrected answer."""
    repaired = ask_ollama(messages + [{"role": "assistant", "content": reply}, {"role": "user", "content": correction}])
    if _is_translation_echo(repaired, language_result) or MALAYALAM_RE.search(repaired):
        meaning = _normalized_text(language_result.meaning_english or "")
        if "rest" in meaning and ("should" in meaning or "can" in meaning):
            return "Athe, kurach neram rest edukku. Fresh aayittu pinne continue cheyyam."
    return repaired


def _record_reply(messages, user, reply):
    save_message("assistant", reply)
    messages.append({"role": "user", "content": user})
    messages.append({"role": "assistant", "content": reply})
    print(f"\nNEXA: {reply}\n")


def _print_teacher_stats():
    stats = get_teacher_stats()
    print(f"\nNEXA Teacher-Student: {stats['lessons']} learned lesson(s), {stats['reuses']} local reuse(s), avg teacher confidence {stats['average_confidence']:.2f}.\n")


def main():
    init_db()
    git_skill = GitSkill(REPO_ROOT)
    agent_runtime = AgentRuntime(REPO_ROOT)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(load_recent_messages(limit=12))
    print("NEXA ONLINE - Auto Memory + Teacher-Student + Git Operator + Gemini Agent Enabled. Type /skills, /agent plan <goal>, /agent run <goal>, /agent confirm, /teacher-stats, /git status, /git pull, or /exit.\n")

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
        if user.lower() == "/agent confirm":
            save_message("user", user)
            _record_reply(messages, user, agent_runtime.confirm())
            continue
        agent_match = re.match(r"^/agent\s+run\s+(.+)$", user, flags=re.IGNORECASE)
        if agent_match:
            save_message("user", user)
            _record_reply(messages, user, agent_runtime.run(agent_match.group(1)))
            continue
        skill_reply = handle_skill_command(user)
        if skill_reply is not None:
            save_message("user", user)
            _record_reply(messages, user, skill_reply)
            continue
        git_reply = handle_git_command(user, git_skill)
        if git_reply is not None:
            save_message("user", user)
            _record_reply(messages, user, git_reply)
            continue
        save_message("user", user)
        new_fact = extract_fact(user)
        if new_fact:
            key, value = new_fact
            set_fact(key, value)
            _record_reply(messages, user, f"Orma vechu: {key} = {value}")
            continue
        fact_key = identify_fact_query(user)
        if fact_key:
            value = get_fact(fact_key)
            _record_reply(messages, user, value if value is not None else _missing_fact_reply(fact_key))
            continue
        fact = resolve_fact_query(user)
        if fact:
            _, value = fact
            _record_reply(messages, user, value)
            continue
        relevant = search_memory(user, limit=5)
        memory_context = "\nRelevant memory:\n" + "".join(f"- {item['role']}: {item['content']}\n" for item in relevant) if relevant else ""
        language_result = prepare_user_input(user)
        context_reply = _contextual_next_step_reply(language_result, relevant)
        if context_reply:
            _record_reply(messages, user, context_reply)
            continue
        messages.append({"role": "user", "content": memory_context + "\nCurrent user message:\n" + language_result.model_text()})
        try:
            reply = repair_manglish_reply(ask_ollama(messages), language_result, messages)
        except httpx.HTTPError as exc:
            reply = f"Local model error: {exc}"
        messages.append({"role": "assistant", "content": reply})
        save_message("assistant", reply)
        print(f"\nNEXA: {reply}\n")


if __name__ == "__main__":
    main()
