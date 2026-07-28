# setup_autostart.ps1  —  RUN ONCE AS ADMINISTRATOR
# Registers the Discord bot and control server as auto-starting, self-restarting
# scheduled tasks so they survive reboots and never silently die.
#
# HOW TO RUN:
#   Right-click Start > "Terminal (Admin)" or "PowerShell (Admin)", then:
#     powershell -ExecutionPolicy Bypass -File "D:\Ai-scripts\media_maker\scripts\setup_autostart.ps1"
#
# After this, both run at logon and restart within ~1 min if they ever stop.
# Manage them in Task Scheduler under: MediaMakerBot, MediaMakerServer.

$ErrorActionPreference = "Stop"
$scripts = "D:\Ai-scripts\media_maker\scripts"

function Register-MM($name, $bat) {
    $action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$scripts\$bat`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)     # never time out (long-running)
    Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Limited -Force | Out-Null
    Write-Host "  registered $name -> $bat"
}

Write-Host "Registering MediaMaker auto-start tasks..."
Register-MM "MediaMakerServer" "start_server.bat"
Register-MM "MediaMakerBot"    "start_bot.bat"

Write-Host "`nStarting them now..."
Start-ScheduledTask -TaskName "MediaMakerServer"
Start-Sleep 2
Start-ScheduledTask -TaskName "MediaMakerBot"

Write-Host "`nDone. Dashboard: http://localhost:8000  |  DM the Discord bot to test."
