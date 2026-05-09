"""
MiniMax TTS Service - FastAPI wrapper for MiniMax Speech API
Docs: https://platform.minimax.io/docs/api-reference/speech-t2a-http

Requires:
  MINIMAX_API_KEY  - Your MiniMax API key
  MINIMAX_GROUP_ID - Your MiniMax Group ID
"""

import os
import httpx
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Poker Live TTS - MiniMax", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MINIMAX_API_KEY = os.environ.get("MINIMAX_API_KEY", "")
MINIMAX_GROUP_ID = os.environ.get("MINIMAX_GROUP_ID", "")
MINIMAX_BASE_URL = os.environ.get("MINIMAX_BASE_URL", "https://api.minimax.io/v1/t2a_v2")
DEFAULT_MODEL = os.environ.get("MINIMAX_MODEL", "speech-2.8-hd")

# 中文预设音色（对应项目角色）
VOICE_PRESETS = {
    "AI-A": "Chinese (Mandarin)_Crisp_Girl",      # 女声，清爽少女
    "AI-B": "Chinese (Mandarin)_Pure-hearted_Boy", # 男声，纯真少年
    "系统": "Chinese (Mandarin)_Male_Announcer",   # 男声，播音员
}

ALL_VOICES = {
    "crisp_girl": "Chinese (Mandarin)_Crisp_Girl",
    "pure_boy": "Chinese (Mandarin)_Pure-hearted_Boy",
    "soft_girl": "Chinese (Mandarin)_Soft_Girl",
    "lyrical": "Chinese (Mandarin)_Lyrical_Voice",
    "gentleman": "Chinese (Mandarin)_Gentleman",
    "sweet_lady": "Chinese (Mandarin)_Sweet_Lady",
    "warm_girl": "Chinese (Mandarin)_Warm_Girl",
    "announcer": "Chinese (Mandarin)_Male_Announcer",
    "radio_host": "Chinese (Mandarin)_Radio_Host",
    "wise_woman": "Chinese (Mandarin)_Wise_Women",
    "gentle_youth": "Chinese (Mandarin)_Gentle_Youth",
}


def _voice_for(speaker: str, voice_key: str = None) -> str:
    if voice_key and voice_key in ALL_VOICES:
        return ALL_VOICES[voice_key]
    return VOICE_PRESETS.get(speaker, ALL_VOICES["crisp_girl"])


@app.get("/")
def root():
    return {"message": "MiniMax TTS is running", "model": DEFAULT_MODEL}


@app.get("/voices")
def list_voices():
    return JSONResponse({
        "provider": "minimax",
        "model": DEFAULT_MODEL,
        "voices": ALL_VOICES,
        "speaker_defaults": VOICE_PRESETS,
    })


@app.get("/health")
def health():
    ok = bool(MINIMAX_API_KEY and MINIMAX_GROUP_ID)
    return {"ready": ok, "api_key_set": bool(MINIMAX_API_KEY), "group_id_set": bool(MINIMAX_GROUP_ID)}


@app.get("/tts")
async def tts(
    text: str = Query(..., min_length=1, description="Text to synthesize"),
    speaker: str = Query("系统", description="Speaker name for auto voice selection"),
    voice: str = Query(None, description="Optional voice preset key"),
    speed: float = Query(1.0, ge=0.5, le=2.0),
    vol: float = Query(1.0, ge=0.0, le=10.0),
    pitch: int = Query(0, ge=-12, le=12),
):
    """
    Synthesize text to speech using MiniMax API and return MP3 audio.
    """
    if not MINIMAX_API_KEY or not MINIMAX_GROUP_ID:
        return JSONResponse(
            {"error": "MiniMax API key or Group ID not configured. Set MINIMAX_API_KEY and MINIMAX_GROUP_ID env vars."},
            status_code=503,
        )

    voice_id = _voice_for(speaker, voice)

    payload = {
        "model": DEFAULT_MODEL,
        "text": text,
        "stream": False,
        "output_format": "hex",
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }

    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{MINIMAX_BASE_URL}?GroupId={MINIMAX_GROUP_ID}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, json=payload)

    if resp.status_code != 200:
        return JSONResponse(
            {"error": f"MiniMax API returned {resp.status_code}", "detail": resp.text},
            status_code=502,
        )

    data = resp.json()
    base_resp = data.get("base_resp", {})
    if base_resp.get("status_code", 0) != 0:
        return JSONResponse(
            {"error": base_resp.get("status_msg", "MiniMax API error"), "code": base_resp.get("status_code")},
            status_code=502,
        )

    audio_hex = data.get("data", {}).get("audio")
    if not audio_hex:
        return JSONResponse({"error": "No audio returned from MiniMax"}, status_code=502)

    audio_bytes = bytes.fromhex(audio_hex)

    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="tts.mp3"'},
    )


@app.get("/tts/speak")
async def speak_line(
    text: str = Query(..., min_length=1),
    speaker: str = Query("系统", description="AI-A / AI-B / 系统"),
):
    """Convenience endpoint that auto-selects voice by speaker."""
    return await tts(text=text, speaker=speaker)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
