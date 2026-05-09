@echo off
cd /d "%~dp0"
echo [TTS] Starting Poker Live TTS Server...
echo [TTS] Endpoint: http://localhost:8000
echo [TTS] Voices  : http://localhost:8000/voices
echo.
.\venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000
pause
