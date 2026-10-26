@echo off
chcp 65001 >nul
title Otonom AI Reels Fabrikasi
set "RF=%USERPROFILE%\Documents\Heloo\reels-factory"
if not exist "%RF%\scripts\factory.py" set "RF=%USERPROFILE%\OneDrive\Documents\Heloo\reels-factory"
if not exist "%RF%\scripts\factory.py" set "RF=%USERPROFILE%\OneDrive\Belgeler\Heloo\reels-factory"
if not exist "%RF%\scripts\factory.py" (
  echo Reels Fabrikasi klasoru bulunamadi:
  echo   %USERPROFILE%\Documents\Heloo\reels-factory
  pause
  exit /b 1
)
cd /d "%RF%"

:menu
cls
echo ==========================================
echo        OTONOM AI REELS FABRIKASI
echo ==========================================
echo   1) Ortam denetimi (doctor)
echo   2) Otonom video uret (Claude API anahtari gerekir)
echo   3) Gorev durumlari
echo   4) Cikti klasorunu ac (videolar)
echo   5) Bu klasorde PowerShell ac
echo   6) Guncelle (git pull)
echo   0) Cikis
echo.
set "c="
set /p c=Secimin: 
if "%c%"=="1" goto doctor
if "%c%"=="2" goto run
if "%c%"=="3" goto status
if "%c%"=="4" goto out
if "%c%"=="5" goto ps
if "%c%"=="6" goto pull
if "%c%"=="0" exit /b 0
goto menu

:doctor
python scripts\factory.py doctor
pause
goto menu

:run
set "cat="
set "n=1"
set /p cat=Kategori (bos birak = otomatik): 
set /p n=Kac video? [1]: 
if "%cat%"=="" (
  python scripts\factory.py run --count %n%
) else (
  python scripts\factory.py run --category %cat% --count %n%
)
pause
goto menu

:status
python scripts\factory.py status
pause
goto menu

:out
if not exist "output\videos" mkdir "output\videos"
start "" explorer "%RF%\output\videos"
goto menu

:ps
start "" powershell -NoExit -Command "Set-Location '%RF%'"
goto menu

:pull
git pull
pause
goto menu
