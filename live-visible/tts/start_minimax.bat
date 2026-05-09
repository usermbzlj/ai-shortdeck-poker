@echo off
cd /d "%~dp0"

REM Load environment variables from .env if exists
if exist .env (
  for /f "tokens=1,2 delims==" %%a in (.env) do (
    set "%%a=%%b"
  )
)

echo [MiniMax TTS] Starting MiniMax TTS Server...
echo [MiniMax TTS] Endpoint: http://localhost:8001
echo [MiniMax TTS] Voices  : http://localhost:8001/voices
echo [MiniMax TTS] Health  : http://localhost:8001/health
echo.
.\venv\Scripts\python.exe -m uvicorn minimax_server:app --host 0.0.0.0 --port 8001
pause
