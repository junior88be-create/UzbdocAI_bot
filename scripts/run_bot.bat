@echo off
rem Document AI Bot - agar to'xtasa, 10 soniyadan so'ng o'zi qayta ishga tushadi.
cd /d "%~dp0.."
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
:loop
echo [%date% %time%] Bot ishga tushmoqda >> bot.log
".venv\Scripts\python.exe" -m app.main >> bot.log 2>&1
echo [%date% %time%] Bot to'xtadi, 10 soniyadan so'ng qayta ishga tushadi >> bot.log
ping -n 11 127.0.0.1 >nul
goto loop
