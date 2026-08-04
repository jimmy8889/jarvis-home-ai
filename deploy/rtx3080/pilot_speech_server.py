from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
from io import BytesIO
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from faster_whisper import WhisperModel


MODEL_NAME = os.environ.get("PILOT_STT_MODEL", "small.en").strip() or "small.en"
MODEL_ROOT = os.environ.get(
    "PILOT_STT_MODEL_ROOT", "/srv/models/faster-whisper"
).strip()
COMPUTE_TYPE = os.environ.get("PILOT_STT_COMPUTE_TYPE", "float16").strip()
MAX_AUDIO_BYTES = int(os.environ.get("PILOT_STT_MAX_AUDIO_BYTES", "1600000"))
API_KEY_FILE = Path(
    os.environ.get("PILOT_STT_API_KEY_FILE", "/etc/pilot/stt-api-key")
)

model: WhisperModel | None = None
model_lock = asyncio.Semaphore(1)


def api_key() -> str:
    try:
        return API_KEY_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def require_auth(authorization: str | None) -> None:
    expected = api_key()
    supplied = (
        authorization.removeprefix("Bearer ").strip()
        if authorization and authorization.startswith("Bearer ")
        else ""
    )
    if not expected or supplied != expected:
        raise HTTPException(status_code=401, detail="speech bearer token required")


def load_model() -> WhisperModel:
    return WhisperModel(
        MODEL_NAME,
        device="cuda",
        compute_type=COMPUTE_TYPE,
        download_root=MODEL_ROOT,
        cpu_threads=4,
        num_workers=1,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    global model
    model = await asyncio.to_thread(load_model)
    yield
    model = None


app = FastAPI(title="Pilot GPU Speech", version="1.0", lifespan=lifespan)


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "ok" if model is not None and api_key() else "starting",
        "provider": "faster-whisper",
        "model": MODEL_NAME,
        "device": "cuda",
        "compute_type": COMPUTE_TYPE,
    }


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model_name: str = Form(default="", alias="model"),
    language: str | None = None,
    response_format: str = "json",
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    require_auth(authorization)
    if model is None:
        raise HTTPException(status_code=503, detail="GPU speech model is starting")
    content = await file.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio upload is too large")
    if not content:
        raise HTTPException(status_code=422, detail="audio upload is empty")
    selected_model = model_name.strip()
    if selected_model and selected_model not in {MODEL_NAME, "whisper-1"}:
        raise HTTPException(status_code=422, detail="unsupported speech model")
    selected_language = language.split("-", 1)[0].lower() if language else None

    async with model_lock:
        try:
            segments, info = await asyncio.to_thread(
                lambda: model.transcribe(  # type: ignore[union-attr]
                    BytesIO(content),
                    language=selected_language,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                    vad_filter=True,
                    condition_on_previous_text=False,
                    without_timestamps=response_format != "verbose_json",
                )
            )
            rows: list[dict[str, Any]] = []
            text_parts: list[str] = []
            for index, segment in enumerate(segments):
                text = " ".join(segment.text.split())
                if not text:
                    continue
                text_parts.append(text)
                rows.append(
                    {
                        "id": index,
                        "start": round(float(segment.start), 3),
                        "end": round(float(segment.end), 3),
                        "text": text,
                        "avg_logprob": float(segment.avg_logprob),
                    }
                )
        except Exception as error:  # provider errors become a bounded API error
            raise HTTPException(
                status_code=502, detail=f"GPU transcription failed: {error}"
            ) from error
    text = " ".join(text_parts).strip()
    if not text:
        raise HTTPException(status_code=422, detail="no text recognized")
    result: dict[str, Any] = {
        "text": text,
        "language": getattr(info, "language", selected_language or "en"),
        "duration": float(getattr(info, "duration", 0.0) or 0.0),
    }
    if response_format == "verbose_json":
        result["segments"] = rows
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("PILOT_STT_HOST", "0.0.0.0"),
        port=int(os.environ.get("PILOT_STT_PORT", "8031")),
    )
