@echo off
rem Launches ONLY the control server (dashboard + AI assistant brain at :8000).
rem The Discord bot runs separately via start_bot.bat. Keeping them as two
rem independent units means either can restart without touching the other.
rem Project root = the folder above this script (portable: works on any drive/path)
for %%I in ("%~dp0..") do set "PROJ=%%~fI"
set "PYTHONPATH=%PROJ%"
set "PYTHONIOENCODING=utf-8"
set "ANTHROPIC_API_KEY=YOUR_KEY_HERE"
set "IG_USER_ID=YOUR_IG_USER_ID"
set "IG_ACCESS_TOKEN=YOUR_KEY_HERE"
set "DISCORD_BOT_TOKEN=YOUR_KEY_HERE"
set "DISCORD_USER_ID=YOUR_DISCORD_USER_ID"
cd /d "%PROJ%"
"%PROJ%\venv\Scripts\python.exe" control_server.py >> "%PROJ%\output\control_server.log" 2>&1
