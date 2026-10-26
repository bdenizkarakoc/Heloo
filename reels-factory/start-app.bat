@echo off
rem Reels Fabrikasi uygulamasini baslatir ve tarayicida acar.
cd /d "%~dp0"
python app\server.py --open
if errorlevel 1 pause
