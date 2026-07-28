@echo off
rem Launches ONLY the Discord bot (two-way DM chat -> control server).
rem Run standalone or via the MediaMakerBot scheduled task (at logon).
rem Logs gateway/ready status to output\discord_bot.log so you can verify it.
rem Project root = the folder above this script (portable: works on any drive/path)
for %%I in ("%~dp0..") do set "PROJ=%%~fI"
set "DISCORD_BOT_TOKEN=YOUR_KEY_HERE"
set "DISCORD_USER_ID=YOUR_DISCORD_USER_ID"
set "PYTHONIOENCODING=utf-8"
cd /d "%PROJ%"
"%PROJ%\venv\Scripts\python.exe" discord_bot.py >> "%PROJ%\output\discord_bot.log" 2>&1
