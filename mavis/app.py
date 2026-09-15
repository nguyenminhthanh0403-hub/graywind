from fastapi import FastAPI
from pydantic import BaseModel

import grounding
from providers import GROQ_MODEL, groq_answer

app = FastAPI()


class AskRequest(BaseModel):
    query: str


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL}


@app.post("/ask")
async def ask(req: AskRequest):
    hits = grounding.retrieve(req.query)
    context = grounding.format_context(hits)
    answer = await groq_answer(req.query, context)

    return {
        "answer": answer,
        "citations": hits,
    }
