# TV Yansıt — tek adımda kurulum ve başlatma (Windows PowerShell 5.1 / PowerShell 7)
# Kullanım: PowerShell'i "Yönetici olarak çalıştır" ile açın, bu dosyanın içeriğini yapıştırıp Enter'a basın.
# Oyun kolunu gerçek Xbox kolu olarak kullanmak için önce:  $OyunKolu = $true
# Ne yapar: git / Python / ffmpeg yoksa winget ile kurar, depoyu indirir ya da günceller, güvenlik duvarı izni
# verir (yönetici ise), Masaüstüne kısayol koyar ve uygulamayı açar.

$ErrorActionPreference = 'Stop'
$Dal = 'claude/trusting-allen-p019dd'
$Depo = 'https://github.com/bdenizkarakoc/Heloo.git'
$Klasor = Join-Path $HOME 'Heloo'
if (-not (Get-Variable OyunKolu -ErrorAction SilentlyContinue)) { $OyunKolu = $false }

function Yaz($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function YoluYenile {
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [Environment]::GetEnvironmentVariable('Path', 'User')
}
function Calisiyor($komut, $arg) {
    try { & $komut $arg *> $null; return $LASTEXITCODE -eq 0 } catch { return $false }
}
function PythonBul {
    # python.exe yolunu döndürür; Microsoft Store kısayolunu atlar
    $adaylar = @(
        @{ k = 'python'; a = @() }, @{ k = 'py'; a = @('-3') },
        @{ k = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; a = @() }
    )
    foreach ($c in $adaylar) {
        try {
            $yol = (& $c.k @($c.a + @('-c', 'import sys; print(sys.executable)')) 2>$null | Select-Object -Last 1)
            if ($LASTEXITCODE -eq 0 -and $yol -and (Test-Path $yol.Trim())) { return $yol.Trim() }
        } catch { }
    }
    return $null
}
function GitCalistir {
    # git ilerleme yazılarını stderr'e yazar; hata sayılmasın, çıkış koduna bakılsın
    $onceki = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & git.exe @args
    $kod = $LASTEXITCODE; $ErrorActionPreference = $onceki
    if ($kod -ne 0) { throw "git $($args -join ' ') başarısız (kod $kod)." }
}
function Kur($ad, $id) {
    Yaz "$ad kuruluyor (winget: $id)..."
    winget install -e --id $id --accept-source-agreements --accept-package-agreements --silent
    YoluYenile
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget bulunamadı. Microsoft Store'dan 'Uygulama Yükleyicisi'ni (App Installer) güncelleyip tekrar deneyin."
}

# 1) Gerekli programlar
if (-not (Calisiyor 'git' '--version'))     { Kur 'Git' 'Git.Git' }
if (-not (PythonBul))                       { Kur 'Python' 'Python.Python.3.12' }  # Store kısayolu da "yok" sayılır
if (-not (Calisiyor 'ffmpeg' '-version'))   { Kur 'ffmpeg' 'Gyan.FFmpeg' }
$Py = PythonBul
if (-not $Py) { throw "Python kuruldu ama bulunamadı. PowerShell'i kapatıp yeniden açın ve bu kodu tekrar çalıştırın." }
foreach ($k in 'git', 'ffmpeg') {
    if (-not (Get-Command $k -ErrorAction SilentlyContinue)) {
        throw "$k kuruldu ama bulunamadı. PowerShell'i kapatıp yeniden açın ve bu kodu tekrar çalıştırın."
    }
}

# 2) Uygulamayı indir ya da güncelle (özel depo: GitHub girişi istenirse tarayıcıda onaylayın)
if (Test-Path (Join-Path $Klasor '.git')) {
    Yaz "Güncelleniyor: $Klasor"
    GitCalistir -C $Klasor fetch origin $Dal
    GitCalistir -C $Klasor checkout $Dal
    GitCalistir -C $Klasor pull --ff-only origin $Dal
} else {
    Yaz "İndiriliyor: $Klasor"
    GitCalistir clone --branch $Dal --single-branch $Depo $Klasor
}
$Uygulama = Join-Path $Klasor 'tv-yansit'
$Betik = Join-Path $Uygulama 'tv_yansit.py'
if (-not (Test-Path $Betik)) { throw "İndirme başarısız: $Betik yok (GitHub girişi ya da internet bağlantısı)." }
$Pyw = Join-Path (Split-Path $Py) 'pythonw.exe'
if (-not (Test-Path $Pyw)) { $Pyw = $Py }

# 3) İsteğe bağlı: gerçek Xbox kolu (ViGEmBus sürücüsü + vgamepad)
if ($OyunKolu) {
    Yaz 'Sanal Xbox kolu kuruluyor (ViGEmBus + vgamepad)...'
    winget install -e --id ViGEm.ViGEmBus --accept-source-agreements --accept-package-agreements --silent
    & $Py -m pip install --upgrade vgamepad
    Write-Host 'Not: ViGEmBus ilk kurulumda bilgisayarın yeniden başlatılmasını isteyebilir.' -ForegroundColor Yellow
}

# 4) Güvenlik duvarı + ağ profili (yalnızca yönetici). TV'nin bilgisayara ulaşması ve TV aramanın yanıtları için.
$Kimlik = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$Yonetici = $Kimlik.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Yonetici) {
    Yaz 'Güvenlik duvarı izni veriliyor (yalnızca Özel ağlar)...'
    Get-NetFirewallRule -DisplayName 'TV Yansit*' -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    foreach ($p in ($Py, $Pyw | Select-Object -Unique)) {
        New-NetFirewallRule -DisplayName "TV Yansit ($([IO.Path]::GetFileName($p)))" -Direction Inbound `
            -Program $p -Action Allow -Profile Private | Out-Null
    }
    $Genel = Get-NetConnectionProfile | Where-Object NetworkCategory -eq 'Public'
    if ($Genel) {
        Yaz "Ev ağı 'Genel' görünüyor; 'Özel' yapılıyor (TV'nin bilgisayarı görebilmesi için): $($Genel.Name -join ', ')"
        $Genel | Set-NetConnectionProfile -NetworkCategory Private
    }
} else {
    Write-Host 'Not: Yönetici değilsiniz; Windows ilk açılışta izin sorarsa "Özel ağlar"a izin verin.' -ForegroundColor Yellow
}

# 5) Masaüstü kısayolu
$Kisayol = Join-Path ([Environment]::GetFolderPath('Desktop')) 'TV Yansıt.lnk'
$Ws = New-Object -ComObject WScript.Shell
$L = $Ws.CreateShortcut($Kisayol)
$L.TargetPath = $Pyw
$L.Arguments = "`"$Betik`""
$L.WorkingDirectory = $Uygulama
$L.IconLocation = "$env:SystemRoot\System32\imageres.dll,190"
$L.Description = 'Bilgisayar ekranını TV''ye yansıt'
$L.Save()

# 6) Başlat (önceki açık kopyayı kapatmadan yenisi 8766+ portundan açılır)
Yaz 'TV Yansıt açılıyor; panel tarayıcıda gelecek.'
Start-Process -FilePath $Pyw -ArgumentList "`"$Betik`"" -WorkingDirectory $Uygulama
Write-Host "Hazır. Sonraki seferlerde Masaüstündeki 'TV Yansıt' kısayolunu kullanın." -ForegroundColor Green
