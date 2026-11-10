@echo off
rem Aktarim: PowerShell ile baslatir (Python gerekmez)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Aktarim.ps1" %*
if errorlevel 1 pause
