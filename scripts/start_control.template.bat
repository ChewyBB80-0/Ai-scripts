@echo off
rem Starts the ParkourFlux control server (dashboard + AI assistant).
rem Open http://localhost:8000 in a browser once this is running.
set "PROJ=D:\Ai-scripts\media_maker"
set "FFMPEG_DIR=C:\Users\Krish\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
set "PATH=%PATH%;%FFMPEG_DIR%"
set "PYTHONPATH=%PROJ%"
set "ANTHROPIC_API_KEY=YOUR_KEY_HERE"
set "IG_USER_ID=YOUR_IG_USER_ID"
set "IG_ACCESS_TOKEN=YOUR_KEY_HERE"
set "DISCORD_BOT_TOKEN=YOUR_KEY_HERE"
set "DISCORD_USER_ID=YOUR_DISCORD_USER_ID"
cd /d "%PROJ%"
start "" /b "%PROJ%\venv\Scripts\python.exe" discord_bot.py
"%PROJ%\venv\Scripts\python.exe" control_server.py
