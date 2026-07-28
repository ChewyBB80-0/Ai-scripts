@echo off
rem Media Maker daily run -- called at logon (Startup folder) or manually.
rem Generates one video into output\pending_review\ (REVIEW_MODE) and
rem refreshes output\channel_stats.json for the ops dashboard.

set "PROJ=D:\Ai-scripts\media_maker"
set "FFMPEG_DIR=C:\Users\Krish\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
set "PATH=%PATH%;%FFMPEG_DIR%"
set "PYTHONPATH=%PROJ%\scripts"
set "DISCORD_BOT_TOKEN=YOUR_KEY_HERE"
set "DISCORD_USER_ID=YOUR_DISCORD_USER_ID"

cd /d "%PROJ%"
echo [%date% %time%] daily run started >> output\daily_run.log

"%PROJ%\venv\Scripts\python.exe" bot.py >> output\daily_run.log 2>&1
"%PROJ%\venv\Scripts\python.exe" scripts\channel_stats.py >> output\daily_run.log 2>&1
"%PROJ%\venv\Scripts\python.exe" scripts\ig_stats.py >> output\daily_run.log 2>&1
"%PROJ%\venv\Scripts\python.exe" scripts\gen_dashboard.py >> output\daily_run.log 2>&1
"%PROJ%\venv\Scripts\python.exe" scripts\discord_notify.py report >> output\daily_run.log 2>&1

echo [%date% %time%] daily run finished >> output\daily_run.log

