import httpx

payload = {
    "model": "qwen3:4b",
    "prompt": "Reply with exactly: NEXA ONLINE",
    "stream": False
}

r = httpx.post("http://localhost:11434/api/generate", json=payload, timeout=120)
r.raise_for_status()
print(r.json()["response"])
