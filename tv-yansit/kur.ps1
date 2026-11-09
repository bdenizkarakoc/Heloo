# TV Yansıt — Windows uygulaması olarak kurulum (Windows PowerShell 5.1 / PowerShell 7)
#
# Kurulduğu yer:  %LOCALAPPDATA%\Programs\TV Yansit
#   TV Yansit.exe   uygulama (simgeli; Başlat menüsü, Masaüstü, görev çubuğuna sabitlenebilir, Steam)
#   app\            uygulama dosyaları
#   python\         uygulamanın kendi Python'u (bilgisayardaki Python'a bağlı değil)
#   kaldir.ps1      Ayarlar > Uygulamalar > TV Yansıt > Kaldır bunu çalıştırır
#
# Kullanım (depo klasöründen):  powershell -NoProfile -ExecutionPolicy Bypass -File .\tv-yansit\kur.ps1
# ya da içeriği PowerShell'e yapıştırın. Oyun kolunu gerçek Xbox kolu olarak kullanmak için önce: $OyunKolu = $true

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'   # Invoke-WebRequest ilerleme çubuğu indirmeyi çok yavaşlatır
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Surum = '1.0.0'
$PythonSurum = '3.12.7'
$Dal = 'claude/trusting-allen-p019dd'
$Depo = 'https://github.com/bdenizkarakoc/Heloo.git'
$Hedef = Join-Path $env:LOCALAPPDATA 'Programs\TV Yansit'
$Exe = Join-Path $Hedef 'TV Yansit.exe'
$KaldirAnahtar = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TVYansit'
if (-not (Get-Variable OyunKolu -ErrorAction SilentlyContinue)) { $OyunKolu = $false }

function Yaz($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function YoluYenile {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Dis {
    # Dış program: stderr'e yazdıkları hata sayılmasın, çıkış koduna bakılsın
    $komut = $args[0]; $argumanlar = @($args | Select-Object -Skip 1)
    $onceki = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $komut @argumanlar
    $kod = $LASTEXITCODE; $ErrorActionPreference = $onceki
    if ($kod -ne 0) { throw "$komut $($argumanlar -join ' ') başarısız (kod $kod)." }
}
function UTF8Yaz($yol, $metin, $bom) {
    [IO.File]::WriteAllText($yol, $metin, (New-Object Text.UTF8Encoding $bom))
}

# ---------------------------------------------------------------- 1) ffmpeg
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget bulunamadı. Microsoft Store'dan 'Uygulama Yükleyicisi'ni güncelleyip tekrar deneyin."
    }
    Yaz 'ffmpeg kuruluyor...'
    Dis winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements --silent
    YoluYenile
}
$Ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
if (-not $Ffmpeg) { throw "ffmpeg kuruldu ama bulunamadı. PowerShell'i kapatıp açın ve tekrar çalıştırın." }
$oge = Get-Item $Ffmpeg
if ($oge.LinkType -and $oge.Target) { $Ffmpeg = @($oge.Target)[0] }   # winget kısayolu → gerçek ffmpeg.exe

# ---------------------------------------------------------------- 2) uygulama dosyalarının kaynağı
$Gecici = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot 'tv_yansit.py'))) {
    $Kaynak = $PSScriptRoot
} elseif (Test-Path (Join-Path $HOME 'Heloo\tv-yansit\tv_yansit.py')) {
    $Kaynak = Join-Path $HOME 'Heloo\tv-yansit'
    Yaz "Güncelleniyor: $HOME\Heloo"
    try { Dis git -C (Join-Path $HOME 'Heloo') pull --ff-only origin $Dal }
    catch { Write-Host "Güncellenemedi, mevcut sürüm kurulacak: $_" -ForegroundColor Yellow }
} else {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Dis winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements --silent
        YoluYenile
    }
    $Gecici = Join-Path $env:TEMP ('tvyansit-' + [guid]::NewGuid().ToString('N'))
    Yaz 'İndiriliyor...'
    Dis git clone --depth 1 --branch $Dal --single-branch $Depo $Gecici
    $Kaynak = Join-Path $Gecici 'tv-yansit'
}

# ---------------------------------------------------------------- 3) açık kopyayı kapat, dosyaları kopyala
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" |
    Where-Object { $_.CommandLine -like '*tv_yansit.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

Yaz "Kuruluyor: $Hedef"
$App = Join-Path $Hedef 'app'
New-Item -ItemType Directory -Force -Path $App | Out-Null
foreach ($d in 'tv_yansit.py', 'girdi.py', 'panel.html', 'tv.html', 'README.md', 'tv-yansit.ico') {
    Copy-Item (Join-Path $Kaynak $d) (Join-Path $App $d) -Force
}
Copy-Item (Join-Path $Kaynak 'tv-yansit.ico') (Join-Path $Hedef 'tv-yansit.ico') -Force
UTF8Yaz (Join-Path $App 'ayar.json') (@{ ffmpeg = $Ffmpeg; surum = $Surum } | ConvertTo-Json) $false

# ---------------------------------------------------------------- 4) uygulamanın kendi Python'u (gömülü sürüm, ~11 MB)
$Py = Join-Path $Hedef 'python'
if (-not (Test-Path (Join-Path $Py 'pythonw.exe'))) {
    $mimari = 'amd64'
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { $mimari = 'arm64' }
    $zip = Join-Path $env:TEMP "python-$PythonSurum-embed-$mimari.zip"
    Yaz "Python $PythonSurum indiriliyor (yalnızca bu uygulama için)..."
    Invoke-WebRequest "https://www.python.org/ftp/python/$PythonSurum/python-$PythonSurum-embed-$mimari.zip" -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $Py -Force
    Remove-Item $zip -Force
}
$Pyw = Join-Path $Py 'pythonw.exe'

# ---------------------------------------------------------------- 5) TV Yansit.exe (Windows'un kendi C# derleyicisiyle)
$Csc = @("$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
         "$env:WINDIR\Microsoft.NET\Framework\v4.0.30319\csc.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
$Baslatici = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("TV Yansıt")]
[assembly: System.Reflection.AssemblyProduct("TV Yansıt")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

static class Program {
    [STAThread]
    static void Main(string[] args) {
        string kok = AppDomain.CurrentDomain.BaseDirectory;
        string py = Path.Combine(kok, @"python\pythonw.exe");
        string betik = Path.Combine(kok, @"app\tv_yansit.py");
        if (!File.Exists(py) || !File.Exists(betik)) {
            MessageBox.Show("TV Yansıt dosyaları eksik. kur.ps1 ile yeniden kurun.", "TV Yansıt",
                            MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        string ek = "";
        foreach (string a in args) ek += " \"" + a.Replace("\"", "") + "\"";
        ProcessStartInfo si = new ProcessStartInfo(py, "\"" + betik + "\"" + ek);
        si.WorkingDirectory = Path.Combine(kok, "app");
        si.UseShellExecute = false;
        Process.Start(si);
    }
}
'@
$ExeVar = $false
if ($Csc) {
    $cs = Join-Path $env:TEMP 'tvyansit-baslatici.cs'
    UTF8Yaz $cs $Baslatici $true
    $ikon = Join-Path $Hedef 'tv-yansit.ico'
    try {
        Dis $Csc /nologo /target:winexe /optimize "/win32icon:$ikon" "/out:$Exe" /r:System.Windows.Forms.dll $cs
        $ExeVar = Test-Path $Exe
    } catch { Write-Host "TV Yansit.exe derlenemedi, kısayol Python ile açacak: $_" -ForegroundColor Yellow }
    Remove-Item $cs -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- 6) Başlat menüsü + Masaüstü
$Ws = New-Object -ComObject WScript.Shell
foreach ($klasor in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'))) {
    $L = $Ws.CreateShortcut((Join-Path $klasor 'TV Yansıt.lnk'))
    if ($ExeVar) { $L.TargetPath = $Exe; $L.Arguments = '' }
    else { $L.TargetPath = $Pyw; $L.Arguments = '"' + (Join-Path $App 'tv_yansit.py') + '"' }
    $L.WorkingDirectory = $Hedef
    $L.IconLocation = (Join-Path $Hedef 'tv-yansit.ico') + ',0'
    $L.Description = 'Bilgisayar ekranını TV''ye yansıt'
    $L.Save()
}

# ---------------------------------------------------------------- 7) kaldırıcı + "Uygulamalar ve özellikler" kaydı
$Kaldirici = @'
# TV Yansıt kaldırıcı
$ErrorActionPreference = 'SilentlyContinue'
$Hedef = Split-Path -Parent $MyInvocation.MyCommand.Path
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*$Hedef*" -and $_.ProcessId -ne $PID } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
foreach ($k in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    Remove-Item (Join-Path $k 'TV Yansıt.lnk') -Force
}
Remove-Item 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\TVYansit' -Recurse -Force
$kural = "Get-NetFirewallRule -DisplayName 'TV Yansit*' | Remove-NetFirewallRule"
$kimlik = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if ($kimlik.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { Invoke-Expression $kural }
else {
    $kod = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($kural))
    Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList "-NoProfile -EncodedCommand $kod"
}
Set-Location $env:TEMP
Start-Sleep -Milliseconds 500
Remove-Item $Hedef -Recurse -Force
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.MessageBox]::Show('TV Yansıt kaldırıldı. (Steam kütüphanesine eklediyseniz oradan da silebilirsiniz.)', 'TV Yansıt') | Out-Null
'@
$KaldirYol = Join-Path $Hedef 'kaldir.ps1'
UTF8Yaz $KaldirYol $Kaldirici $true
$boyutKB = [int]((Get-ChildItem $Hedef -Recurse -File | Measure-Object Length -Sum).Sum / 1KB)
$simge = Join-Path $Hedef 'tv-yansit.ico'
if ($ExeVar) { $simge = $Exe }
New-Item -Path $KaldirAnahtar -Force | Out-Null
$kayit = @{
    DisplayName = 'TV Yansıt'; DisplayVersion = $Surum; Publisher = 'TV Yansıt'
    DisplayIcon = $simge; InstallLocation = $Hedef
    UninstallString = 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $KaldirYol + '"'
}
foreach ($k in $kayit.Keys) { Set-ItemProperty -Path $KaldirAnahtar -Name $k -Value $kayit[$k] }
foreach ($k in 'NoModify', 'NoRepair') {
    New-ItemProperty -Path $KaldirAnahtar -Name $k -Value 1 -PropertyType DWord -Force | Out-Null
}
New-ItemProperty -Path $KaldirAnahtar -Name EstimatedSize -Value $boyutKB -PropertyType DWord -Force | Out-Null

# ---------------------------------------------------------------- 8) güvenlik duvarı (TV'nin bilgisayara ulaşması için)
$PyExe = Join-Path $Py 'python.exe'
$kurallar = @"
Get-NetFirewallRule -DisplayName 'TV Yansit*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
New-NetFirewallRule -DisplayName 'TV Yansit (pythonw)' -Direction Inbound -Program '$Pyw' -Action Allow -Profile Private | Out-Null
New-NetFirewallRule -DisplayName 'TV Yansit (python)' -Direction Inbound -Program '$PyExe' -Action Allow -Profile Private | Out-Null
Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public' | Set-NetConnectionProfile -NetworkCategory Private
"@
$kimlik = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
Yaz 'Güvenlik duvarı izni veriliyor (yalnızca Özel ağlar)...'
if ($kimlik.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Invoke-Expression $kurallar
} else {
    $kod = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($kurallar))
    try { Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -ArgumentList "-NoProfile -EncodedCommand $kod" }
    catch { Write-Host 'Yönetici izni verilmedi; Windows ilk açılışta sorarsa "Özel ağlar"a izin verin.' -ForegroundColor Yellow }
}

# ---------------------------------------------------------------- 9) isteğe bağlı: gerçek Xbox kolu
if ($OyunKolu) {
    Yaz 'Sanal Xbox kolu kuruluyor (ViGEmBus + vgamepad)...'
    $pth = Get-ChildItem $Py -Filter 'python*._pth' | Select-Object -First 1
    (Get-Content $pth.FullName) -replace '^#\s*import site', 'import site' | Set-Content $pth.FullName -Encoding ASCII
    $getpip = Join-Path $env:TEMP 'get-pip.py'
    Invoke-WebRequest 'https://bootstrap.pypa.io/get-pip.py' -OutFile $getpip -UseBasicParsing
    Dis $PyExe $getpip --no-warn-script-location
    Dis $PyExe -m pip install --upgrade vgamepad --no-warn-script-location
    try { Dis winget install -e --id ViGEm.ViGEmBus --accept-source-agreements --accept-package-agreements --silent }
    catch { Write-Host 'ViGEmBus winget ile kurulamadı; github.com/nefarius/ViGEmBus/releases adresinden kurun.' -ForegroundColor Yellow }
}

if ($Gecici) { Remove-Item $Gecici -Recurse -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------- 10) aç
Yaz 'TV Yansıt açılıyor.'
if ($ExeVar) { Start-Process $Exe }
else { Start-Process $Pyw -ArgumentList ('"' + (Join-Path $App 'tv_yansit.py') + '"') -WorkingDirectory $App }
Write-Host ''
Write-Host "Kuruldu: Başlat menüsünde ve Masaüstünde 'TV Yansıt'. Kaldırmak için: Ayarlar > Uygulamalar > TV Yansıt > Kaldır." -ForegroundColor Green
