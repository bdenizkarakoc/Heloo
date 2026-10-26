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
$folderLnk = Join-Path $desktop "Reels Videolari.lnk"
$cloudDir = Join-Path $root "output\cloud"

$kesimDir = Join-Path $desktop "kesim"
$kesimLnk = Join-Path $desktop "Kesim.lnk"
$ready = "Haz" + [char]0x0131 + "r"

if ($Remove) {
  Remove-Item $deskLnk, $startLnk, $folderLnk, $kesimLnk, (Join-Path $kesimDir "Kesim.lnk") -ErrorAction SilentlyContinue
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

# Kesim: sade montaj penceresi. Masaustu\kesim klasorune baslatici + "Montaja at" / "Hazir" klasorleri.
# Klasordeki mevcut dosyalara (or. eski Kesim.exe) dokunulmaz.
New-Item -ItemType Directory -Force -Path $kesimDir, (Join-Path $kesimDir "Montaja at"), (Join-Path $kesimDir $ready) | Out-Null
foreach ($path in @((Join-Path $kesimDir "Kesim.lnk"), $kesimLnk)) {
  $k = $shell.CreateShortcut($path)
  $k.TargetPath = $pyw
  $k.Arguments = "`"$server`" --open --page kesim"
  $k.WorkingDirectory = $root
  $k.Description = "Kesim: birak, montajlansin"
  $k.Save()
}
Write-Host "Kesim: $kesimDir (Kesim.lnk, 'Montaja at', '$ready')"

# Buluttan inen videolarin klasoru (uygulama 30 dakikada bir doldurur)
New-Item -ItemType Directory -Force -Path $cloudDir | Out-Null
$f = $shell.CreateShortcut($folderLnk)
$f.TargetPath = $cloudDir
$f.Description = "Buluttan gelen Reels videolari"
$f.Save()
Write-Host "Video klasoru kisayolu: $folderLnk"

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
