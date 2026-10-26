# Kesim (masaustu video editoru) + Reels Fabrikasi baglantisi.
# Kesim.exe'yi bulur, resources\app klasorunu BIR KEZ yedekler (app.fabrika-yedek) ve kesim-app dosyalarini kopyalar:
#   - Fabrika sekmesi (otomatik montaj, "su videoyu yap", altyazi, ses temizleme, fabrika stili, AI asistan)
#   - SelfEdit (kendini gelistiren efekt motoru) korunur
#   - Claude/MCP icin yerel kontrol kapisi
# Kullanim (reels-factory klasorunden):
#   powershell -ExecutionPolicy Bypass -File scripts\install-kesim.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-kesim.ps1 -KesimPath "D:\Kesim\Kesim.exe"
#   powershell -ExecutionPolicy Bypass -File scripts\install-kesim.ps1 -Restore     # yedegi geri yukle
param([string]$KesimPath = "", [switch]$Restore)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$src = Join-Path $root "kesim-app"
$desktop = [Environment]::GetFolderPath("Desktop")
$downloads = Join-Path $env:USERPROFILE "Downloads"

function Ok($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }

# 1) Kesim.exe adaylari
$cands = @()
if ($KesimPath) { $cands += $KesimPath }
$cands += @(
  (Join-Path $desktop "kesim\Kesim.exe"),
  (Join-Path $env:USERPROFILE "OneDrive\Desktop\kesim\Kesim.exe"),
  (Join-Path $downloads "Kesim_SelfEdit\Kesim.exe"),
  (Join-Path $downloads "Kesim_Windows\Kesim.exe")
)
$exes = @($cands | Where-Object { $_ -and (Test-Path $_) } | ForEach-Object { (Resolve-Path $_).Path } | Select-Object -Unique)
if (-not $exes.Count) {
  Warn "Kesim.exe bulunamadi. Kesim'i Masaustu\kesim klasorune koyup tekrar calistirin ya da -KesimPath verin."
  Warn "Simdilik tarayicidaki sade Kesim (Masaustu > Kesim) kullanilir."
  exit 0
}

# pythonw: fabrika arka planda penceresiz baslasin
$pyw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pyw) { $pyw = (Get-Command python -ErrorAction SilentlyContinue).Source }
$utf8 = New-Object System.Text.UTF8Encoding $false

foreach ($exe in $exes) {
  $res = Join-Path (Split-Path $exe) "resources"
  $app = Join-Path $res "app"
  $asar = Join-Path $res "app.asar"
  $bak = Join-Path $res "app.fabrika-yedek"
  Write-Host ""
  Write-Host "Kesim: $exe"

  if ($Restore) {
    if (Test-Path $bak) {
      if (Test-Path $app) { Remove-Item $app -Recurse -Force }
      Copy-Item $bak $app -Recurse
      Ok "yedek geri yuklendi"
    } else { Warn "yedek yok" }
    continue
  }

  if (-not (Test-Path $app) -and (Test-Path $asar)) {
    # Paketli (asar) surum: klasore acilir, asar yedek adiyla kenara alinir
    Write-Host "  app.asar aciliyor..."
    & npx --yes @electron/asar extract $asar $app
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $app "index.html"))) { Warn "app.asar acilamadi; bu kurulum atlandi."; continue }
    Rename-Item $asar "app.asar.fabrika-yedek"
    Ok "app.asar klasore acildi (asar yedeklendi)"
  }
  if (-not (Test-Path (Join-Path $app "index.html"))) { Warn "resources\app\index.html yok; bu bir Kesim kurulumu gibi gorunmuyor, atlandi."; continue }

  if (-not (Test-Path $bak)) { Copy-Item $app $bak -Recurse; Ok "ozgun dosyalar yedeklendi: $bak" }
  else { Ok "yedek zaten var (ilk kurulumdaki hali korunuyor)" }

  # robocopy: alt klasorleri (selfedit, fabrika) ic ice kopyalamadan birlestirir; 8'den kucuk cikis kodu basaridir
  robocopy $src $app /E /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { Warn "dosyalar kopyalanamadi (robocopy $LASTEXITCODE)"; continue }
  $cfg = @{ root = $root; python = $pyw; port = 8765 } | ConvertTo-Json
  [IO.File]::WriteAllText((Join-Path $app "fabrika\config.json"), $cfg, $utf8)
  Ok "Fabrika sekmesi + SelfEdit + Claude kontrol kapisi kuruldu"
}

if (-not $Restore) {
  # Masaustu kisayolu: Kesim artik masaustu programi
  $main = $exes[0]
  $shell = New-Object -ComObject WScript.Shell
  foreach ($lnkPath in @((Join-Path $desktop "Kesim.lnk"), (Join-Path $desktop "kesim\Kesim.lnk"))) {
    if ((Split-Path $lnkPath) -eq (Split-Path $main)) { if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force }; continue }
    $k = $shell.CreateShortcut($lnkPath)
    $k.TargetPath = $main
    $k.WorkingDirectory = Split-Path $main
    $k.IconLocation = "$main,0"
    $k.Description = "Kesim + Reels Fabrikasi"
    $k.Save()
  }
  Ok "Masaustu > Kesim kisayolu: $main"
  if (Get-Process -Name Kesim -ErrorAction SilentlyContinue) { Warn "Kesim acik: degisikliklerin gelmesi icin Kesim'i kapatip yeniden acin." }
  Write-Host ""
  Write-Host "Kesim'de sol panelde 'Fabrika' sekmesine bakin. Geri almak icin: scripts\install-kesim.ps1 -Restore"
}
