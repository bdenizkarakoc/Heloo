@echo off
setlocal
title Kesim + SelfEdit kurulumu
cd /d "%~dp0"
set "ZIP=%~dp0..\Kesim_Windows.zip"
set "DST=%~dp0..\Kesim_SelfEdit"
set "APP=%DST%\resources\app"

echo.
echo   Kesim + SelfEdit kurulumu
echo   -------------------------
if not exist "%ZIP%" goto nozip
if exist "%DST%\Kesim.exe" goto patch

echo   [1/3] Kesim_Windows.zip aciliyor, biraz surebilir...
mkdir "%DST%" 2>nul
tar -xf "%ZIP%" -C "%DST%"
if errorlevel 1 (
  echo   tar basarisiz, PowerShell ile deneniyor...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%DST%' -Force"
)
if not exist "%DST%\Kesim.exe" goto fail

:patch
echo   [2/3] Orijinal dosyalar yedekleniyor...
if not exist "%APP%\main.js.orig" copy /y "%APP%\main.js" "%APP%\main.js.orig" >nul
if not exist "%APP%\index.html.orig" copy /y "%APP%\index.html" "%APP%\index.html.orig" >nul
echo   [3/3] SelfEdit dosyalari kopyalaniyor...
xcopy "%~dp0app\*" "%APP%\" /E /I /Y /Q >nul
if errorlevel 1 goto fail

echo.
echo   TAMAM. Kesim_SelfEdit klasorundeki Kesim.exe artik kendini gelistiren surumdur.
echo   Kesim icinde sol panelde "Gelisim" sekmesine bak.
echo.
set /p R="  Simdi baslatilsin mi? (E/H): "
if /i "%R%"=="E" start "" "%DST%\Kesim.exe"
goto end

:nozip
echo.
echo   HATA: Kesim_Windows.zip bulunamadi.
echo   Beklenen yer: %ZIP%
echo   Bu klasoru (Kesim_SelfEdit_Yama), Kesim_Windows.zip ile ayni klasore koy.
goto end

:fail
echo.
echo   HATA: Kurulum tamamlanamadi. Kesim_SelfEdit klasorunu silip tekrar dene.

:end
echo.
pause
