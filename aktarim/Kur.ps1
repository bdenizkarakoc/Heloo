# Aktarim kurulumu: dosyalari GitHub'dan indirir, masaustune kisayol koyar, programi baslatir.
# Kullanim (PowerShell):  irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/eloquent-rubin-wc5t2q/aktarim/Kur.ps1 | iex
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$base = 'https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/eloquent-rubin-wc5t2q/aktarim'
$dest = Join-Path $env:LOCALAPPDATA 'Aktarim'
$files = @('Aktarim.ps1', 'Aktarim.bat', 'README.md', 'web/index.html', 'web/app.js', 'web/style.css',
           'web/manifest.webmanifest', 'web/icon.svg')
New-Item -ItemType Directory -Force -Path (Join-Path $dest 'web') | Out-Null
foreach ($f in $files) {
  Write-Host "indiriliyor: $f"
  Invoke-WebRequest -UseBasicParsing -Uri "$base/$f" -OutFile (Join-Path $dest ($f -replace '/', '\'))
}
Get-ChildItem -LiteralPath $dest -Recurse -File | Unblock-File

$name = 'Aktar' + [char]0x0131 + 'm'
$desktop = [Environment]::GetFolderPath('Desktop')
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop "$name.lnk"))
$lnk.TargetPath = 'powershell.exe'
$lnk.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $dest 'Aktarim.ps1') + '"'
$lnk.WorkingDirectory = $dest
$lnk.IconLocation = 'shell32.dll,146'
$lnk.Save()

Write-Host ''
Write-Host "Kuruldu: $dest" -ForegroundColor Green
Write-Host "Masaustunde '$name' kisayolu olusturuldu. Program simdi aciliyor..." -ForegroundColor Green
Start-Process powershell.exe -WorkingDirectory $dest -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $dest 'Aktarim.ps1') + '"')
