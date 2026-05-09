"""
Local TTS Service - powered by edge-tts (Microsoft Azure TTS)
Supports multiple Chinese voices. Returns audio/mpeg stream.
"""

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import edge_tts
import io

app = FastAPI(title="Poker Live TTS", version="1.0.0")

# Allow frontend dev server to call this service
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Voice presets for Chinese
VOICE_PRESETS = {
    # 女声 - 活泼自然（推荐AI-A）
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",
    # 女声 - 温柔甜美
    "xiaoyi": "zh-CN-XiaoyiNeural",
    # 男声 - 年轻活力（推荐AI-B）
    "yunxi": "zh-CN-YunxiNeural",
    # 男声 - 沉稳专业
    "yunjian": "zh-CN-YunjianNeural",
    # 男声 - 新闻播报风
    "yunyang": "zh-CN-YunyangNeural",
    # 台湾女声
    "hsiaochen": "zh-TW-HsiaoChenNeural",
    # 香港女声
    "hiumaan": "zh-HK-HiuMaanNeural",
    # 系统默认
    "system": "zh-CN-XiaoxiaoNeural",
}

# Default mapping for speakers
SPEAKER_VOICE_MAP = {
    "AI-A": "xiaoxiao",
    "AI-B": "yunxi",
    "系统": "yunyang",
}


@app.get("/")
def root():
    return {"message": "Poker Live TTS is running"}


@app.get("/voices")
def list_voices():
    """List available voice presets."""
    return JSONResponse({
        "voices": VOICE_PRESETS,
        "speaker_defaults": SPEAKER_VOICE_MAP,
    })


@app.get("/tts")
async def tts(
    text: str = Query(..., min_length=1, description="Text to synthesize"),
    voice: str = Query("xiaoxiao", description="Voice preset key"),
    speaker: str = Query(None, description="Optional speaker name for auto voice selection"),
):
    """
    Synthesize text to speech and return MP3 audio stream.
    
    - text: required, the text to speak
    - voice: optional preset key (default: xiaoxiao)
    - speaker: optional, auto-picks voice if 'AI-A', 'AI-B', or '系统'
    """
    # Auto-resolve voice from speaker if provided
    if speaker and not voice:
        voice = SPEAKER_VOICE_MAP.get(speaker, "xiaoxiao")
    
    voice_name = VOICE_PRESETS.get(voice, VOICE_PRESETS["xiaoxiao"])
    
    communicate = edge_tts.Communicate(text, voice_name)
    
    async def audio_stream():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    
    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": f'inline; filename="tts.mp3"',
            "Cache-Control": "no-cache",
        }
    )


@app.get("/tts/speak")
async def speak_line(
    text: str = Query(..., min_length=1),
    speaker: str = Query("系统", description="AI-A / AI-B / 系统"),
):
    """Convenience endpoint that auto-selects voice by speaker."""
    voice = SPEAKER_VOICE_MAP.get(speaker, "xiaoxiao")
    voice_name = VOICE_PRESETS[voice]
    
    communicate = edge_tts.Communicate(text, voice_name)
    
    async def audio_stream():
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    
    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
