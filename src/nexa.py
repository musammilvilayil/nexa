import httpx

from language import prepare_user_input
from memory import (
    extract_fact,
    init_db,
    load_recent_messages,
    resolve_fact_query,
    save_message,
    search_memory,
    set_fact,
)

MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """
You are NEXA, a local personal AI assistant.

Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Language rules:
- Manglish means Malayalam written using Latin letters.
- When the user writes Manglish, understand the Malayalam meaning and normally reply in natural Manglish.
- Do not translate literally when a natural Malayalam meaning is clear.
- If the language layer provides normalized Malayalam or an English meaning, use it as interpretation help while preserving the user's intent.

Memory rules:
- Use retrieved memory when it contains the answer.
- Do not ask for information already present in memory.
- Preserve user facts accurately.
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


def main():
    init_db()

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(load_recent_messages(limit=12))

    print("NEXA ONLINE - Auto Memory + Language Layer Enabled. Type /exit to quit.\n")

    while True:
        user = input("You: ").strip()

        if user.lower() in {"/exit", "exit", "quit"}:
            print("NEXA: Shutting down.")
            break

        if not user:
            continue

        # Keep the user's original words in permanent conversational memory.
        save_message("user", user)

        # 1. Learn supported structured facts from the original message.
        new_fact = extract_fact(user)

        if new_fact:
            key, value = new_fact
            set_fact(key, value)
            reply = f"Orma vechu: {key} = {value}"

            save_message("assistant", reply)
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": reply})

            print(f"\nNEXA: {reply}\n")
            continue

        # 2. Resolve known facts deterministically before asking an LLM.
        fact = resolve_fact_query(user)

        if fact:
            _, value = fact
            reply = value

            save_message("assistant", reply)
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": reply})

            print(f"\nNEXA: {reply}\n")
            continue

        # 3. Retrieve relevant conversational memory using the original text.
        relevant = search_memory(user, limit=5)
        memory_context = ""

        if relevant:
            memory_context = "\nRelevant memory:\n"

            for item in relevant:
                memory_context += f"- {item['role']}: {item['content']}\n"

        # 4. Normalize/annotate the user's language before local reasoning.
        language_result = prepare_user_input(user)
        model_input = language_result.model_text()

        current_message = (
            memory_context
            + "\nCurrent user message:\n"
            + model_input
        )

        messages.append({"role": "user", "content": current_message})

        # 5. Ask the local model.
        try:
            reply = ask_ollama(messages)
        except httpx.HTTPError as exc:
            reply = f"Local model error: {exc}"

        messages.append({"role": "assistant", "content": reply})
        save_message("assistant", reply)

        print(f"\nNEXA: {reply}\n")


if __name__ == "__main__":
    main()
