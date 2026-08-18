import httpx

MODEL = "gemma3n:e2b"
URL = "http://localhost:11434/api/chat"

system_prompt = """
You are NEXA.

The user often speaks Malayalam using English letters. This is called Manglish.

Examples:
- sugam ahno = ????????
- entha cheyyunne = ????? ????????????
- njan varam = ??? ????
- enikk manasilayi = ??????? ??????????
- namuk cheyyam = ??????? ???????
- pattumo = ????????

When the user writes Manglish:
1. Understand it as Malayalam.
2. Do NOT complain about spelling.
3. Preserve the exact meaning and intent of the Manglish sentence. Do not paraphrase it into a different question.
4. Reply naturally using English letters in Manglish only. Do not use Malayalam script or provide translations unless the user asks.
"""

text = input("You: ")

r = httpx.post(
    URL,
    json={
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "stream": False
    },
    timeout=300
)

r.raise_for_status()
print("\nNEXA:", r.json()["message"]["content"])

