# Reels Fabrikasi guncelleme (Windows). Kullanim (reels-factory klasorunden):
#   powershell -ExecutionPolicy Bypass -File scripts\update.ps1
# Son kodu GitHub'dan ceker, bagimliliklari tamamlar, kisayollari yeniler ve uygulamayi yeniden baslatir.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$branch = "claude/autonomous-ai-reels-factory-x82681"

Write-Host "> Son surum indiriliyor"
git fetch origin $branch
git checkout $branch
git pull --ff-only origin $branch

Write-Host "> Bagimliliklar"
python -m pip install -q -r requirements.txt
npm install --silent

# Calisan uygulamayi kapat (eski kodu tutmasin)
$conn = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
if ($conn) {
  Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  Write-Host "> Eski uygulama kapatildi"
}

# Kisayollari yenile ve uygulamayi ac (install-app uygulamayi da baslatir)
powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "install-app.ps1") -Startup
