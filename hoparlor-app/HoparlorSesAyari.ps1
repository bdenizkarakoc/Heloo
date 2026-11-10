#Requires -Version 5.1
<#
.SYNOPSIS
  Hoparlör Ses Ayarı — Logitech Z607 5.1 ve diğer hoparlörler için ekolayzır (bas, tiz, müzik türü hazırları).

.DESCRIPTION
  Tek başına çalışan pencereli program. Logitech, Z607 için bilgisayarda ekolayzır programı sunmadığından ses
  ayarı ücretsiz, açık kaynak Equalizer APO ile bütün Windows sesine uygulanır:
    <Equalizer APO>\config\heloo-hoparlor.txt   (her hoparlör için ayrı blok: Device: {çıkış GUID})
    config.txt içine bir kez:  Include: heloo-hoparlor.txt
  Ayarlar: %APPDATA%\HelooHoparlor\ayarlar.json (reels-factory /hoparlor sayfasıyla aynı hazırlar ve kurallar).

  Kurulum (kısayol + Equalizer APO): hoparlor-app\kur.ps1 — README.md'deki tek satır.
  Elle çalıştırma: dosyaya sağ tık → "PowerShell ile çalıştır". Equalizer APO klasörüne yazmak için yönetici izni ister.

.PARAMETER SelfTest
  Pencere açmadan örnek ayar dosyasını ekrana yazar (deneme için).
#>
param([switch]$NoElevate, [switch]$SelfTest)

$ErrorActionPreference = 'Stop'

# ------------------------------------------------------------------ veriler
$Bands = @(31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)
$Limit = 12
$Fs = 48000.0

$Presets = [ordered]@{   # reels-factory/scripts/reels/hoparlor.py PRESETS ile aynı (test denetler)
  # ---- en iyi ayarlar
  z607       = @{ ad = 'Z607 için en iyi'; grup = 'en_iyi'; b = @(0, 2, 2, -1, -2, -1, 1, 2, 2, 1); sub = 1; ipucu = 'Z607''ye göre: sıkı bas, uydu hoparlörlerin kutu sesi azaltılır, vokal ve detay açılır.' }
  referans   = @{ ad = 'Referans (stüdyo)'; grup = 'en_iyi'; b = @(3, 2.5, 1.5, 0.5, 0, 0, 0, -0.5, -1, -1.5); ipucu = 'Ses mühendislerinin oda hedefi: hafif sıcak, doğal; şarkı nasıl kaydedildiyse öyle.' }
  genel      = @{ ad = 'Dengeli canlı'; grup = 'en_iyi'; b = @(3, 3, 1, -1, -1.5, -0.5, 0.5, 2, 2.5, 2); ipucu = 'Her şeye uyan hafif V: dolgun bas, net vokal, parlak tiz; yorucu değil.' }
  netlik     = @{ ad = 'Vokal netliği'; grup = 'en_iyi'; b = @(-2, -1, 0, -1, 0, 1, 3, 3, 1, 0); merkez = 2; ipucu = 'Şarkı sözü ve konuşma öne çıkar; uğultu azalır.' }
  kisik      = @{ ad = 'Kısık seste dolgun'; grup = 'en_iyi'; b = @(6, 4, 2, 0, 0, 0, 0, 1, 3, 4); ipucu = 'Kulak kısık seste bası ve tizi az duyar (Fletcher–Munson); bu ayar telafi eder.' }
  derin      = @{ ad = 'Derin bas (sinema)'; grup = 'en_iyi'; b = @(5, 5, 3, 0, -1, 0, 0, 0, 1, 1); sub = 2; merkez = 2; ipucu = 'Film patlamaları ve derin bas; diyalog merkezden net.' }
  sicak      = @{ ad = 'Sıcak / yumuşak'; grup = 'en_iyi'; b = @(2, 2, 2, 1, 0, 0, -1, -2, -2, -3); ipucu = 'Uzun dinlemede yormaz; sert, cızırtılı kayıtları yumuşatır.' }
  parlak     = @{ ad = 'Parlak / detaylı'; grup = 'en_iyi'; b = @(-1, 0, 0, 0, 0, 0, 1, 2, 3, 4); ipucu = 'Enstrüman detayları ve hava; boğuk kayıtları açar.' }
  # ---- müzik türleri
  duz        = @{ ad = 'Düz'; grup = 'tur'; b = @(0, 0, 0, 0, 0, 0, 0, 0, 0, 0) }
  pop        = @{ ad = 'Pop'; grup = 'tur'; b = @(-1, 1, 3, 4, 2, 0, -1, 0, 1, 2) }
  rock       = @{ ad = 'Rock'; grup = 'tur'; b = @(4, 3, 2, 0, -1, -1, 1, 3, 4, 4) }
  rnb        = @{ ad = 'R&&B'; grup = 'tur'; b = @(3, 6, 5, 1, -2, -1, 1, 2, 3, 3) }
  hiphop     = @{ ad = 'Hip-hop / Rap'; grup = 'tur'; b = @(5, 5, 3, 1, -1, -1, 1, 0, 1, 2) }
  trap       = @{ ad = 'Trap / Drill'; grup = 'tur'; b = @(6, 6, 3, 0, -2, -1, 1, 1, 2, 2) }
  caz        = @{ ad = 'Caz'; grup = 'tur'; b = @(3, 2, 1, 2, -1, -1, 0, 1, 2, 3) }
  klasik     = @{ ad = 'Klasik'; grup = 'tur'; b = @(3, 2, 1, 0, -1, -1, 0, 1, 2, 3) }
  turku      = @{ ad = 'Türkü / Halk'; grup = 'tur'; b = @(0, 1, 1, 0, 1, 2, 3, 3, 2, 1) }
  halay      = @{ ad = 'Halay / Oyun havası'; grup = 'tur'; b = @(5, 4, 2, 0, -1, 0, 1, 1, 1, 1) }
  arabesk    = @{ ad = 'Arabesk'; grup = 'tur'; b = @(1, 2, 2, 0, 0, 1, 2, 2, 1, 1) }
  elektronik = @{ ad = 'Elektronik'; grup = 'tur'; b = @(5, 4, 1, 0, -2, 0, 1, 2, 4, 5) }
  akustik    = @{ ad = 'Akustik'; grup = 'tur'; b = @(2, 1, 1, 1, 2, 1, 2, 2, 2, 1) }
  lofi       = @{ ad = 'Lo-fi / Chill'; grup = 'tur'; b = @(2, 2, 1, 1, 0, -1, -1, -2, -2, -3) }
  canli      = @{ ad = 'Canlı konser'; grup = 'tur'; b = @(2, 1, 0, -1, 0, 1, 2, 2, 2, 2) }
  bas        = @{ ad = 'Bol bas'; grup = 'tur'; b = @(7, 6, 4, 2, 0, 0, 0, 0, 0, 0) }
  film       = @{ ad = 'Film / Dizi'; grup = 'tur'; b = @(4, 3, 1, 0, 0, 1, 2, 1, 2, 2); merkez = 3 }
  konusma    = @{ ad = 'Konuşma / Podcast'; grup = 'tur'; b = @(-4, -3, -1, 0, 2, 3, 4, 3, 1, 0); merkez = 2 }
  oyun       = @{ ad = 'Oyun'; grup = 'tur'; b = @(3, 2, 0, -1, 0, 1, 3, 3, 2, 1) }
  gece       = @{ ad = 'Gece (kısık ses)'; grup = 'tur'; b = @(-4, -3, -2, 0, 1, 2, 2, 1, 0, -1) }
}

# hp: koruma için alçak kesim (Hz), max: en çok yükseltme (dB). Hoparlörün çalamadığı derin bas yükseltilmez.
$Kinds = [ordered]@{
  z607      = @{ ad = 'Logitech Z607 5.1';               hp = 35;  max = 10; k51 = $true; oneri = 'z607' }
  masaustu  = @{ ad = 'Masaüstü hoparlör (2.0/2.1)';     hp = 45;  max = 9;  k51 = $false; oneri = 'genel' }
  soundbar  = @{ ad = 'Soundbar';                        hp = 45;  max = 9;  k51 = $false; oneri = 'genel' }
  bluetooth = @{ ad = 'Taşınabilir Bluetooth hoparlör';  hp = 70;  max = 8;  k51 = $false; oneri = 'genel' }
  laptop    = @{ ad = 'Dizüstü dahili hoparlör';         hp = 150; max = 6;  k51 = $false; oneri = 'netlik' }
  kulaklik  = @{ ad = 'Kulaklık';                        hp = 0;   max = 10; k51 = $false; oneri = 'referans' }
}

# sade sürgüler: anahtar, ad, süzgeç türü, frekans, Q
$Simple = @(
  @{ k = 'bas';   ad = 'Bas';            t = 'LSC'; f = 105;  q = 0.71 },
  @{ k = 'orta';  ad = 'Orta';           t = 'PK';  f = 900;  q = 0.7 },
  @{ k = 'vokal'; ad = 'Vokal / netlik'; t = 'PK';  f = 3000; q = 1.0 },
  @{ k = 'tiz';   ad = 'Tiz';            t = 'HSC'; f = 8000; q = 0.71 }
)
$Chans = @(
  @{ k = 'sub';    ad = 'Subwoofer';        ch = 'SUB' },
  @{ k = 'merkez'; ad = 'Merkez (diyalog)'; ch = 'C' },
  @{ k = 'arka';   ad = 'Arka hoparlörler'; ch = 'RL RR SL SR' }
)

# Ses gücü: yükseltilen yerde en yüksek noktanın ne kadarı kadar genel ses kısılsın (cızırtı koruması).
$Power = [ordered]@{
  guvenli = @{ ad = 'Güvenli'; pay = 1.0; ipucu = 'Hiç cızırtı olmaz; yükselttiğin kadar genel ses kısılır.' }
  dengeli = @{ ad = 'Dengeli'; pay = 0.5; ipucu = 'Önerilen: ses az kısılır, cızırtı nadir.' }
  yuksek  = @{ ad = 'Yüksek';  pay = 0.0; ipucu = 'Ses hiç kısılmaz. Çok bas açıp sonuna kadar dinlerken bazı şarkılarda bozulma olabilir.' }
}
$LevelMax = 10

$AppDir = Join-Path $(if ($env:APPDATA) { $env:APPDATA } else { $HOME }) 'HelooHoparlor'
$StateFile = Join-Path $AppDir 'ayarlar.json'
$ApoFile = 'heloo-hoparlor.txt'
$ApoInclude = "Include: $ApoFile"
$ApoUrl = 'https://sourceforge.net/projects/equalizerapo/'

# ------------------------------------------------------------------ ayarlar
function New-Settings([string]$preset = 'duz') {
  $p = $Presets[$preset]
  $m = 0; if ($p.ContainsKey('merkez')) { $m = $p.merkez }
  $sb = 0; if ($p.ContainsKey('sub')) { $sb = $p.sub }
  [pscustomobject]@{ acik = $true; preset = $preset; bands = @($p.b | ForEach-Object { [double]$_ })
    bas = 0.0; orta = 0.0; vokal = 0.0; tiz = 0.0; seviye = 0.0; guc = 'dengeli'; sub = [double]$sb; merkez = [double]$m; arka = 0.0 }
}

function New-Speaker([string]$id, [string]$ad, [string]$kind) {
  [pscustomobject]@{ id = $id; ad = $ad; kind = $kind; device = ''; device_ad = ''; settings = (New-Settings $Kinds[$kind].oneri) }   # türüne önerilen ayarla başlar
}

function Clamp([double]$v, [double]$lo = -12, [double]$hi = $Limit) { [math]::Round([math]::Min($hi, [math]::Max($lo, $v)), 1) }

function Repair-Settings($s) {
  $d = New-Settings
  if ($null -eq $s) { return $d }
  foreach ($k in 'acik', 'preset', 'bas', 'orta', 'vokal', 'tiz', 'seviye', 'guc', 'sub', 'merkez', 'arka') {
    if ($s.PSObject.Properties[$k]) { $d.$k = $s.$k }
  }
  if ($s.PSObject.Properties['bands'] -and @($s.bands).Count -eq $Bands.Count) { $d.bands = @($s.bands | ForEach-Object { Clamp $_ }) }
  foreach ($k in 'bas', 'orta', 'vokal', 'tiz', 'sub', 'merkez', 'arka') { $d.$k = Clamp $d.$k }
  $d.seviye = Clamp $d.seviye -20 $LevelMax
  if (-not $Power.Contains([string]$d.guc)) { $d.guc = 'dengeli' }
  $d.acik = [bool]$d.acik
  if (-not ($Presets.Contains([string]$d.preset) -or $d.preset -eq 'ozel' -or ([string]$d.preset).StartsWith('my:'))) { $d.preset = 'ozel' }
  $d
}

function Read-State {
  try {
    if (Test-Path $StateFile) {
      $st = Get-Content $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
      if ($st.speakers) {
        $st.speakers = @($st.speakers | ForEach-Object {
            if (-not $Kinds.Contains([string]$_.kind)) { $_.kind = 'masaustu' }
            $_.settings = Repair-Settings $_.settings; $_ })
        if (-not $st.PSObject.Properties['custom']) { $st | Add-Member -NotePropertyName custom -NotePropertyValue @() }
        $st.custom = @($st.custom | Where-Object { $_ -and $_.id -and $_.ad } | ForEach-Object { $_.settings = Repair-Settings $_.settings; $_ })
        return $st
      }
    }
  } catch { }
  [pscustomobject]@{ active = 'z607'; custom = @(); speakers = @(New-Speaker 'z607' 'Logitech Z607' 'z607') }
}

function Save-State($st) {
  New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
  [IO.File]::WriteAllText($StateFile, ($st | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
}

function Get-Active($st) {
  $a = @($st.speakers | Where-Object { $_.id -eq $st.active })
  if ($a.Count) { $a[0] } else { $st.speakers[0] }
}

# ------------------------------------------------------------------ süzgeçler
# 10 bant Equalizer APO GraphicEQ ile uygulanır: pürüzsüz eğri, bantlar arasında dalgalanma yok.
function Get-Graphic($s, [string]$kind) {
  $k = $Kinds[$kind]
  for ($i = 0; $i -lt $Bands.Count; $i++) {
    $g = [math]::Min([double]$s.bands[$i], [double]$k.max)
    if ($k.hp -and $Bands[$i] -lt $k.hp * 1.3) { $g = [math]::Min($g, 0) }   # çalamadığı bas yükseltilmez
    , @([double]$Bands[$i], $g)
  }
}

function Get-GraphicDb($pts, [double]$f) {
  if ($f -le $pts[0][0]) { return $pts[0][1] }
  $last = $pts[$pts.Count - 1]
  if ($f -ge $last[0]) { return $last[1] }
  for ($i = 1; $i -lt $pts.Count; $i++) {
    if ($f -le $pts[$i][0]) {
      $t = [math]::Log($f / $pts[$i - 1][0]) / [math]::Log($pts[$i][0] / $pts[$i - 1][0])
      return $pts[$i - 1][1] + ($pts[$i][1] - $pts[$i - 1][1]) * $t
    }
  }
  0.0
}

function Get-Filters($s, [string]$kind) {
  $k = $Kinds[$kind]; $mx = [double]$k.max
  $out = New-Object System.Collections.ArrayList
  if ($k.hp) { [void]$out.Add(@('HP', [double]$k.hp, 0.0, 0.71)) }
  foreach ($x in $Simple) {
    $g = [math]::Min([double]$s.($x.k), $mx)
    if ($x.k -eq 'bas' -and $k.hp -ge 100) { $g = [math]::Min($g, 3) }
    if ($g -ne 0) { [void]$out.Add(@($x.t, [double]$x.f, $g, [double]$x.q)) }
  }
  , $out
}

function Get-Coeffs([string]$t, [double]$f, [double]$g, [double]$q) {
  $a = [math]::Pow(10, $g / 40); $w = 2 * [math]::PI * $f / $Fs
  $cw = [math]::Cos($w); $al = [math]::Sin($w) / (2 * $q)
  switch ($t) {
    'PK' { return @((1 + $al * $a), (-2 * $cw), (1 - $al * $a), (1 + $al / $a), (-2 * $cw), (1 - $al / $a)) }
    'HP' { return @(((1 + $cw) / 2), (-(1 + $cw)), ((1 + $cw) / 2), (1 + $al), (-2 * $cw), (1 - $al)) }
  }
  $r = 2 * [math]::Sqrt($a) * $al
  if ($t -eq 'LSC') {
    return @(($a * (($a + 1) - ($a - 1) * $cw + $r)), (2 * $a * (($a - 1) - ($a + 1) * $cw)), ($a * (($a + 1) - ($a - 1) * $cw - $r)),
      (($a + 1) + ($a - 1) * $cw + $r), (-2 * (($a - 1) + ($a + 1) * $cw)), (($a + 1) + ($a - 1) * $cw - $r))
  }
  @(($a * (($a + 1) + ($a - 1) * $cw + $r)), (-2 * $a * (($a - 1) + ($a + 1) * $cw)), ($a * (($a + 1) + ($a - 1) * $cw - $r)),
    (($a + 1) - ($a - 1) * $cw + $r), (2 * (($a - 1) - ($a + 1) * $cw)), (($a + 1) - ($a - 1) * $cw - $r))
}

$CurveFreqs = @(0..119 | ForEach-Object { 20 * [math]::Pow(1000, $_ / 119) })

function Get-Curve($flt) {
  $cs = @($flt | ForEach-Object { , (Get-Coeffs $_[0] $_[1] $_[2] $_[3]) })
  foreach ($f in $CurveFreqs) {
    $w = 2 * [math]::PI * $f / $Fs; $c1 = [math]::Cos($w); $s1 = [math]::Sin($w); $c2 = [math]::Cos(2 * $w); $s2 = [math]::Sin(2 * $w)
    $db = 0.0
    foreach ($c in $cs) {
      $nr = $c[0] + $c[1] * $c1 + $c[2] * $c2; $ni = $c[1] * $s1 + $c[2] * $s2
      $dr = $c[3] + $c[4] * $c1 + $c[5] * $c2; $di = $c[4] * $s1 + $c[5] * $s2
      $db += 10 * [math]::Log10([math]::Max(1e-18, ($nr * $nr + $ni * $ni) / ($dr * $dr + $di * $di)))
    }
    $db
  }
}

function Get-Analysis($sp) {
  $s = $sp.settings; $k = $Kinds[$sp.kind]
  $flt = Get-Filters $s $sp.kind
  $geq = @(Get-Graphic $s $sp.kind)
  $bq = if ($flt.Count) { @(Get-Curve $flt) } else { @($CurveFreqs | ForEach-Object { 0.0 }) }
  $curve = @(for ($i = 0; $i -lt $CurveFreqs.Count; $i++) { $bq[$i] + (Get-GraphicDb $geq $CurveFreqs[$i]) })
  $peak = [math]::Max(0, ($curve[3..($curve.Count - 1)] | Measure-Object -Maximum).Maximum)
  $chPeak = 0.0
  if ($k.k51) { foreach ($c in $Chans) { $chPeak = [math]::Max($chPeak, [double]$s.($c.k)) } }
  $pay = [double]$Power[[string]$s.guc].pay
  if ($pay -lt 1) { $chPeak = 0.0 }   # kanal yükseltmesi yalnızca Güvenli'de genel sesi kısar
  @{ filters = $flt; graphic = $geq; curve = $curve; peak = $peak; preamp = [math]::Round($s.seviye - $pay * $peak - $chPeak, 1) }
}

# ------------------------------------------------------------------ Equalizer APO
$Inv = [Globalization.CultureInfo]::InvariantCulture
function N([double]$v, [string]$f = '0.0') { $v.ToString($f, $Inv) }

function Get-Block($sp) {
  $k = $Kinds[$sp.kind]
  $l = New-Object System.Collections.ArrayList
  $title = "# $($sp.ad) ($($k.ad))"; if ($sp.device_ad) { $title += " - $($sp.device_ad)" }
  [void]$l.Add($title)
  [void]$l.Add($(if ($sp.device) { "Device: $($sp.device)" } else { 'Device: all' }))
  if (-not $sp.settings.acik) { [void]$l.Add('# kapalı (düz ses)'); return ($l -join "`r`n") }
  $an = Get-Analysis $sp
  [void]$l.Add("Preamp: $(N $an.preamp) dB")
  if (@($an.graphic | Where-Object { $_[1] -ne 0 }).Count) {
    [void]$l.Add('GraphicEQ: ' + (($an.graphic | ForEach-Object { "$(N $_[0] '0') $(N $_[1])" }) -join '; '))
  }
  foreach ($x in $an.filters) {
    if ($x[0] -eq 'HP') { [void]$l.Add("Filter: ON HP Fc $(N $x[1] '0') Hz Q $(N $x[3] '0.00')") }
    else { [void]$l.Add("Filter: ON $($x[0]) Fc $(N $x[1] '0') Hz Gain $(N $x[2]) dB Q $(N $x[3] '0.00')") }
  }
  if ($k.k51) {
    $any = $false
    foreach ($c in $Chans) {
      $v = [double]$sp.settings.($c.k)
      if ($v -ne 0) { [void]$l.Add("Channel: $($c.ch)"); [void]$l.Add("Preamp: $(N $v) dB"); $any = $true }
    }
    if ($any) { [void]$l.Add('Channel: all') }
  }
  $l -join "`r`n"
}

function Get-ApoConfig($st) {
  $blocks = New-Object System.Collections.ArrayList
  $act = Get-Active $st
  if (-not $act.device) { [void]$blocks.Add((Get-Block $act)) }   # çıkışı seçilmemiş: varsayılan çıkışa
  foreach ($sp in $st.speakers) { if ($sp.device) { [void]$blocks.Add((Get-Block $sp)) } }
  "# Heloo hoparlör ayarı - Hoparlör Ses Ayarı programı yazar, elle değiştirme.`r`n`r`n" + ($blocks -join "`r`n`r`n") + "`r`n`r`nDevice: all`r`n"
}

function Get-ApoDir {
  foreach ($key in 'HKLM:\SOFTWARE\EqualizerAPO', 'HKLM:\SOFTWARE\WOW6432Node\EqualizerAPO') {
    try { $p = (Get-ItemProperty -Path $key -Name ConfigPath -ErrorAction Stop).ConfigPath; if ($p -and (Test-Path $p)) { return $p } } catch { }
  }
  $p = Join-Path $env:ProgramFiles 'EqualizerAPO\config'
  if (Test-Path $p) { return $p }
  $null
}

function Write-Apo($st) {
  $dir = Get-ApoDir
  if (-not $dir) { return @{ ok = $false; msg = 'Equalizer APO kurulu değil — "Equalizer APO indir" düğmesine bas.' } }
  $text = Get-ApoConfig $st
  try {
    $enc = New-Object Text.UTF8Encoding $true
    [IO.File]::WriteAllText((Join-Path $dir $ApoFile), $text, $enc)
    $main = Join-Path $dir 'config.txt'
    $cur = if (Test-Path $main) { [IO.File]::ReadAllText($main) } else { '' }
    if ($cur -notmatch [regex]::Escape($ApoInclude)) {
      $nl = if ($cur -and -not $cur.EndsWith("`n")) { "`r`n" } else { '' }
      [IO.File]::AppendAllText($main, "$nl$ApoInclude`r`n", (New-Object Text.UTF8Encoding $false))
    }
    @{ ok = $true; msg = 'Uygulandı - ses anında değişti.' }
  } catch [UnauthorizedAccessException] {
    @{ ok = $false; msg = 'Yazma izni yok: programı yönetici olarak aç (sağ tık → PowerShell ile çalıştır, izin penceresine Evet).' }
  } catch {
    @{ ok = $false; msg = "Yazılamadı: $($_.Exception.Message)" }
  }
}

function Get-Devices {
  try {
    @(Get-PnpDevice -Class AudioEndpoint -PresentOnly -ErrorAction Stop | Where-Object { $_.InstanceId -like '*{0.0.0.*' } | ForEach-Object {
        if ($_.InstanceId -match '(\{[0-9A-Fa-f-]{36}\})$') { [pscustomobject]@{ guid = $Matches[1]; ad = $_.FriendlyName } } })
  } catch { @() }
}

# ------------------------------------------------------------------ deneme (pencere yok)
if ($SelfTest) {
  $st = Read-State
  $sp = Get-Active $st
  $sp.settings = New-Settings 'turku'; $sp.settings.bas = 3
  Get-ApoConfig $st
  return
}

# ------------------------------------------------------------------ hata olursa sessizce kapanma: ekrana yaz
Add-Type -AssemblyName System.Windows.Forms, System.Drawing, Microsoft.VisualBasic
$LogFile = Join-Path $AppDir 'hata.log'
function Write-Log([string]$t) {
  try { New-Item -ItemType Directory -Force -Path $AppDir | Out-Null; Add-Content -Path $LogFile -Value "$(Get-Date -Format s) $t" -Encoding UTF8 } catch { }
}
trap {   # betiğin her yerindeki durduran hatayı yakalar (trap bütün betiğe uygulanır)
  $msg = "$($_.Exception.Message)`n`nSatır $($_.InvocationInfo.ScriptLineNumber): $(([string]$_.InvocationInfo.Line).Trim())"
  try { New-Item -ItemType Directory -Force -Path $AppDir | Out-Null; Add-Content -Path $LogFile -Value "$(Get-Date -Format s) $msg" -Encoding UTF8 } catch { }
  Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
  [void][Windows.Forms.MessageBox]::Show("Hoparlör Ses Ayarı açılamadı:`n`n$msg`n`nKayıt: $LogFile`nBu pencerenin ekran görüntüsünü gönder.", 'Hoparlör Ses Ayarı - hata', 'OK', 'Error')
  exit 1
}

# Konsol penceresini gizle. Bu, sürecin İLK ShowWindow çağrısıdır: Windows kısayolun/başlatanın pencere biçimini
# (gizli/küçültülmüş) ilk ShowWindow çağrısına uygular; konsol bunu üstlenince program penceresi normal açılır.
try {
  if (-not ('Heloo.Win' -as [type])) {
    Add-Type -Namespace Heloo -Name Win -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
[DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
'@
  }
  $hw = [Heloo.Win]::GetConsoleWindow()
  if ($hw -ne [IntPtr]::Zero) { [void][Heloo.Win]::ShowWindow($hw, 0) }
} catch { Write-Log "konsol gizlenemedi: $($_.Exception.Message)" }

# ------------------------------------------------------------------ yönetici izni
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $NoElevate -and $PSCommandPath) {
  try {
    Start-Process powershell -Verb RunAs -WindowStyle Minimized -ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-STA', '-File', "`"$PSCommandPath`"", '-NoElevate')
    return
  } catch { Write-Log "yönetici izni verilmedi: $($_.Exception.Message)" }   # izin verilmezse yine açılır; yazarken uyarır
}

# ------------------------------------------------------------------ pencere
[Windows.Forms.Application]::EnableVisualStyles()

# renkler (PowerShell değişken adlarında büyük/küçük harf ayırmaz: başka yerde $renk adı kullanma)
$Renk = @{ bg = [Drawing.Color]::FromArgb(11, 15, 26); card = [Drawing.Color]::FromArgb(20, 27, 45); ink = [Drawing.Color]::FromArgb(238, 242, 251)
  muted = [Drawing.Color]::FromArgb(154, 166, 194); acc = [Drawing.Color]::FromArgb(255, 210, 63); line = [Drawing.Color]::FromArgb(37, 48, 73)
  ok = [Drawing.Color]::FromArgb(79, 209, 197); bad = [Drawing.Color]::FromArgb(255, 107, 107) }
$Font = New-Object Drawing.Font('Segoe UI', 9.5)
$Bold = New-Object Drawing.Font('Segoe UI', 9.5, [Drawing.FontStyle]::Bold)

$script:st = Read-State
$script:loading = $false
$script:an = $null
$script:devs = @()

function L([string]$text, $x, $y, $w = 150, $fnt = $null, $color = $null) {
  if (-not $fnt) { $fnt = $Font }; if (-not $color) { $color = $Renk.ink }
  $l = New-Object Windows.Forms.Label -Property @{ Text = $text; Left = $x; Top = $y; Width = $w; Height = 22; Font = $fnt; ForeColor = $color; BackColor = [Drawing.Color]::Transparent }
  $l
}

$form = New-Object Windows.Forms.Form -Property @{ Text = 'Hoparlör Ses Ayarı'; Width = 1000; Height = 790; BackColor = $Renk.bg; ForeColor = $Renk.ink
  Font = $Font; StartPosition = 'CenterScreen'; FormBorderStyle = 'FixedSingle'; MaximizeBox = $false }

# --- üst: hoparlör
$form.Controls.Add((L 'HOPARLÖR' 16 12 200 $Bold $Renk.muted))
$cbSpk = New-Object Windows.Forms.ComboBox -Property @{ Left = 16; Top = 36; Width = 260; DropDownStyle = 'DropDownList'; Font = $Bold }
$btnAdd = New-Object Windows.Forms.Button -Property @{ Left = 284; Top = 35; Width = 110; Height = 28; Text = '+ Hoparlör ekle'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$btnDel = New-Object Windows.Forms.Button -Property @{ Left = 400; Top = 35; Width = 60; Height = 28; Text = 'Sil'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$chkOn = New-Object Windows.Forms.CheckBox -Property @{ Left = 476; Top = 38; Width = 140; Text = 'Ses ayarı açık'; ForeColor = $Renk.ink }
$btnApo = New-Object Windows.Forms.Button -Property @{ Left = 820; Top = 35; Width = 150; Height = 28; Text = 'Equalizer APO indir'; FlatStyle = 'Flat'; ForeColor = $Renk.acc }
$form.Controls.AddRange(@($cbSpk, $btnAdd, $btnDel, $chkOn, $btnApo))
$form.Controls.Add((L 'Tür:' 16 72 40))
$cbKind = New-Object Windows.Forms.ComboBox -Property @{ Left = 56; Top = 69; Width = 220; DropDownStyle = 'DropDownList' }
$form.Controls.Add((L 'Windows çıkışı:' 290 72 100))
$cbDev = New-Object Windows.Forms.ComboBox -Property @{ Left = 392; Top = 69; Width = 420; DropDownStyle = 'DropDownList' }
$btnDev = New-Object Windows.Forms.Button -Property @{ Left = 820; Top = 68; Width = 150; Height = 28; Text = 'Çıkışları yenile'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$form.Controls.AddRange(@($cbKind, $cbDev, $btnDev))
foreach ($k in $Kinds.Keys) { [void]$cbKind.Items.Add($Kinds[$k].ad) }

# --- en iyi ayarlar + müzik türü (müzik türü paneli aşağıdaki yer açma adımında yerleşir)
$form.Controls.Add((L 'EN İYİ AYARLAR  (üzerine gel: ne yaptığı yazar)' 16 108 600 $Bold $Renk.muted))
$flow = New-Object Windows.Forms.FlowLayoutPanel -Property @{ Left = 16; Top = 130; Width = 955; Height = 78; BackColor = $Renk.bg; AutoScroll = $true }
$flowTur = New-Object Windows.Forms.FlowLayoutPanel -Property @{ Left = 16; Width = 955; Height = 112; BackColor = $Renk.bg; AutoScroll = $true }
$form.Controls.Add($flow)
$tips = New-Object Windows.Forms.ToolTip -Property @{ AutoPopDelay = 15000; InitialDelay = 300 }
$presetBtns = @{}
foreach ($id in $Presets.Keys) {
  $pr = $Presets[$id]; $best = ($pr.grup -eq 'en_iyi')
  $b = New-Object Windows.Forms.Button -Property @{ Text = $pr.ad; Tag = $id; AutoSize = $true; Height = 30; FlatStyle = 'Flat'; ForeColor = $Renk.ink; BackColor = $Renk.card }
  $b.FlatAppearance.BorderColor = $(if ($best) { $Renk.acc } else { $Renk.line })
  if ($pr.ContainsKey('ipucu')) { $tips.SetToolTip($b, $pr.ipucu) }
  $b.Add_Click({ Set-Preset $this.Tag })
  if ($best) { $flow.Controls.Add($b) } else { $flowTur.Controls.Add($b) }
  $presetBtns[$id] = $b
}

# --- sade sürgüler
$form.Controls.Add((L 'SESİNİ KENDİN AYARLA' 16 216 300 $Bold $Renk.muted))
$form.Controls.Add((L 'Ses gücü:' 16 245 140))
$powerBtns = @{}; $px0 = 156
foreach ($id in $Power.Keys) {
  $b = New-Object Windows.Forms.Button -Property @{ Left = $px0; Top = 240; Width = 92; Height = 28; Text = $Power[$id].ad; Tag = $id; FlatStyle = 'Flat'; ForeColor = $Renk.ink; BackColor = $Renk.card }
  $b.Add_Click({ (Get-Active $script:st).settings.guc = $this.Tag; Show-Power; Request-Apply })
  $form.Controls.Add($b); $powerBtns[$id] = $b; $px0 += 98
}
$lblPower = L '' 16 272 470 $Font $Renk.muted; $form.Controls.Add($lblPower)

# Her sürgü 0,5 dB adımla oynar (ok tuşları / fare tekerleği / sürükleme); yanındaki kutuya değer elle yazılabilir.
$tracks = @{}; $nums = @{}; $script:syncing = $false
function New-Num($x, $y, $w, [double]$lo, [double]$hi, $tag) {
  New-Object Windows.Forms.NumericUpDown -Property @{ Left = $x; Top = $y; Width = $w; Minimum = [decimal]$lo; Maximum = [decimal]$hi; DecimalPlaces = 1
    Increment = [decimal]0.5; Tag = $tag; BackColor = $Renk.card; ForeColor = $Renk.acc; Font = $Bold; TextAlign = 'Center' }
}
function Set-Num($num, [double]$v) { $num.Value = [decimal][math]::Max([double]$num.Minimum, [math]::Min([double]$num.Maximum, $v)) }
function Add-Slider([string]$key, [string]$label, $y, [int]$lo = -12, [int]$hi = 12) {
  $form.Controls.Add((L $label 16 ($y + 6) 140))
  $tb = New-Object Windows.Forms.TrackBar -Property @{ Left = 156; Top = $y; Width = 250; Minimum = $lo * 2; Maximum = $hi * 2; TickFrequency = 2
    SmallChange = 1; LargeChange = 2; Tag = $key; BackColor = $Renk.bg }
  $num = New-Num 412 ($y + 3) 70 $lo $hi $key
  $tb.Add_ValueChanged({
      if ($script:loading -or $script:syncing) { return }
      $v = $this.Value / 2.0; (Get-Active $script:st).settings.($this.Tag) = $v
      $script:syncing = $true; Set-Num $script:nums[$this.Tag] $v; $script:syncing = $false; Request-Apply })
  $num.Add_ValueChanged({
      if ($script:loading -or $script:syncing) { return }
      $v = [math]::Round([double]$this.Value * 2) / 2.0; (Get-Active $script:st).settings.($this.Tag) = $v
      $script:syncing = $true; $script:tracks[$this.Tag].Value = [int]($v * 2); $script:syncing = $false; Request-Apply })
  $form.Controls.AddRange(@($tb, $num)); $script:tracks[$key] = $tb; $script:nums[$key] = $num
}
$y = 296
foreach ($x in $Simple) { Add-Slider $x.k $x.ad $y; $y += 40 }
Add-Slider 'seviye' 'Ses seviyesi' $y -20 $LevelMax; $y += 48
$lbl51 = L '5.1 kanal düzeyleri (Z607)' 16 $y 300 $Font $Renk.muted; $form.Controls.Add($lbl51); $y += 24
foreach ($x in $Chans) { Add-Slider $x.k $x.ad $y; $y += 40 }

# --- eğri
$form.Controls.Add((L 'SES EĞRİSİ' 500 216 200 $Bold $Renk.muted))
$pic = New-Object Windows.Forms.PictureBox -Property @{ Left = 500; Top = 240; Width = 470; Height = 230; BackColor = [Drawing.Color]::FromArgb(14, 20, 36) }
$lblPre = L '' 500 476 470 $Font $Renk.muted
$form.Controls.AddRange(@($pic, $lblPre))
$pic.Add_Paint({
    param($s, $e)
    $g = $e.Graphics; $g.SmoothingMode = 'AntiAlias'; $picW = $pic.Width; $picH = $pic.Height; $dbRange = 15.0
    $px = { param($f) [float]([math]::Log($f / 20) / [math]::Log(1000) * $picW) }
    $py = { param($d) [float]($picH / 2 - $d / $dbRange * ($picH / 2 - 10)) }
    $pen = New-Object Drawing.Pen($Renk.line, 1); $br = New-Object Drawing.SolidBrush($Renk.muted); $sf = New-Object Drawing.Font('Segoe UI', 7.5)
    foreach ($f in 50, 100, 200, 500, 1000, 2000, 5000, 10000) { $xx = & $px $f; $g.DrawLine($pen, $xx, 0, $xx, $picH); $g.DrawString($(if ($f -ge 1000) { "$($f / 1000)k" } else { "$f" }), $sf, $br, $xx + 2, $picH - 14) }
    foreach ($d in -12, -6, 0, 6, 12) { $yy = & $py $d; $g.DrawLine($pen, 0, $yy, $picW, $yy); $g.DrawString("$d", $sf, $br, 2, $yy - 13) }
    if (-not $script:an) { return }
    $on = (Get-Active $script:st).settings.acik
    $pts = New-Object 'System.Collections.Generic.List[System.Drawing.PointF]'
    for ($i = 0; $i -lt $CurveFreqs.Count; $i++) { $pts.Add([Drawing.PointF]::new((& $px $CurveFreqs[$i]), (& $py $(if ($on) { $script:an.curve[$i] } else { 0 })))) }
    $cp = New-Object Drawing.Pen($(if ($on) { $Renk.acc } else { $Renk.muted }), 2.5)
    $g.DrawLines($cp, $pts.ToArray())
  })

# --- 10 bant
$form.Controls.Add((L 'GELİŞMİŞ EKOLAYZIR (10 BANT)' 500 506 300 $Bold $Renk.muted))
$bandTracks = @(); $bandNums = @()
function Set-Band([int]$i, [double]$v) {
  $sp = Get-Active $script:st; $sp.settings.bands[$i] = $v; $sp.settings.preset = 'ozel'; Show-Presets; Request-Apply
}
for ($i = 0; $i -lt $Bands.Count; $i++) {
  $x0 = 500 + $i * 47
  $num = New-Num $x0 528 45 -12 12 $i; $num.Font = $Font
  $tb = New-Object Windows.Forms.TrackBar -Property @{ Minimum = -24; Maximum = 24; TickFrequency = 2; SmallChange = 1; LargeChange = 2; Tag = $i; BackColor = $Renk.bg }
  $tb.Orientation = 'Vertical'; $tb.AutoSize = $false; $tb.SetBounds($x0, 554, 44, 144)   # sıra önemli: önce dikey, sonra boyut
  $f = $Bands[$i]; $fl = L $(if ($f -ge 1000) { "$($f / 1000)k" } else { "$f" }) $x0 700 44 $Font $Renk.muted; $fl.TextAlign = 'MiddleCenter'
  $tb.Add_ValueChanged({
      if ($script:loading -or $script:syncing) { return }
      $v = $this.Value / 2.0
      $script:syncing = $true; Set-Num $script:bandNums[$this.Tag] $v; $script:syncing = $false; Set-Band $this.Tag $v })
  $num.Add_ValueChanged({
      if ($script:loading -or $script:syncing) { return }
      $v = [math]::Round([double]$this.Value * 2) / 2.0
      $script:syncing = $true; $script:bandTracks[$this.Tag].Value = [int]($v * 2); $script:syncing = $false; Set-Band $this.Tag $v })
  $form.Controls.AddRange(@($num, $tb, $fl)); $bandTracks += $tb; $bandNums += $num
}
$btnReset = New-Object Windows.Forms.Button -Property @{ Left = 16; Top = $y + 6; Width = 100; Height = 28; Text = 'Sıfırla'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$btnWin = New-Object Windows.Forms.Button -Property @{ Left = 124; Top = $y + 6; Width = 200; Height = 28; Text = 'Windows ses ayarları'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$form.Controls.AddRange(@($btnReset, $btnWin))

$status = L '' 16 724 955 $Bold $Renk.muted
$form.Controls.Add($status)
$tip = L "Daha yüksek ses: Windows ses ayarları → Hoparlörler → Özellikler → Geliştirmeler → 'Ses yüksekliği eşitleme' aç (sesi bozmadan yükseltir)." 16 690 470 $Font $Renk.muted
$tip.Height = 34; $form.Controls.Add($tip)

# ------------------------------------------------------------------ davranış
function Show-Power {
  $cur = [string](Get-Active $script:st).settings.guc
  foreach ($id in $powerBtns.Keys) {
    $on = ($id -eq $cur)
    $powerBtns[$id].BackColor = $(if ($on) { $Renk.acc } else { $Renk.card }); $powerBtns[$id].ForeColor = $(if ($on) { [Drawing.Color]::Black } else { $Renk.ink })
  }
  $lblPower.Text = $Power[$cur].ipucu
}

function Show-Presets {
  $sp = Get-Active $script:st; $cur = $sp.settings.preset; $rec = $Kinds[$sp.kind].oneri
  foreach ($id in $presetBtns.Keys) {
    $on = ($id -eq $cur)
    $presetBtns[$id].Text = $Presets[$id].ad + $(if ($id -eq $rec) { '  ✓ önerilen' } else { '' })
    $presetBtns[$id].BackColor = $(if ($on) { $Renk.acc } else { $Renk.card }); $presetBtns[$id].ForeColor = $(if ($on) { [Drawing.Color]::Black } else { $Renk.ink })
  }
  foreach ($b in $mineFlow.Controls) {
    if ($b -is [Windows.Forms.Button]) {
      $on = ("my:$($b.Tag)" -eq $cur)
      $b.BackColor = $(if ($on) { $Renk.ok } else { $Renk.card }); $b.ForeColor = $(if ($on) { [Drawing.Color]::Black } else { $Renk.ink })
    }
  }
  $btnMineDel.Enabled = ([string]$cur).StartsWith('my:')
}

# ------------------------------------------------------------------ Benim ayarlarım
function Copy-Settings($s) { Repair-Settings ($s | ConvertTo-Json -Depth 4 | ConvertFrom-Json) }

function Build-Mine {
  $mineFlow.Controls.Clear()
  $list = @($script:st.custom)
  if (-not $list.Count) {
    $mineFlow.Controls.Add((L 'Henüz kayıtlı ayarın yok: beğendiğin sesi ayarla, "Ayarımı kaydet"e bas.' 0 0 640 $Font $Renk.muted))
    return
  }
  foreach ($c in $list) {
    $b = New-Object Windows.Forms.Button -Property @{ Text = "★ $($c.ad)"; Tag = $c.id; AutoSize = $true; Height = 30; FlatStyle = 'Flat'; ForeColor = $Renk.ink; BackColor = $Renk.card }
    $b.FlatAppearance.BorderColor = $Renk.ok
    $b.Add_Click({ Load-Custom $this.Tag })
    $mineFlow.Controls.Add($b)
  }
}

function Load-Custom([string]$id) {
  $c = @($script:st.custom | Where-Object { $_.id -eq $id })
  if (-not $c.Count) { return }
  $sp = Get-Active $script:st
  $sp.settings = Copy-Settings $c[0].settings; $sp.settings.preset = "my:$id"
  Load-UI; Request-Apply
  $status.Text = "'$($c[0].ad)' yüklendi."; $status.ForeColor = $Renk.ok
}

function Save-Custom {
  $sp = Get-Active $script:st
  $cur = @($script:st.custom | Where-Object { "my:$($_.id)" -eq $sp.settings.preset })
  $def = $(if ($cur.Count) { $cur[0].ad } else { '' })
  $ad = [Microsoft.VisualBasic.Interaction]::InputBox("Bu ayara bir ad ver (ör. Akşam keyfi, Film gecesi, Türkü bas).`n`nBas, tiz, 10 bant, ses gücü ve kanal düzeyleri birlikte kaydedilir; her hoparlörde kullanabilirsin.`nAynı adı yazarsan güncellenir.", 'Ayarımı kaydet', $def)
  $ad = $ad.Trim(); if (-not $ad) { return }
  if ($ad.Length -gt 40) { $ad = $ad.Substring(0, 40) }
  $old = @($script:st.custom | Where-Object { $_.ad -ieq $ad })
  if ($old.Count) { $id = $old[0].id }
  else { $ids = @($script:st.custom | ForEach-Object { $_.id }); $n = 1; do { $id = "ayar$n"; $n++ } while ($ids -contains $id) }
  $snap = Copy-Settings $sp.settings; $snap.preset = "my:$id"
  $script:st.custom = @(@($script:st.custom | Where-Object { $_.id -ne $id }) + [pscustomobject]@{ id = $id; ad = $ad; settings = $snap })
  $sp.settings.preset = "my:$id"
  Build-Mine; Show-Presets; Request-Apply
  $status.Text = "'$ad' " + $(if ($old.Count) { 'güncellendi.' } else { 'kaydedildi.' }); $status.ForeColor = $Renk.ok
}

function Remove-Custom {
  $sp = Get-Active $script:st
  $c = @($script:st.custom | Where-Object { "my:$($_.id)" -eq $sp.settings.preset })
  if (-not $c.Count) { return }
  if ([Windows.Forms.MessageBox]::Show("'$($c[0].ad)' silinsin mi?`n(Şu anki sesin değişmez.)", 'Ayarımı sil', 'YesNo') -ne 'Yes') { return }
  $script:st.custom = @($script:st.custom | Where-Object { $_.id -ne $c[0].id })
  foreach ($x in $script:st.speakers) { if ($x.settings.preset -eq "my:$($c[0].id)") { $x.settings.preset = 'ozel' } }
  Build-Mine; Show-Presets; Save-State $script:st
  $status.Text = "'$($c[0].ad)' silindi."; $status.ForeColor = $Renk.muted
}

function Fill-Devices {
  $sp = Get-Active $script:st
  $cbDev.Items.Clear(); [void]$cbDev.Items.Add("Windows'ta seçili çıkış")
  $list = @($script:devs)
  if ($sp.device -and -not ($list | Where-Object { $_.guid -eq $sp.device })) { $list += [pscustomobject]@{ guid = $sp.device; ad = $(if ($sp.device_ad) { $sp.device_ad } else { $sp.device }) } }
  $script:devList = $list
  foreach ($d in $list) { [void]$cbDev.Items.Add($d.ad) }
  $idx = 0; for ($i = 0; $i -lt $list.Count; $i++) { if ($list[$i].guid -eq $sp.device) { $idx = $i + 1 } }
  $cbDev.SelectedIndex = $idx
}

function Load-UI {
  $script:loading = $true
  $sp = Get-Active $script:st; $s = $sp.settings; $k = $Kinds[$sp.kind]
  $cbSpk.Items.Clear(); foreach ($x in $script:st.speakers) { [void]$cbSpk.Items.Add($x.ad) }
  $cbSpk.SelectedIndex = [array]::IndexOf(@($script:st.speakers | ForEach-Object { $_.id }), $sp.id)
  $cbKind.SelectedIndex = [array]::IndexOf(@($Kinds.Keys), $sp.kind)
  $chkOn.Checked = [bool]$s.acik
  foreach ($key in @($script:tracks.Keys)) {
    $tb = $script:tracks[$key]; $tb.Value = [int][math]::Max($tb.Minimum, [math]::Min($tb.Maximum, [math]::Round([double]$s.$key * 2)))
    Set-Num $script:nums[$key] ([double]$s.$key)
  }
  foreach ($x in $Chans) { $script:tracks[$x.k].Enabled = $k.k51; $script:nums[$x.k].Enabled = $k.k51 }
  $lbl51.Text = $(if ($k.k51) { '5.1 kanal düzeyleri (Windows: 5.1 Surround yapılandır)' } else { '5.1 kanal düzeyleri yalnızca 5.1 hoparlörde' })
  for ($i = 0; $i -lt $Bands.Count; $i++) { $bandTracks[$i].Value = [int][math]::Round([double]$s.bands[$i] * 2); Set-Num $bandNums[$i] ([double]$s.bands[$i]) }
  Show-Presets; Show-Power; Fill-Devices
  $script:loading = $false
}

$timer = New-Object Windows.Forms.Timer -Property @{ Interval = 300 }
function Request-Apply { $timer.Stop(); $timer.Start() }
$timer.Add_Tick({
    $timer.Stop()
    Save-State $script:st
    $script:an = Get-Analysis (Get-Active $script:st)
    $lblPre.Text = "Genel ses: $(N $script:an.preamp) dB" + $(if ($script:an.preamp -lt 0) { "  (cızırtı koruması; daha yüksek ses için 'Ses gücü: Yüksek' ya da 'Ses seviyesi')" } else { '' })
    $pic.Invalidate()
    $r = Write-Apo $script:st
    $status.Text = $r.msg; $status.ForeColor = $(if ($r.ok) { $Renk.ok } else { $Renk.bad })
    $btnApo.Visible = -not (Get-ApoDir)
  })

function Set-Preset([string]$id) {
  $sp = Get-Active $script:st; $old = $sp.settings; $new = New-Settings $id
  foreach ($key in 'bas', 'orta', 'vokal', 'tiz', 'seviye', 'guc', 'sub', 'arka', 'acik') {
    if (-not ($key -eq 'sub' -and $Presets[$id].ContainsKey('sub'))) { $new.$key = $old.$key }   # kendi sürgülerin korunur (hazırın subu hariç)
  }
  $sp.settings = $new; Load-UI; Request-Apply
  $pr = $Presets[$id]
  $status.Text = $pr.ad + $(if ($pr.ContainsKey('ipucu')) { ': ' + $pr.ipucu } else { '' }); $status.ForeColor = $Renk.ok
}

$cbSpk.Add_SelectedIndexChanged({ if ($script:loading -or $cbSpk.SelectedIndex -lt 0) { return }; $script:st.active = $script:st.speakers[$cbSpk.SelectedIndex].id; Load-UI; Request-Apply })
$cbKind.Add_SelectedIndexChanged({ if ($script:loading) { return }; (Get-Active $script:st).kind = @($Kinds.Keys)[$cbKind.SelectedIndex]; Load-UI; Request-Apply })
$cbDev.Add_SelectedIndexChanged({
    if ($script:loading) { return }
    $sp = Get-Active $script:st
    if ($cbDev.SelectedIndex -le 0) { $sp.device = ''; $sp.device_ad = '' } else { $d = $script:devList[$cbDev.SelectedIndex - 1]; $sp.device = $d.guid; $sp.device_ad = $d.ad }
    Request-Apply })
$chkOn.Add_CheckedChanged({ if ($script:loading) { return }; (Get-Active $script:st).settings.acik = $chkOn.Checked; Request-Apply })
$btnReset.Add_Click({ $sp = Get-Active $script:st; $g = $sp.settings.guc; $sp.settings = New-Settings 'duz'; $sp.settings.guc = $g; Load-UI; Request-Apply })
$btnWin.Add_Click({ Start-Process control.exe -ArgumentList 'mmsys.cpl' })
$btnApo.Add_Click({ Start-Process $ApoUrl })
$btnDev.Add_Click({ $script:devs = Get-Devices; $script:loading = $true; Fill-Devices; $script:loading = $false; $status.Text = "$(@($script:devs).Count) ses çıkışı bulundu"; $status.ForeColor = $Renk.muted })
$btnAdd.Add_Click({
    $ad = [Microsoft.VisualBasic.Interaction]::InputBox('Hoparlörün adı (ör. Masa hoparlörü, Soundbar):', 'Hoparlör ekle', '')
    if (-not $ad.Trim()) { return }
    $ids = @($script:st.speakers | ForEach-Object { $_.id }); $n = 1
    do { $id = "hoparlor$n"; $n++ } while ($ids -contains $id)
    $script:st.speakers = @($script:st.speakers) + (New-Speaker $id $ad.Trim() 'masaustu')
    $script:st.active = $id; Load-UI; Request-Apply
    $status.Text = 'Eklendi: türünü ve Windows çıkışını seç.'; $status.ForeColor = $Renk.ok
  })
$btnDel.Add_Click({
    if (@($script:st.speakers).Count -lt 2) { return }
    $sp = Get-Active $script:st
    if ([Windows.Forms.MessageBox]::Show("$($sp.ad) silinsin mi?", 'Sil', 'YesNo') -ne 'Yes') { return }
    $script:st.speakers = @($script:st.speakers | Where-Object { $_.id -ne $sp.id }); $script:st.active = $script:st.speakers[0].id
    Load-UI; Request-Apply
  })

# --- Benim ayarlarım: müzik türlerinin altına yer aç (alttaki her şey aşağı kayar)
$turH = 118   # müzik türü paneli için
$shift = 76 + $turH
foreach ($ctl in @($form.Controls)) { if ($ctl.Top -ge 210) { $ctl.Top += $shift } }
$form.Height += $shift
$form.Controls.Add((L 'MÜZİK TÜRÜ' 16 212 200 $Bold $Renk.muted))
$flowTur.Top = 234; $form.Controls.Add($flowTur)
$form.Controls.Add((L 'BENİM AYARLARIM' 16 (212 + $turH) 200 $Bold $Renk.muted))
$mineFlow = New-Object Windows.Forms.FlowLayoutPanel -Property @{ Left = 16; Top = (234 + $turH); Width = 690; Height = 50; BackColor = $Renk.bg; AutoScroll = $true }
$btnMineSave = New-Object Windows.Forms.Button -Property @{ Left = 714; Top = (236 + $turH); Width = 130; Height = 30; Text = 'Ayarımı kaydet'; FlatStyle = 'Flat'; ForeColor = [Drawing.Color]::Black; BackColor = $Renk.acc }
$btnMineDel = New-Object Windows.Forms.Button -Property @{ Left = 850; Top = (236 + $turH); Width = 120; Height = 30; Text = 'Seçili ayarı sil'; FlatStyle = 'Flat'; ForeColor = $Renk.ink }
$form.Controls.AddRange(@($mineFlow, $btnMineSave, $btnMineDel))
$btnMineSave.Add_Click({ Save-Custom })
# ekran küçükse pencere ekrana sığsın, içerik kaydırılsın
$wa = [Windows.Forms.Screen]::PrimaryScreen.WorkingArea
if ($form.Height -gt $wa.Height) { $form.Height = $wa.Height; $form.AutoScroll = $true }
$btnMineDel.Add_Click({ Remove-Custom })

$form.Add_Shown({
    $form.WindowState = 'Normal'; $form.TopMost = $true; $form.Activate(); $form.TopMost = $false   # öne getir
    Build-Mine
    $script:devs = Get-Devices
    Load-UI; Request-Apply
    if (-not (Get-ApoDir)) {
      $r = [Windows.Forms.MessageBox]::Show("Ses ayarı için ücretsiz Equalizer APO gerekiyor.`n`nKurulumda Z607'nin bağlı olduğu çıkışı (Hoparlörler) işaretle ve bilgisayarı yeniden başlat.`n`nİndirme sayfası açılsın mı?", 'Equalizer APO', 'YesNo', 'Information')
      if ($r -eq 'Yes') { Start-Process $ApoUrl }
    }
  })
$form.Add_FormClosing({ $timer.Stop(); Save-State $script:st; [void](Write-Apo $script:st) })
$form.ShowInTaskbar = $true
$form.Icon = [Drawing.SystemIcons]::Information
try { $form.Icon = [Drawing.Icon]::ExtractAssociatedIcon((Join-Path $env:SystemRoot 'System32\SndVol.exe')) } catch { }
[void]$form.ShowDialog()
if ($Error.Count) { Write-Log ("olay hataları: " + (($Error | Select-Object -First 5 | ForEach-Object { $_.ToString() }) -join ' | ')) }
