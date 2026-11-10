@echo off
rem Aktarım'ı başlatır (Python 3.9+ gerekir: https://www.python.org/downloads/ — "Add to PATH" işaretli)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 aktarim.py %*) || (python aktarim.py %*)
pause
