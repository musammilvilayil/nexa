from __future__ import annotations

import json
import re
from pathlib import Path

from bridges import OllamaBridge, OllamaBridgeError
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
from runtime import build_runtime
from training import TradingCurriculum, TrainingStore

MODEL = "qwen3:1.7b"
MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
REPO_ROOT = Path(__file__).resolve().parents[1]
TRAINING_DB = REPO_ROOT / "data" / "training.db"

SYSTEM_PROMPT = """
You are NEXA, a local-first autonomous personal AI operating platform.

Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Architecture rules:
- Deterministic registered skills execute through the NEXA Kernel before the language model.
- Never claim a tool action happened unless the deterministic tool layer reports success.
- Never invent installed capabilities.
- Trading research may discuss hypotheses and evidence, but never claim guaranteed profit or certainty.
- NEXA's risk controls, audit ledger, owner mandate, and kill switches outrank strategy preferences.
- Live trading is never considered armed merely because a model, prompt, or environment string asks for it.

Language rules:
- Manglish means Malayalam spoken language written using Latin letters.
- When the user writes Manglish, understand the Malayalam meaning and answer in natural Latin-script Manglish.
- Manglish output should use natural Malayalam conversational grammar written in Latin letters. English technical words are fine.
- Do not output Malayalam Unicode/script for a Manglish user unless they explicitly ask for Malayalam script.
- Normalized Malayalam and English meaning supplied by the language layer are interpretation metadata only.
- Never answer by merely translating, echoing, or restating the current user message.
- Answer the user's actual request or question directly.

Memory rules:
- Use retrieved memory when it contains the answer.
- Do not ask for information already present in memory.
- Preserve user facts accurately.
- If a requested personal fact is not stored, say that it is not stored instead of guessing.
""".strip()


_ollama = OllamaBridge(model=MODEL)


def ask_ollama(messages):
    return _ollama.chat(messages, think=False)


def _normalized_text(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _is_translation_echo(reply, language_result):
    reply_norm = _normalized_text(reply)
    if not reply_norm:
        return False

    candidates = [language_result.original, language_result.meaning_english]
    for candidate in candidates:
        if not candidate:
            continue
        candidate_norm = _normalized_text(candidate)
        if not candidate_norm:
            continue
        if reply_norm == candidate_norm:
            return True
        if len(candidate_norm.split()) >= 4 and candidate_norm in reply_norm:
            return True
        candidate_words = set(candidate_norm.split())
        reply_words = set(reply_norm.split())
        if len(candidate_words) >= 5:
            overlap = len(candidate_words & reply_words) / len(candidate_words)
            if overlap >= 0.90:
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
Do NOT translate, paraphrase, copy, or repeat the user's question.
Do NOT simply prepend words like "Athe" to the user's sentence.
Write conversational Malayalam using LATIN letters only: natural Manglish.
English technical words are allowed, but the sentence grammar should sound like spoken Malayalam.
Do not use Malayalam Unicode/script.
If the user is asking for permission/advice, answer the decision first and then give one short useful reason or next action.

Return only the corrected answer.
""".strip()

    repair_messages = messages + [
        {"role": "assistant", "content": reply},
        {"role": "user", "content": correction},
    ]
    repaired = ask_ollama(repair_messages)
    if not isinstance(repaired, str):
        repaired = str(repaired)

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
    print(
        "\nNEXA Teacher-Student: "
        f"{stats['lessons']} learned lesson(s), "
        f"{stats['reuses']} local reuse(s), "
        f"avg teacher confidence {stats['average_confidence']:.2f}.\n"
    )


def _skills_reply(runtime) -> str:
    lines = ["NEXA Kernel plugins:"]
    for metadata in runtime.registry.list_metadata():
        lines.append(f"- {metadata.name} v{metadata.version}: {metadata.description}")
        for operation in metadata.operations:
            lines.append(f"  - {operation.name} [{operation.risk.value}]")
    lines.extend(
        [
            "Built-in services:",
            "- Personal Memory [active]",
            "- Teacher-Student Language Layer [active]",
            "- Gemini/Ollama training bridges [available when configured]",
        ]
    )
    return "\n".join(lines)


def _training_status_reply() -> str:
    store = TrainingStore(TRAINING_DB)
    curriculum = TradingCurriculum()
    lines = ["NEXA trading training:"]
    mastered = 0
    for module in curriculum.modules:
        progress = store.progress(module.module_id)
        if progress is None:
            lines.append(f"- {module.module_id}: pending")
        elif progress["mastered"]:
            mastered += 1
            lines.append(
                f"- {module.module_id}: mastered "
                f"(best {progress['best_score']:.2f}, attempts {progress['attempts']})"
            )
        else:
            lines.append(
                f"- {module.module_id}: in progress "
                f"(best {progress['best_score']:.2f}, attempts {progress['attempts']})"
            )
    lines.append(f"Mastered {mastered}/{len(curriculum.modules)} modules.")
    return "\n".join(lines)


def _kernel_reply(response) -> str:
    if response.status == "confirmation_required" and response.pending_action is not None:
        action = response.pending_action
        expires = action.expires_at_utc.isoformat()
        return (
            f"Confirmation required. Action ID: {action.action_id}\n"
            f"Skill: {action.skill_name}\n"
            f"Operation: {action.operation}\n"
            f"Risk: {action.risk.value}\n"
            f"Expires: {expires}\n"
            f"Use /confirm {action.action_id} to execute the exact validated action, "
            f"or /cancel {action.action_id}."
        )

    base = response.message
    if response.result is not None and response.result.data is not None:
        data = response.result.data
        if isinstance(data, str):
            if data.strip() and data.strip() != base.strip():
                return f"{base}\n{data}"
        else:
            try:
                encoded = json.dumps(data, ensure_ascii=False, indent=2, default=str)
            except TypeError:
                encoded = repr(data)
            if encoded not in {"null", "{}", "[]"}:
                return f"{base}\n{encoded}"
    return base


def _pending_reply(runtime) -> str:
    pending = runtime.kernel.pending_actions()
    if not pending:
        return "No pending kernel actions."
    lines = ["Pending actions:"]
    for action in pending:
        lines.append(
            f"- {action.action_id}: {action.skill_name}.{action.operation} "
            f"[{action.risk.value}] expires {action.expires_at_utc.isoformat()}"
        )
    return "\n".join(lines)


def main():
    init_db()
    runtime = build_runtime()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(load_recent_messages(limit=12))

    print(
        "NEXA ONLINE - Kernel + Memory + Teacher-Student + Workspace/File/Git/GitHub/Trading enabled.\n"
        "Commands: /skills, /pending, /confirm <id>, /cancel <id>, /teacher-stats, /training-status, /exit.\n"
    )

    while True:
        user = input("You: ").strip()
        lowered = user.lower()

        if lowered in {"/exit", "exit", "quit"}:
            print("NEXA: Shutting down.")
            break
        if lowered == "/teacher-stats":
            _print_teacher_stats()
            continue
        if lowered == "/training-status":
            print(f"\nNEXA: {_training_status_reply()}\n")
            continue
        if lowered == "/skills":
            print(f"\nNEXA: {_skills_reply(runtime)}\n")
            continue
        if lowered == "/pending":
            print(f"\nNEXA: {_pending_reply(runtime)}\n")
            continue
        if lowered.startswith("/confirm "):
            action_id = user.split(maxsplit=1)[1].strip()
            response = runtime.kernel.confirm(action_id)
            reply = _kernel_reply(response)
            save_message("user", user)
            _record_reply(messages, user, reply)
            continue
        if lowered.startswith("/cancel "):
            action_id = user.split(maxsplit=1)[1].strip()
            response = runtime.kernel.cancel(action_id)
            reply = _kernel_reply(response)
            save_message("user", user)
            _record_reply(messages, user, reply)
            continue
        if not user:
            continue

        # Registered tool/plugin routing is always attempted before the LLM.
        response = runtime.kernel.process(user)
        if response.status != "no_match":
            reply = _kernel_reply(response)
            save_message("user", user)
            _record_reply(messages, user, reply)
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
            if not isinstance(reply, str):
                reply = str(reply)
            reply = repair_manglish_reply(reply, language_result, messages)
        except OllamaBridgeError as exc:
            reply = f"Local model error: {exc}"

        messages.append({"role": "assistant", "content": reply})
        save_message("assistant", reply)
        print(f"\nNEXA: {reply}\n")


if __name__ == "__main__":
    main()
