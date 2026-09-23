from fastapi import Depends, FastAPI
from pydantic import BaseModel

import auth
import grounding
import graywind_grounding
from providers import GROQ_MODEL, groq_answer
from rate_limit import check_rate_limit

app = FastAPI()


class AskRequest(BaseModel):
    query: str
    # Optional, and None for every existing caller: the MCP wrapper and the CLI
    # want full answers. Only the spoken avatar sets it, because there a long
    # answer is a long silence while it is voice-converted.
    max_chars: int | None = None


@app.get("/status")
def status():
    return {"ok": True, "provider": GROQ_MODEL, "auth_configured": bool(auth.MAVIS_API_KEY)}


@app.post("/ask")
async def ask(req: AskRequest, api_key: str = Depends(auth.require_api_key)):
    check_rate_limit(api_key)

    bullion_hits = grounding.retrieve(req.query)
    graywind_hits = graywind_grounding.retrieve(req.query)

    context = "\n\n".join(filter(None, [
        grounding.format_context(bullion_hits),
        graywind_grounding.format_context(graywind_hits),
    ])) or None

    answer = await groq_answer(req.query, context, max_chars=req.max_chars)

    return {
        "answer": answer,
        "citations": bullion_hits + graywind_hits,
    }
