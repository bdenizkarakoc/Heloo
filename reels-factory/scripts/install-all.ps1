# Reels Fabrikasi - TEK ADIMDA KURULUM / GUNCELLEME (Windows 10/11, PowerShell)
#
# Internetten tek satirla:
#   irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/autonomous-ai-reels-factory-x82681/reels-factory/scripts/install-all.ps1 | iex
# veya indirilen dosyayla:
#   powershell -ExecutionPolicy Bypass -File install-all.ps1
#
# Yaptiklari: Git/Python/FFmpeg/Node.js (eksikse winget ile) -> kodu indirir veya gunceller -> Python ve Node
# paketleri -> render tarayicisi -> ses motoru (kendi sesin icin, ~250 MB) -> Claude Code (kurulum + giris) ->
# masaustu kisayollari + Windows acilisinda baslatma -> uygulamayi acar. Tekrar calistirmak guvenlidir
# (guncelleme yapar; .env, videolar, sesler, kanallar silinmez).
#
# Secenekler (ortam degiskeni, komuttan once):  $env:RF_DIR="C:\Reels"; $env:RF_NO_VOICE=1; $env:RF_NO_CLAUDE=1
$Dir = if ($env:RF_DIR) { $env:RF_DIR } else { Join-Path ([Environment]::GetFolderPath("MyDocuments")) "Heloo" }
$NoVoice = [bool]$env:RF_NO_VOICE
$NoClaude = [bool]$env:RF_NO_CLAUDE
# Windows PowerShell 5.1'de git gibi programlarin normal stderr ciktisi "Stop" ile hata sanilir; cikis kodlarina bakilir.
$ErrorActionPreference = "Continue"
$Repo = "https://github.com/bdenizkarakoc/Heloo.git"
$Branch = "claude/autonomous-ai-reels-factory-x82681"
$Port = 8765

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Yellow }
function Ok($t) { Write-Host "    OK $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    ! $t" -ForegroundColor DarkYellow }
function Fail($t) { Write-Host ""; Write-Host "X $t" -ForegroundColor Red; throw "Kurulum durdu." }
function Has($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function RefreshPath {
  $m = [Environment]::GetEnvironmentVariable("Path", "Machine"); $u = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = "$m;$u;$env:USERPROFILE\.local\bin"
}
function WingetGet($id, $name) {
  if (-not (Has winget)) { Fail "$name bulunamadi ve winget yok. $name'i elle kurun, sonra bu komutu tekrar calistirin." }
  Write-Host "    $name kuruluyor (winget)..."
  winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
  RefreshPath
}
function PythonOk {
  if (-not (Has python)) { return $false }
  try { $v = & python -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null; return ([int]$v -ge 310) } catch { return $false }
}

Write-Host "Reels Fabrikasi kurulumu / guncellemesi" -ForegroundColor Cyan
Write-Host "Klasor: $Dir"

# ---------------------------------------------------------------- 1. Gereksinimler
Step "Gereksinimler (Git, Python, FFmpeg, Node.js)"
RefreshPath
if (-not (Has git)) { WingetGet "Git.Git" "Git" }
if (-not (PythonOk)) { WingetGet "Python.Python.3.12" "Python 3.12" }
if (-not (Has ffmpeg)) { WingetGet "Gyan.FFmpeg" "FFmpeg" }
$nodeOk = $false
if (Has node) { $nodeOk = ([int]((node --version).TrimStart('v').Split('.')[0]) -ge 22) }
if (-not $nodeOk) { WingetGet "OpenJS.NodeJS.LTS" "Node.js LTS" }
RefreshPath
foreach ($c in "git", "ffmpeg", "node", "npm") { if (-not (Has $c)) { Fail "$c kurulamadi. PowerShell'i kapatip yeniden acin ve komutu tekrar calistirin." } }
if (-not (PythonOk)) { Fail "Python 3.10+ bulunamadi. PowerShell'i kapatip yeniden acin ve tekrar deneyin (Microsoft Store 'python' kisayolu ise Ayarlar > Uygulama yurutme diger adlari'ndan kapatin)." }
Ok ("git, python " + (python --version) + ", ffmpeg, node " + (node --version))

# ---------------------------------------------------------------- 2. Kod
Step "Kod indiriliyor / guncelleniyor"
if (Test-Path (Join-Path $Dir ".git")) {
  Push-Location $Dir
  git fetch origin $Branch
  git checkout $Branch 2>$null; if ($LASTEXITCODE -ne 0) { git checkout -b $Branch "origin/$Branch" }
  git pull --ff-only origin $Branch
  if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Guncelleme yapilamadi (klasorde degistirilmis kod dosyalari olabilir). 'git status' ile bakin." }
  Pop-Location
} else {
  if (Test-Path $Dir) { Fail "$Dir var ama bir git deposu degil. Baska klasor: `$env:RF_DIR='C:\ReelsFabrikasi' yazip tekrar calistirin." }
  git clone --branch $Branch $Repo $Dir
  if ($LASTEXITCODE -ne 0) { Fail "Kod indirilemedi (internet baglantisini kontrol edin)." }
}
$App = Join-Path $Dir "reels-factory"
Set-Location $App
Ok $App

# Calisan uygulamayi kapat (eski kodu tutmasin)
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep 1; Ok "eski uygulama kapatildi" }

# ---------------------------------------------------------------- 3. Paketler
Step "Python paketleri"
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "Python paketleri kurulamadi." }
Ok "requirements.txt"
python -m pip install -q graphifyy
if ($LASTEXITCODE -ne 0) { Warn "Graphify (bilgi haritasi) kurulamadi; diger her sey calisir." } else { Ok "Graphify (bilgi haritasi)" }
python -m pip install -q uv
if ($LASTEXITCODE -ne 0) { Warn "uv kurulamadi; fetch ve git MCP sunuculari atlanir." } else { Ok "uv (fetch/git MCP sunuculari icin)" }

if (-not $NoVoice) {
  Step "Ses motoru (kendi sesinle seslendirme; PyTorch CPU ~250 MB, bir kez)"
  python -c "import torch, torchaudio" 2>$null
  if ($LASTEXITCODE -ne 0) {
    python -m pip install -q torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cpu
    if ($LASTEXITCODE -ne 0) { Warn "Ses motoru kurulamadi; uygulamadaki Sesim sayfasindan tekrar deneyebilirsiniz." } else { Ok "kuruldu" }
  } else { Ok "zaten kurulu" }
}

Step "Node paketleri (HyperFrames, GSAP) ve render tarayicisi"
npm install --silent
if ($LASTEXITCODE -ne 0) { Fail "npm install basarisiz." }
npx hyperframes browser ensure
npx hyperframes telemetry disable 2>$null | Out-Null
Ok "HyperFrames hazir"

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Ok ".env olusturuldu (anahtarlar uygulamadan da girilebilir)" }

# ---------------------------------------------------------------- 4. Claude Code
if (-not $NoClaude) {
  Step "Claude Code (senaryo, arastirma, gorsel denetim ve kitle testi icin)"
  $claude = (Get-Command claude -ErrorAction SilentlyContinue).Source
  if (-not $claude -and (Test-Path "$env:USERPROFILE\.local\bin\claude.exe")) { $claude = "$env:USERPROFILE\.local\bin\claude.exe" }
  if (-not $claude) {
    Write-Host "    Claude Code indiriliyor (resmi yukleyici)..."
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
    RefreshPath
    $bin = "$env:USERPROFILE\.local\bin"
    $up = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($up -split ";") -notcontains $bin) { [Environment]::SetEnvironmentVariable("Path", ($up.TrimEnd(";") + ";" + $bin), "User") }
    if (Test-Path "$bin\claude.exe") { $claude = "$bin\claude.exe" }
  }
  if ($claude) {
    $logged = $false
    try { $logged = [bool]((& $claude auth status 2>$null | Out-String | ConvertFrom-Json).loggedIn) } catch {}
    if (-not $logged) {
      Write-Host "    Tarayicida Claude hesabinizla (Pro/Max) giris yapin..."
      & $claude auth login
    }
    Ok (& $claude --version)
  } else { Warn "Claude Code kurulamadi; uygulamadaki 'Claude Code'u kur ve bagla' dugmesiyle tekrar deneyin." }
}

# Claude Code becerileri (Windows'ta depodaki sembolik baglantilar calismaz): reels-production + YouTube agent skill
$skillDir = Join-Path $env:USERPROFILE ".claude\skills"
New-Item -ItemType Directory -Force -Path $skillDir | Out-Null
$skills = @(Get-Item (Join-Path $App "skills\reels-production")) + @(Get-ChildItem (Join-Path $App "skills\youtube-agent") -Directory -Filter "yt-*")
foreach ($sk in $skills) {
  $dst = Join-Path $skillDir $sk.Name
  if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
  Copy-Item $sk.FullName $dst -Recurse
}
Ok ("Claude Code becerileri: " + $skills.Count + " (/yt-script, /yt-package, /yt-shorts ...)")

# MCP sunuculari (reels-fabrikasi, playwright, memory, filesystem, fetch, git, github, sentry, context7; anahtarliysa brave-search, postgres)
Step "Claude Code MCP sunuculari"
python scripts/factory.py mcp
if ($LASTEXITCODE -ne 0) { Warn "Bazi MCP sunuculari eklenemedi; uygulamada Yayin > Ayarlar > 'MCP sunucularini Claude Code'a ekle' ile tekrar deneyin." }

# ---------------------------------------------------------------- 5. Denetim + kisayollar + baslat
Step "Ortam denetimi"
python scripts/factory.py doctor --offline
Step "Kisayollar ve uygulama"
powershell -ExecutionPolicy Bypass -File (Join-Path $App "scripts\install-app.ps1") -Startup

Write-Host ""
Write-Host "TAMAM - Reels Fabrikasi kuruldu ve acildi: http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host "  Masaustu: 'Reels Fabrikasi' (panel), 'Reels Videolari' (buluttan gelen videolar)"
Write-Host "  Panel ust menusu: Studyo (kendi videonu duzenle), Sesim (sesini ogret), Yayin (kanal, onay, paylasim)"
Write-Host "  Guncellemek icin ayni komutu tekrar calistirmaniz yeterli."
