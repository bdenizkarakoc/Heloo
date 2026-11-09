@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem TV Yansit: bilgisayar ekranini televizyona yansitir. Cift tiklayin.

where python >nul 2>nul
if errorlevel 1 (
  echo Python bulunamadi. https://www.python.org/downloads/ adresinden kurun ^("Add to PATH" isaretli^).
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 if not exist "ffmpeg.exe" if not exist "C:\ffmpeg\bin\ffmpeg.exe" (
  echo ffmpeg bulunamadi, kuruluyor ^(winget^)...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo Kurulum bitti. Bu pencereyi kapatip TV Yansit'i yeniden acin.
  pause
  exit /b 0
)

rem Windows Guvenlik Duvari: ilk calistirmada "Erisime izin ver" (Ozel aglar) deyin; TV baglanabilsin.
where pythonw >nul 2>nul
if errorlevel 1 (
  python tv_yansit.py %*
) else (
  start "" pythonw tv_yansit.py %*
)
