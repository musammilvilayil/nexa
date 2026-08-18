import httpx
from memory import (
    init_db,
    save_message,
    load_recent_messages,
    search_memory,
    resolve_fact_query,
    extract_fact,
    set_fact,
)

MODEL = "qwen3:1.7b"
OLLAMA_URL = "http://localhost:11434/api/chat"

SYSTEM_PROMPT = """
You are NEXA, a local personal AI assistant.

Be accurate, helpful, concise, and technical when needed.
You understand English, Malayalam, and Manglish.

Important:
- Use retrieved memory when it contains the answer.
- Do not ask for information already present in memory.
- Preserve user facts accurately.
"""

init_db()

messages = [
    {"role": "system", "content": SYSTEM_PROMPT}
]

messages.extend(load_recent_messages(limit=12))

print("NEXA ONLINE - Auto Memory Enabled. Type /exit to quit.\n")

while True:
    user = input("You: ").strip()

    if user.lower() in {"/exit", "exit", "quit"}:
        print("NEXA: Shutting down.")
        break

    if not user:
        continue

    save_message("user", user)

    # 1. Learn new structured facts automatically
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

    # 2. Resolve known facts
    fact = resolve_fact_query(user)

    if fact:
        key, value = fact
        reply = value

        save_message("assistant", reply)
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": reply})

        print(f"\nNEXA: {reply}\n")
        continue

    # 3. Search conversational memory
    relevant = search_memory(user, limit=5)

    memory_context = ""
    if relevant:
        memory_context = "\nRelevant memory:\n"

        for item in relevant:
            memory_context += f"- {item['role']}: {item['content']}\n"

    messages.append({
        "role": "user",
        "content": memory_context + "\nCurrent user message:\n" + user
    })

    # 4. Ask local model
    response = httpx.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "messages": messages,
            "stream": False,
            "think": False
        },
        timeout=180
    )

    response.raise_for_status()

    reply = response.json()["message"]["content"]

    messages.append({"role": "assistant", "content": reply})
    save_message("assistant", reply)

    print(f"\nNEXA: {reply}\n")
