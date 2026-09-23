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


def _brevity_instruction(max_chars):
    """System message asking for an answer that fits in `max_chars`.

    The spoken caller truncates anything longer (see avatar/brain.py), and a
    truncated answer stops mid-thought. Asking for a short answer costs nothing
    and gets a *complete* one instead of the first 200 characters of a long one.

    A character budget is given as an approximate sentence count because models
    honour "two or three sentences" far better than "200 characters".
    """
    sentences = max(1, round(max_chars / 110))
    return (
        f"Answer in at most {sentences} short "
        f"{'sentence' if sentences == 1 else 'sentences'} — under {max_chars} "
        "characters. Your answer is read aloud, so lead with the point, keep "
        "any figures exact, and do not use lists, markdown or preamble."
    )


async def groq_answer(query, context=None, max_chars=None):
    if not GROQ_API_KEY:
        raise HTTPException(500, "GROQ_API_KEY not set")

    messages = []
    if max_chars:
        messages.append({"role": "system", "content": _brevity_instruction(max_chars)})
    messages.append({"role": "user", "content": _build_prompt(query, context)})

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={"model": GROQ_MODEL, "messages": messages},
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Groq error: {resp.text}")

    data = resp.json()
    return data["choices"][0]["message"]["content"]
