# Reels Fabrikasi: masaustu kisayolu ve (istege bagli) Windows acilisinda otomatik baslatma.
# Kullanim (reels-factory klasorunden):
#   powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1            # masaustu kisayolu
#   powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1 -Startup   # + acilista arka planda baslat
#   powershell -ExecutionPolicy Bypass -File scripts\install-app.ps1 -Remove    # kisayollari kaldir
param([switch]$Startup, [switch]$Remove)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$server = Join-Path $root "app\server.py"
$desktop = [Environment]::GetFolderPath("Desktop")
$startupDir = [Environment]::GetFolderPath("Startup")
$deskLnk = Join-Path $desktop "Reels Fabrikasi.lnk"
$startLnk = Join-Path $startupDir "Reels Fabrikasi (arka plan).lnk"

if ($Remove) {
  Remove-Item $deskLnk, $startLnk -ErrorAction SilentlyContinue
  Write-Host "Kisayollar kaldirildi."; exit 0
}

# pythonw: konsol penceresi acmadan calisir
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command python -ErrorAction Stop).Source }

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($deskLnk)
$lnk.TargetPath = $pyw
$lnk.Arguments = "`"$server`" --open"
$lnk.WorkingDirectory = $root
$lnk.Description = "Reels Fabrikasi kontrol paneli"
$lnk.Save()
Write-Host "Masaustu kisayolu: $deskLnk"

if ($Startup) {
  $s = $shell.CreateShortcut($startLnk)
  $s.TargetPath = $pyw
  $s.Arguments = "`"$server`""
  $s.WorkingDirectory = $root
  $s.WindowStyle = 7
  $s.Description = "Reels Fabrikasi arka plan (otomatik mod)"
  $s.Save()
  Write-Host "Windows acilisinda arka planda baslayacak: $startLnk"
}

Start-Process $pyw -ArgumentList "`"$server`" --open" -WorkingDirectory $root
Write-Host "Uygulama acildi: http://127.0.0.1:8765/"
