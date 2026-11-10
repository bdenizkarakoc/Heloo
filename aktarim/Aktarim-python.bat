@echo off
rem Python surumu (istege bagli)
cd /d "%~dp0"
where py >nul 2>nul && (py -3 aktarim.py %*) || (python aktarim.py %*)
pause
