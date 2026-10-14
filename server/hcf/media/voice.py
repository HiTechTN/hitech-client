"""Voice pipelines (STT tiers + TTS), backend-agnostic.

Tiers (meme philosophie que les adapters LLM) :
  - navigateur : Web Speech API cote client (aucun appel serveur)
  - local      : faster-whisper CPU (prive, gratuit) — Darija via prompt de biais
  - gemini     : comprehension audio native (phase suivante, 501 pour l'instant)

POST /api/hc/media/transcribe {file, tier=local, lang=ar} -> {text,...}
POST /api/hc/media/speak {text, voice} -> audio/mpeg (voix ar-TN)
"""
import io
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/hc/media")

MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_TTS_CHARS = 2000
AR_TN_VOICES = ("ar-TN-HediNeural", "ar-TN-ReemNeural")

# Bias whisper toward Tunisian dialect transcriptions.
DARJA_PROMPT = ("Ahla, chneya el mochkla? El youm bech na7kiw 3al informatique, "
                "serveur, container, deploy, erreur, fichier, code, application.")

_whisper = None


def _get_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    return _whisper


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...),
                     tier: str = Form("local"),
                     lang: str = Form("ar")):
    """Speech -> text. tier=local (whisper CPU) | gemini (bientôt)."""
    tier = (tier or "local").strip().lower()
    if tier == "gemini":
        raise HTTPException(
            status_code=501,
            detail="tier gemini : compréhension audio native — phase suivante "
                   "(utilisez tier=local ou la dictée navigateur en attendant)")
    if tier != "local":
        raise HTTPException(status_code=400, detail="tier inconnu (local|gemini)")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="audio vide")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="audio trop lourd (max 25 Mo)")
    suffix = Path(file.filename or "audio.webm").suffix.lower() or ".webm"
    if suffix not in (".webm", ".mp3", ".wav", ".ogg", ".m4a", ".mp4", ".flac"):
        suffix = ".webm"
    with tempfile.TemporaryDirectory(prefix="hcf-stt-") as tmp:
        src = str(Path(tmp) / f"in{suffix}")
        Path(src).write_bytes(data)
        try:
            model = _get_whisper()
        except Exception as e:
            raise HTTPException(status_code=503,
                                detail=f"moteur vocal indisponible: {e}"[:200])
        try:
            segments, info = model.transcribe(
                src, language=(lang or "ar"), initial_prompt=DARJA_PROMPT,
                beam_size=5, vad_filter=True)
            text = " ".join(s.text.strip() for s in segments).strip()
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"transcription impossible: {e}"[:200])
    if not text:
        raise HTTPException(status_code=422, detail="aucune parole détectée")
    return {"ok": True, "tier": "local", "lang": getattr(info, "language", lang),
            "lang_prob": round(float(getattr(info, "language_probability", 0) or 0), 2),
            "text": text}


class SpeakIn(BaseModel):
    text: str
    voice: str = "ar-TN-HediNeural"


@router.post("/speak")
async def speak(body: SpeakIn):
    """Text -> Tunisian voice (edge-tts ar-TN). Returns audio/mpeg."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="texte vide")
    if len(text) > MAX_TTS_CHARS:
        raise HTTPException(status_code=400, detail="texte trop long (max 2000)")
    voice = body.voice if body.voice in AR_TN_VOICES else AR_TN_VOICES[0]
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        audio = buf.getvalue()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TTS impossible: {e}"[:200])
    if not audio:
        raise HTTPException(status_code=502, detail="TTS: aucun audio généré")
    return StreamingResponse(io.BytesIO(audio), media_type="audio/mpeg",
                             headers={"Content-Disposition": 'inline; filename="reply.mp3"'})


@router.get("/voices")
async def voices():
    return {"tts_voices": list(AR_TN_VOICES),
            "stt_tiers": ["navigateur", "local", "gemini (bientôt)"]}
