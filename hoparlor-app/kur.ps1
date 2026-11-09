# Hoparlor Ses Ayari - KURULUM / GUNCELLEME (Windows 10/11, PowerShell)
#
# Internetten tek satirla (PowerShell'e yapistir, Enter):
#   irm https://raw.githubusercontent.com/bdenizkarakoc/Heloo/claude/dazzling-fermi-49dzwq/hoparlor-app/kur.ps1 | iex
# veya indirilen dosyayla:
#   powershell -ExecutionPolicy Bypass -File kur.ps1
#   powershell -ExecutionPolicy Bypass -File kur.ps1 -Kaldir      # kaldirir (Equalizer APO'ya dokunmaz)
#
# Yaptiklari: programi %LOCALAPPDATA%\HoparlorSesAyari klasorune indirir -> Masaustu ve Baslat menusune
# "Hoparlor Ses Ayari" kisayolu koyar -> Equalizer APO yoksa indirip kurulumunu baslatir -> programi acar.
# Tekrar calistirmak guvenlidir (guncelleme yapar; ayarlarin %APPDATA%\HelooHoparlor icinde kalir).
param([switch]$Kaldir, [switch]$Acma)

$ErrorActionPreference = "Stop"
$Branch = if ($env:HOPARLOR_BRANCH) { $env:HOPARLOR_BRANCH } else { "claude/dazzling-fermi-49dzwq" }
$Raw = "https://raw.githubusercontent.com/bdenizkarakoc/Heloo/$Branch/hoparlor-app"
$Dir = Join-Path $env:LOCALAPPDATA "HoparlorSesAyari"
$App = Join-Path $Dir "HoparlorSesAyari.ps1"
$Name = "Hoparlor Ses Ayari"
$ApoDownload = "https://sourceforge.net/projects/equalizerapo/files/latest/download"
$ApoPage = "https://sourceforge.net/projects/equalizerapo/"
$Links = @(
  (Join-Path ([Environment]::GetFolderPath("Desktop")) "$Name.lnk"),
  (Join-Path ([Environment]::GetFolderPath("Programs")) "$Name.lnk")
)

function Step($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Yellow }
function Ok($t) { Write-Host "    OK $t" -ForegroundColor Green }
function Warn($t) { Write-Host "    ! $t" -ForegroundColor DarkYellow }

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

if ($Kaldir) {
  Step "Kaldiriliyor"
  foreach ($l in $Links) { if (Test-Path $l) { Remove-Item $l -Force } }
  if (Test-Path $Dir) { Remove-Item $Dir -Recurse -Force }
  Ok "Program ve kisayollar kaldirildi. Ayarlar: $env:APPDATA\HelooHoparlor (istersen elle sil)."
  Write-Host "    Sesi duz hale getirmek icin Equalizer APO klasorundeki config.txt'den 'Include: heloo-hoparlor.txt' satirini sil"
  Write-Host "    ya da Equalizer APO'yu Denetim Masasi > Programlar'dan kaldir."
  return
}

Step "Program indiriliyor"
New-Item -ItemType Directory -Force -Path $Dir | Out-Null
$tmp = "$App.yeni"
Invoke-WebRequest -UseBasicParsing -Uri "$Raw/HoparlorSesAyari.ps1" -OutFile $tmp
$bytes = [IO.File]::ReadAllBytes($tmp)
if ($bytes.Length -lt 2000 -or $bytes[0] -ne 0xEF -or $bytes[1] -ne 0xBB) { Remove-Item $tmp -Force; throw "Indirilen dosya bozuk gorunuyor, tekrar dene." }
Move-Item $tmp $App -Force
Unblock-File $App
try { Invoke-WebRequest -UseBasicParsing -Uri "$Raw/kur.ps1" -OutFile (Join-Path $Dir "kur.ps1"); Unblock-File (Join-Path $Dir "kur.ps1") } catch { }
Ok $App

Step "Kisayollar"
$ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$shell = New-Object -ComObject WScript.Shell
foreach ($l in $Links) {
  New-Item -ItemType Directory -Force -Path (Split-Path $l) | Out-Null
  $s = $shell.CreateShortcut($l)
  $s.TargetPath = $ps
  $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$App`""
  $s.WorkingDirectory = $Dir
  $s.IconLocation = "$env:SystemRoot\System32\SndVol.exe,0"
  $s.Description = "Hoparlor ses ayari: bas, tiz, muzik turu (Equalizer APO)"
  $s.WindowStyle = 7
  $s.Save()
  Ok $l
}

Step "Equalizer APO"
function ApoInstalled {
  foreach ($k in "HKLM:\SOFTWARE\EqualizerAPO", "HKLM:\SOFTWARE\WOW6432Node\EqualizerAPO") {
    try { if ((Get-ItemProperty -Path $k -Name ConfigPath -ErrorAction Stop).ConfigPath) { return $true } } catch { }
  }
  Test-Path (Join-Path $env:ProgramFiles "EqualizerAPO\config")
}
if (ApoInstalled) {
  Ok "kurulu"
} else {
  Warn "kurulu degil - ses ayari icin gerekli (ucretsiz, acik kaynak)."
  $setup = Join-Path $env:TEMP "EqualizerAPO-kurulum.exe"
  try {
    Write-Host "    indiriliyor (SourceForge)..."
    Invoke-WebRequest -UseBasicParsing -UserAgent "Wget" -Uri $ApoDownload -OutFile $setup
    $head = [IO.File]::ReadAllBytes($setup)[0..1]
    if ($head[0] -ne 0x4D -or $head[1] -ne 0x5A) { throw "kurulum dosyasi yerine sayfa indi" }   # "MZ" = exe
    Write-Host ""
    Write-Host "    Kurulum penceresi aciliyor. Sonunda acilan 'Configurator' penceresinde" -ForegroundColor Cyan
    Write-Host "    Z607'nin bagli oldugu cikisi (Hoparlorler / Speakers) ISARETLE, OK de, bilgisayari YENIDEN BASLAT." -ForegroundColor Cyan
    Start-Process -FilePath $setup -Verb RunAs -Wait
    if (ApoInstalled) { Ok "Equalizer APO kuruldu - yeniden baslattiktan sonra ses ayari calisir." }
    else { Warn "Kurulum tamamlanmadi; programdaki 'Equalizer APO indir' dugmesiyle sonra kurabilirsin." }
  } catch {
    Warn "Otomatik indirilemedi ($($_.Exception.Message)). Sayfa aciliyor: $ApoPage"
    Start-Process $ApoPage
  }
}

Write-Host ""
Write-Host "Hazir! Masaustundeki '$Name' kisayoluyla ac (izin sorusuna Evet de)." -ForegroundColor Green
if (-not $Acma) { Start-Process $ps -WindowStyle Minimized -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$App`"") }
Write-Host "Acilmazsa: $env:APPDATA\HelooHoparlor\hata.log dosyasina bak ya da su komutla hatayi gor:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$App`" -NoElevate"
