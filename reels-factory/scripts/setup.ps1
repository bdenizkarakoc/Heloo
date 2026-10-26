# Reels Factory kurulumu (Windows PowerShell). Kullanım (reels-factory klasöründen):
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

function Need($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { Write-Host "X '$cmd' bulunamadi: $hint"; exit 1 }
}
Need python "Python 3.10+ kurun: winget install Python.Python.3.12"
Need ffmpeg "FFmpeg kurun: winget install Gyan.FFmpeg (sonra terminali yeniden acin)"
Need node "Node.js 22+ kurun: winget install OpenJS.NodeJS.LTS"
$major = [int]((node --version).TrimStart('v').Split('.')[0])
if ($major -lt 22) { Write-Host "X Node.js 22+ gerekli (simdiki: $major)"; exit 1 }

Write-Host "> Python bagimliliklari"; python -m pip install -r requirements.txt
Write-Host "> Node bagimliliklari (HyperFrames, GSAP)"; npm install
Write-Host "> Render tarayicisi"; npx hyperframes browser ensure
npx hyperframes telemetry disable 2>$null | Out-Null
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "> .env olusturuldu" }
python scripts/factory.py doctor
