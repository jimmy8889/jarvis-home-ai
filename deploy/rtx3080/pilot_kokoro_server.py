from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from io import BytesIO
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
import soundfile as sf
import torch

from kokoro import KPipeline


MODEL_NAME = "Kokoro-82M"
PORT = int(os.environ.get("PILOT_KOKORO_PORT", "8032"))
DEVICE = os.environ.get("PILOT_KOKORO_DEVICE", "cuda").strip() or "cuda"
API_KEY_FILE = Path(
    os.environ.get("PILOT_KOKORO_API_KEY_FILE", "/etc/pilot/kokoro-api-key")
)
MAX_INPUT_CHARS = int(os.environ.get("PILOT_KOKORO_MAX_INPUT_CHARS", "4000"))
SAMPLE_RATE = 24_000

# Kokoro's English voice IDs use a prefix to select the accent pipeline:
# ``a*`` is American English and ``b*`` is British English. The latter is the
# closest stock baseline to Australian English; an Australian cloned voice is
# intentionally a separate, consent-gated future configuration.
AMERICAN_VOICES = {
    "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica", "af_kore",
    "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky", "am_adam",
    "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx",
    "am_puck", "am_santa",
}
BRITISH_VOICES = {
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable",
    "bm_george", "bm_lewis",
}
VOICES = AMERICAN_VOICES | BRITISH_VOICES


class SpeechRequest(BaseModel):
    model: str = Field(default=MODEL_NAME)
    voice: str = Field(default="bm_george")
    input: str
    response_format: str = Field(default="wav")
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


pipelines: dict[str, KPipeline] = {}
pipeline_lock = asyncio.Lock()
generation_lock = asyncio.Semaphore(1)


def configured_key() -> str:
    try:
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def require_auth(authorization: str | None) -> None:
    expected = configured_key()
    if not expected:
        return
    supplied = (
        authorization.removeprefix("Bearer ").strip()
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    if supplied != expected:
        raise HTTPException(status_code=401, detail="Kokoro bearer token required")


def pipeline_code(voice: str) -> str:
    if voice in AMERICAN_VOICES:
        return "a"
    if voice in BRITISH_VOICES:
        return "b"
    raise HTTPException(status_code=422, detail="unsupported Kokoro English voice")


async def get_pipeline(code: str) -> KPipeline:
    async with pipeline_lock:
        existing = pipelines.get(code)
        if existing is not None:
            return existing
        # Loading is blocking and downloads the small model on first start, so
        # keep it off the event loop. Both pipelines share the model cache.
        pipeline = await asyncio.to_thread(
            KPipeline,
            code,
            repo_id="hexgrad/Kokoro-82M",
            device=DEVICE,
        )
        pipelines[code] = pipeline
        return pipeline


def generate_wav(request: SpeechRequest) -> bytes:
    code = pipeline_code(request.voice)
    pipeline = pipelines[code]
    generated = pipeline(request.input, voice=request.voice, speed=request.speed)
    chunks = []
    for result in generated:
        audio = getattr(result, "audio", None)
        if audio is None:
            continue
        chunks.append(audio.detach().float().cpu().numpy())
    if not chunks:
        raise HTTPException(status_code=502, detail="Kokoro returned empty audio")
    import numpy as np

    audio = np.concatenate(chunks)
    output = BytesIO()
    sf.write(output, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return output.getvalue()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Warm the default Australian-adjacent British male voice. The American
    # pipeline is loaded lazily if a user previews an ``a*`` voice.
    await get_pipeline("b")
    yield
    pipelines.clear()


app = FastAPI(title="Pilot Kokoro TTS", version="1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok" if "b" in pipelines else "starting",
        "provider": "kokoro",
        "model": MODEL_NAME,
        "device": DEVICE,
        "sample_rate": SAMPLE_RATE,
        "voices": sorted(VOICES),
    }


@app.post("/v1/audio/speech")
async def speech(
    request: SpeechRequest,
    authorization: str | None = Header(default=None),
) -> Any:
    require_auth(authorization)
    if request.model not in {MODEL_NAME, "kokoro", "tts"}:
        raise HTTPException(status_code=422, detail="unsupported Kokoro model")
    if request.response_format != "wav":
        raise HTTPException(status_code=422, detail="Kokoro sidecar currently returns WAV")
    if not request.input.strip() or len(request.input) > MAX_INPUT_CHARS:
        raise HTTPException(status_code=422, detail="input is empty or too long")
    code = pipeline_code(request.voice)
    await get_pipeline(code)
    async with generation_lock:
        content = await asyncio.to_thread(generate_wav, request)
    from fastapi.responses import Response

    return Response(content=content, media_type="audio/wav")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
