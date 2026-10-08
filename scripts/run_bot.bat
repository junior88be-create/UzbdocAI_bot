@echo off
rem Runs the bot forever: if it exits or crashes (e.g. Postgres not up yet right
rem after a reboot), wait 10 seconds and start it again. Output goes to bot.log.
cd /d "%~dp0.."
:loop
".venv\Scripts\python.exe" -m app.main >> bot.log 2>&1
echo [%date% %time%] bot exited - restarting in 10s >> bot.log
ping -n 11 127.0.0.1 >nul
goto loop
