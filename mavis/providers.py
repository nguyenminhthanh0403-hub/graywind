import os

import httpx
from fastapi import HTTPException

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _build_prompt(query, context):
    if context:
        return f"{context}\n\nQuestion: {query}"
    return query


async def groq_answer(query, context=None):
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not set")

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": _build_prompt(query, context)}],
            },
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Groq error: {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]
