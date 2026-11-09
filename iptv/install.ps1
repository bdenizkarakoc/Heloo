# Heloo TV kurulumu (Windows 10/11):
#   1) Python 3.10+ bulur (yoksa winget ile kurmayi onerir)
#   2) .venv sanal ortamini olusturur, PySide6 + python-mpv kurar
#   3) GitHub'dan en guncel mpv'yi indirir (libmpv-2.dll + mpv.exe; zhongfly/mpv-winbuild, RTX VSR/HDR destekli)
#   4) Masaustu ve Baslat menusu kisayolu olusturur
# Kullanim (iptv klasorunden):
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   powershell -ExecutionPolicy Bypass -File install.ps1 -Force        # sanal ortami ve mpv'yi yeniden kur
#   powershell -ExecutionPolicy Bypass -File install.ps1 -NoShortcut
param([switch]$Force, [switch]$NoShortcut)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$root = $PSScriptRoot
Set-Location -LiteralPath $root

function Say($m) { Write-Host ">> $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

function Test-Python([string]$exe, [string[]]$pre) {
  try {
    $v = & $exe @pre -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $v -and ([version]$v -ge [version]"3.10")) { return $true }
  } catch { }
  return $false
}

function Find-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    foreach ($v in @("-3.13", "-3.12", "-3.11", "-3.10", "-3")) {
      if (Test-Python "py" @($v)) { return @{ Exe = "py"; Pre = @($v) } }
    }
  }
  foreach ($n in @("python", "python3")) {
    $cmd = Get-Command $n -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source -notlike "*WindowsApps*" -and (Test-Python $cmd.Source @())) {
      return @{ Exe = $cmd.Source; Pre = @() }
    }
  }
  return $null
}

# 1) Python
Say "Python araniyor..."
$py = Find-Python
if (-not $py) {
  Warn "Python 3.10 veya ustu bulunamadi."
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    $ans = Read-Host "winget ile Python 3.12 kurulsun mu? (E/H)"
    if ($ans -match '^[EeYy]') {
      winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
      $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
      $py = Find-Python
    }
  }
  if (-not $py) { throw "Python 3.10+ kurun (https://www.python.org/downloads/ - 'Add python.exe to PATH' isaretli) ve tekrar calistirin." }
}
Ok ("Python: " + (& $py.Exe @($py.Pre) -c "import sys; print(sys.version.split()[0])"))

# 2) Sanal ortam + paketler
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if ($Force -and (Test-Path (Join-Path $root ".venv"))) {
  Say "Eski sanal ortam siliniyor..."
  Remove-Item -Recurse -Force (Join-Path $root ".venv")
}
if (-not (Test-Path $venvPy)) {
  Say "Sanal ortam olusturuluyor (.venv)..."
  & $py.Exe @($py.Pre) -m venv (Join-Path $root ".venv")
  if ($LASTEXITCODE -ne 0) { throw "Sanal ortam olusturulamadi." }
}
Say "Paketler kuruluyor (PySide6, python-mpv)..."
& $venvPy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $venvPy -m pip install -r (Join-Path $root "requirements.txt") --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "Paketler kurulamadi (internet baglantisini denetleyin)." }
Ok "Paketler hazir"

# 3) mpv (GitHub)
Say "mpv (libmpv-2.dll + mpv.exe) GitHub'dan indiriliyor..."
$fa = @("-m", "helootv.tools.fetch_mpv")
if ($Force) { $fa += "--force" }
& $venvPy @fa
if ($LASTEXITCODE -ne 0) { throw "mpv indirilemedi. Uygulamada Ayarlar > Sistem > 'mpv bilesenlerini indir' ile tekrar deneyebilirsiniz." }
Ok "mpv hazir"

# 4) Kisayollar
if (-not $NoShortcut) {
  $ico = Join-Path $root "bin\heloo-tv.ico"
  & $venvPy -m helootv --write-icon $ico | Out-Null
  $ws = New-Object -ComObject WScript.Shell
  $targets = @(
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "Heloo TV.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Programs")) "Heloo TV.lnk")
  )
  foreach ($t in $targets) {
    $lnk = $ws.CreateShortcut($t)
    $lnk.TargetPath = Join-Path $root ".venv\Scripts\pythonw.exe"
    $lnk.Arguments = "-m helootv"
    $lnk.WorkingDirectory = $root
    if (Test-Path $ico) { $lnk.IconLocation = $ico }
    $lnk.Description = "Heloo TV - NVIDIA RTX 4K IPTV oynatici"
    $lnk.Save()
  }
  Ok "Masaustu ve Baslat menusu kisayolu: Heloo TV"
}

# 5) NVIDIA denetimi
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
  $gpuInfo = & $smi.Source --query-gpu=name,driver_version --format=csv,noheader 2>$null
  if ($gpuInfo) { Ok "Ekran karti: $gpuInfo" }
} else {
  Warn "nvidia-smi bulunamadi: RTX Video Super Resolution icin NVIDIA RTX kart ve guncel surucu gerekir."
}
Write-Host ""
Write-Host "Kurulum tamam. 'Heloo TV' kisayoluyla ya da 'Heloo TV.bat' ile acin." -ForegroundColor Green
Write-Host "RTX 4K icin: NVIDIA App > Sistem > Video > RTX Video Enhancement > Super Resolution: ACIK (kalite: Otomatik ya da 4)." -ForegroundColor Green
Write-Host "HDR ekranda istege bagli: ayni yerde 'High Dynamic Range' + Windows HDR acik; uygulamada Ayarlar > RTX Video HDR." -ForegroundColor Green
