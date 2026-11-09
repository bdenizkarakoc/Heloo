@echo off
rem Heloo TV - RTX 4K IPTV oynatici. Ilk calistirmada kurulumu yapar (install.ps1).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Heloo TV ilk kez kuruluyor...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
  if errorlevel 1 (
    echo Kurulum basarisiz. Yukaridaki hatayi okuyun.
    pause
    exit /b 1
  )
)
if not exist "bin\libmpv-2.dll" ".venv\Scripts\python.exe" -m helootv.tools.fetch_mpv
start "" ".venv\Scripts\pythonw.exe" -m helootv %*
