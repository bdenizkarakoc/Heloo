# Reels Fabrikasi - ARKA PLAN ISLEMLERINI DURDUR (Windows PowerShell)
#
# Internetten tek satirla:
#   irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/autonomous-ai-reels-factory-x82681/reels-factory/scripts/stop-app.ps1 | iex
#
# Yaptiklari: calisan uygulamayi (otomatik mod, bulut esitleme, yayin zamanlayicisi, Telegram dinleyicisi) ve
# onun baslattigi video uretimlerini kapatir; Windows acilisinda kendiliginden baslamasini kaldirir.
# Hicbir dosya silinmez. Uygulama masaustundeki "Reels Fabrikasi" kisayoluyla yine elle acilabilir.
# Acilista baslamayi geri acmak icin: reels-factory klasorunde  scripts\install-app.ps1 -Startup
$ErrorActionPreference = "Continue"
$Port = 8765
$stopped = 0

# 1) Uygulama sunucusu ve alt islemleri (render, ffmpeg, claude)
$procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -and $_.CommandLine -match "app[\\/]server\.py" }
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$ids = @(@($procs | ForEach-Object { $_.ProcessId }) + @($conn | ForEach-Object { $_.OwningProcess }) | Sort-Object -Unique)
foreach ($id in $ids) {
  # once alt islemler (ornegin video render), sonra uygulamanin kendisi
  Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $stopped++ }
  Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; $stopped++
}
if ($ids.Count) { Write-Host "OK Reels Fabrikasi durduruldu ($stopped islem)." -ForegroundColor Green }
else { Write-Host "Calisan Reels Fabrikasi bulunamadi." }

# 2) Windows acilisinda baslatma kisayolu
$startLnk = Join-Path ([Environment]::GetFolderPath("Startup")) "Reels Fabrikasi (arka plan).lnk"
if (Test-Path $startLnk) { Remove-Item $startLnk -Force; Write-Host "OK Windows acilisinda baslama kapatildi." -ForegroundColor Green }
else { Write-Host "Acilista baslatma zaten kapali." }

Write-Host "Not: Buluttaki zamanlanmis gorev (gunde 2 video) bilgisayardan bagimsizdir; onu claude.ai'dan durdurabilirsiniz."
