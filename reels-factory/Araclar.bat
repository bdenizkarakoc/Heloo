@echo off
rem Araclar uygulamasini kendi penceresinde acar (Fabrika calismasa da).
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  python app\araclar_app.py
  if errorlevel 1 pause
) else (
  start "" pythonw app\araclar_app.py
)
