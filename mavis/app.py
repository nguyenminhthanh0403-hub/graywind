from fastapi import Depends, FastAPI
from pydantic import BaseModel

import auth
import grounding
import graywind_grounding
from providers import GROQ_MODEL, groq_answer

app = FastAPI()


class AskRequest(BaseModel):
    query: str


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL}


@app.post("/ask")
async def ask(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    answer = await groq_answer(req.query, context)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
    }
