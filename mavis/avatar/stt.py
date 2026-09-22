"""Transcribe an utterance with Groq's Whisper endpoint."""
import io
import os
import wave

import httpx
import numpy as np

GROQ_STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
GROQ_STT_MODEL = "whisper-large-v3-turbo"


class STTError(RuntimeError):
    pass


def _to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(pcm.tobytes())
    return buf.getvalue()


async def transcribe(samples: np.ndarray, sample_rate: int = 16000,
                     *, client: httpx.AsyncClient | None = None) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise STTError("GROQ_API_KEY not set")
    if samples.size == 0:
        return ""

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        resp = await client.post(
            GROQ_STT_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("utterance.wav", _to_wav_bytes(samples, sample_rate),
                            "audio/wav")},
            data={"model": GROQ_STT_MODEL},
        )
    except httpx.RequestError as exc:
        raise STTError(f"speech-to-text unreachable: {exc}") from exc
    finally:
        if owns_client:
            await client.aclose()

    if resp.status_code != 200:
        raise STTError(f"speech-to-text failed ({resp.status_code})")
    return resp.json().get("text", "").strip()
