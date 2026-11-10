<#
.SYNOPSIS
  Aktarım — bilgisayar ile telefon (iPhone/iOS ve Samsung/Android) arasında dosya, fotoğraf,
  video, belge ve yazı aktarımı. Python gerekmez; Windows'taki PowerShell 5.1 (ya da 7) yeter.

.DESCRIPTION
  Yerel ağda küçük bir sunucu açar. Telefon aynı Wi-Fi ağında QR kodu okutarak tarayıcıdan bağlanır.
  Silinen öğeler "Sonradan Sil" kutusuna gider; 1 hafta / 2 hafta / 1 ay boyunca geri yüklenebilir,
  süre dolunca kendiliğinden silinir. Veri biçimi Python sürümüyle (aktarim.py) aynıdır.

.EXAMPLE
  .\Aktarim.ps1                       # sunucuyu başlat, tarayıcıyı aç
  .\Aktarim.ps1 -Ekle dosya1 klasor2  # çalışan sunucuya dosya gönder
  .\Aktarim.ps1 -GonderKur            # sağ tık → Gönder → "Telefona gönder (Aktarım)"
  .\Aktarim.ps1 -GuvenlikDuvari       # (yönetici) güvenlik duvarına izin kuralı ekle
#>
[CmdletBinding(PositionalBinding = $false)]
param(
  [string]$Klasor,
  [int]$Port = 0,
  [switch]$TarayiciAcma,
  [switch]$Ekle,
  [switch]$GonderKur,
  [switch]$GuvenlikDuvari,
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Dosyalar
)

$ErrorActionPreference = 'Stop'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------------------------------------------------------------------------
# Ortak işlevler: hem ana süreçte hem her istek için açılan runspace'lerde çalışır.
# ---------------------------------------------------------------------------
$LibText = @'
$RetentionChoices = @(7, 14, 30)
$Day = 86400
$Utf8 = New-Object System.Text.UTF8Encoding $false
try { Add-Type -AssemblyName System.Web -ErrorAction Stop } catch {}

function Now-Unix { [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0 }
function New-Id { [guid]::NewGuid().ToString('N').Substring(0, 12) }

function Lock-Do($S, [scriptblock]$Block) {
  [System.Threading.Monitor]::Enter($S.Lock)
  try { & $Block } finally { [System.Threading.Monitor]::Exit($S.Lock) }
}

function Write-JsonFile([string]$Path, $Data) {
  $json = ConvertTo-Json -InputObject $Data -Depth 6
  if ($null -eq $json -or $json -eq '') { $json = '[]' }
  $tmp = "$Path.tmp"
  [IO.File]::WriteAllText($tmp, $json, $Utf8)
  if (Test-Path -LiteralPath $Path) {
    try { [IO.File]::Replace($tmp, $Path, [NullString]::Value) }
    catch { [IO.File]::Copy($tmp, $Path, $true); [IO.File]::Delete($tmp) }
  } else { [IO.File]::Move($tmp, $Path) }
}

function ConvertTo-Hash($o) {
  $h = @{}
  foreach ($p in $o.PSObject.Properties) { $h[$p.Name] = $p.Value }
  $h
}

function Get-Device([string]$Ua) {
  if (-not $Ua) { return 'Cihaz' }
  if ($Ua -match 'iPhone') { return 'iPhone' }
  if ($Ua -match 'iPad' -or ($Ua -match 'Macintosh' -and $Ua -match 'Mobile')) { return 'iPad' }
  if ($Ua -match 'SM-|Samsung') { return 'Samsung' }
  if ($Ua -match 'Android') { return 'Android' }
  if ($Ua -match 'Windows|Linux') { return 'Bilgisayar' }
  if ($Ua -match 'Macintosh') { return 'Mac' }
  'Cihaz'
}

function Get-SafeName([string]$Name) {
  if (-not $Name) { $Name = '' }
  $Name = ($Name -replace '\\', '/').Split('/')[-1]
  $Name = ($Name -replace '[\x00-\x1f<>:"|?*]', '_').Trim(' ', '.')
  if ($Name.Length -gt 180) { $Name = $Name.Substring(0, 180) }
  if (-not $Name) { $Name = 'dosya' }
  $Name
}

function Get-Mime([string]$Name) {
  $ext = [IO.Path]::GetExtension($Name).ToLowerInvariant()
  $map = @{ '.jpg'='image/jpeg'; '.jpeg'='image/jpeg'; '.png'='image/png'; '.gif'='image/gif'; '.webp'='image/webp';
            '.heic'='image/heic'; '.heif'='image/heif'; '.mp4'='video/mp4'; '.mov'='video/quicktime'; '.m4v'='video/mp4';
            '.webm'='video/webm'; '.mp3'='audio/mpeg'; '.m4a'='audio/mp4'; '.wav'='audio/wav'; '.pdf'='application/pdf';
            '.txt'='text/plain'; '.zip'='application/zip'; '.docx'='application/vnd.openxmlformats-officedocument.wordprocessingml.document';
            '.xlsx'='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'; '.svg'='image/svg+xml' }
  if ($map.ContainsKey($ext)) { return $map[$ext] }
  try { return [System.Web.MimeMapping]::GetMimeMapping($Name) } catch { return 'application/octet-stream' }
}

function New-Shared([string]$Root) {
  $files = Join-Path $Root 'files'
  [void][IO.Directory]::CreateDirectory($files)
  $S = [hashtable]::Synchronized(@{})
  $S.Root = $Root; $S.Files = $files; $S.Lock = New-Object object; $S.Version = 0
  $S.Meta = Join-Path $Root 'items.json'; $S.CfgPath = Join-Path $Root 'ayarlar.json'
  $S.Items = New-Object System.Collections.ArrayList
  $bytes = New-Object byte[] 9
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $token = [Convert]::ToBase64String($bytes).Replace('+', '-').Replace('/', '_').TrimEnd('=')
  $S.Cfg = @{ token = $token; retention_days = 14; port = 8765 }
  if (Test-Path -LiteralPath $S.CfgPath) {
    try { $c = ConvertFrom-Json ([IO.File]::ReadAllText($S.CfgPath)); foreach ($p in $c.PSObject.Properties) { $S.Cfg[$p.Name] = $p.Value } } catch {}
  }
  Write-JsonFile $S.CfgPath $S.Cfg
  if (Test-Path -LiteralPath $S.Meta) {
    try { foreach ($o in (ConvertFrom-Json ([IO.File]::ReadAllText($S.Meta)))) { if ($o) { [void]$S.Items.Add((ConvertTo-Hash $o)) } } } catch {}
  }
  [void](Remove-Expired $S)
  $S
}

function Save-Items($S) {
  $S.Version = [int]$S.Version + 1
  Write-JsonFile $S.Meta @($S.Items.ToArray())
}

function Find-Item($S, [string]$Id) {
  foreach ($i in $S.Items) { if ($i.id -eq $Id) { return $i } }
  $null
}

function Remove-ItemNow($S, $Item) {
  if ($Item.kind -eq 'file') {
    $p = Join-Path $S.Files $Item.file
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
  }
  $S.Items.Remove($Item)
}

function Remove-Expired($S) {
  $now = Now-Unix
  Lock-Do $S {
    $gone = @($S.Items | Where-Object { $_.expires_at -and [double]$_.expires_at -le $now })
    foreach ($g in $gone) { Remove-ItemNow $S $g }
    if ($gone.Count) { Save-Items $S }
    $gone.Count
  }
}

function Add-FileFromStream($S, [string]$Name, $Stream, [long]$Length, [string]$Source, [string]$Mime) {
  $Name = Get-SafeName $Name
  $id = New-Id
  $ext = [IO.Path]::GetExtension($Name)
  if ($ext.Length -gt 12) { $ext = $ext.Substring(0, 12) }
  $fname = "$id$ext"
  $final = Join-Path $S.Files $fname
  $tmp = "$final.part"
  $written = [long]0
  $buf = New-Object byte[] 1048576
  $fs = [IO.File]::Open($tmp, 'Create', 'Write')
  try {
    while ($written -lt $Length) {
      $want = [int][Math]::Min($buf.Length, $Length - $written)
      $n = $Stream.Read($buf, 0, $want)
      if ($n -le 0) { break }
      $fs.Write($buf, 0, $n)
      $written += $n
    }
  } finally { $fs.Dispose() }
  if ($written -ne $Length) { Remove-Item -LiteralPath $tmp -Force; throw 'aktarım yarıda kesildi' }
  [IO.File]::Move($tmp, $final)
  if (-not $Mime -or $Mime -eq 'application/x-www-form-urlencoded' -or $Mime -eq 'application/octet-stream') { $Mime = Get-Mime $Name }
  $item = @{ id = $id; created = (Now-Unix); deleted_at = $null; expires_at = $null; kind = 'file'; name = $Name;
             file = $fname; size = $written; mime = $Mime; source = $Source }
  Lock-Do $S { [void]$S.Items.Add($item); Save-Items $S }
  $item
}

function Add-Text($S, [string]$Text, [string]$Source) {
  if ($null -eq $Text) { $Text = '' }
  $Text = $Text.Trim()
  if (-not $Text) { throw [ArgumentException]'boş yazı' }
  if ($Text.Length -gt 1000000) { throw [ArgumentException]'yazı çok uzun' }
  $first = ($Text -split "`r?`n")[0]
  if ($first.Length -gt 60) { $first = $first.Substring(0, 60) }
  $item = @{ id = (New-Id); created = (Now-Unix); deleted_at = $null; expires_at = $null; kind = 'text'; text = $Text;
             name = $first; size = $Utf8.GetByteCount($Text); source = $Source }
  Lock-Do $S { [void]$S.Items.Add($item); Save-Items $S }
  $item
}

function Test-Days($Days) {
  if ($RetentionChoices -notcontains [int]$Days) { throw [ArgumentException]'süre 7, 14 ya da 30 gün olmalı' }
}

function Set-SoftDelete($S, [string]$Id, $Days) {
  if (-not $Days) { $Days = [int]$S.Cfg.retention_days }
  Test-Days $Days
  Lock-Do $S {
    $it = Find-Item $S $Id
    if (-not $it) { throw [Collections.Generic.KeyNotFoundException]'öğe bulunamadı' }
    $now = Now-Unix
    if (-not $it.deleted_at) { $it.deleted_at = $now }
    $it.expires_at = $now + [int]$Days * $Day
    $it.retention_days = [int]$Days
    Save-Items $S
    $it
  }
}

function Set-Restore($S, [string]$Id) {
  Lock-Do $S {
    $it = Find-Item $S $Id
    if (-not $it) { throw [Collections.Generic.KeyNotFoundException]'öğe bulunamadı' }
    $it.deleted_at = $null; $it.expires_at = $null; $it.Remove('retention_days')
    Save-Items $S
    $it
  }
}

function Remove-Hard($S, [string]$Id) {
  Lock-Do $S {
    $it = Find-Item $S $Id
    if (-not $it) { throw [Collections.Generic.KeyNotFoundException]'öğe bulunamadı' }
    Remove-ItemNow $S $it
    Save-Items $S
  }
}

function Clear-Bin($S) {
  Lock-Do $S {
    $gone = @($S.Items | Where-Object { $_.deleted_at })
    foreach ($g in $gone) { Remove-ItemNow $S $g }
    if ($gone.Count) { Save-Items $S }
    $gone.Count
  }
}

function Get-Listing($S) {
  Lock-Do $S {
    $all = @($S.Items.ToArray())
    $active = @($all | Where-Object { -not $_.deleted_at } | Sort-Object { [double]$_.created } -Descending)
    $bin = @($all | Where-Object { $_.deleted_at } | Sort-Object { [double]$_.expires_at })
    $total = [long]0
    foreach ($i in $all) { if ($i.size) { $total += [long]$i.size } }
    [ordered]@{ items = $active; bin = $bin; version = [int]$S.Version; retention_days = [int]$S.Cfg.retention_days;
                choices = $RetentionChoices; now = (Now-Unix); total_size = $total }
  }
}

# ---------------- HTTP ----------------

function Send-Bytes($Out, [int]$Status, [string]$Reason, [hashtable]$Headers, [byte[]]$Body) {
  $sb = New-Object Text.StringBuilder
  [void]$sb.Append("HTTP/1.1 $Status $Reason`r`n")
  foreach ($k in $Headers.Keys) { [void]$sb.Append("${k}: $($Headers[$k])`r`n") }
  if ($null -ne $Body) { [void]$sb.Append("Content-Length: $($Body.Length)`r`n") }
  [void]$sb.Append("Connection: close`r`n`r`n")
  $h = [Text.Encoding]::ASCII.GetBytes($sb.ToString())
  $Out.Write($h, 0, $h.Length)
  if ($null -ne $Body -and $Body.Length) { $Out.Write($Body, 0, $Body.Length) }
}

function Send-Json($Out, $Data, [int]$Status = 200) {
  $json = ConvertTo-Json -InputObject $Data -Depth 6 -Compress
  $reason = @{ 200 = 'OK'; 201 = 'Created'; 400 = 'Bad Request'; 401 = 'Unauthorized'; 404 = 'Not Found'; 411 = 'Length Required'; 500 = 'Internal Server Error' }[$Status]
  Send-Bytes $Out $Status $reason @{ 'Content-Type' = 'application/json; charset=utf-8'; 'Cache-Control' = 'no-store' } ($Utf8.GetBytes($json))
}

function Send-Error($Out, [int]$Status, [string]$Msg) { Send-Json $Out @{ error = $Msg } $Status }

function Read-Exact($Stream, [int]$Count) {
  $buf = New-Object byte[] $Count
  $off = 0
  while ($off -lt $Count) {
    $n = $Stream.Read($buf, $off, $Count - $off)
    if ($n -le 0) { break }
    $off += $n
  }
  $buf
}

function Read-JsonBody($Stream, $Req) {
  $n = 0
  if ($Req.Headers['content-length']) { $n = [int]$Req.Headers['content-length'] }
  if ($n -gt 4000000) { throw [ArgumentException]'istek çok büyük' }
  if ($n -le 0) { return New-Object psobject }
  $obj = ConvertFrom-Json ($Utf8.GetString((Read-Exact $Stream $n)))
  if ($null -eq $obj) { $obj = New-Object psobject }
  $obj
}

function Read-Request($Stream) {
  $ms = New-Object IO.MemoryStream
  $last = 0
  while ($true) {
    $b = $Stream.ReadByte()
    if ($b -lt 0) { return $null }
    $ms.WriteByte([byte]$b)
    $last = ($last -shl 8) -bor $b   # Int32: yalnız son 4 bayt kalır
    if ($last -eq 0x0D0A0D0A) { break }
    if ($ms.Length -gt 65536) { return $null }
  }
  $lines = [Text.Encoding]::GetEncoding(28591).GetString($ms.ToArray()) -split "`r`n"
  $parts = $lines[0].Split(' ')
  if ($parts.Count -lt 2) { return $null }
  $headers = @{}
  foreach ($l in $lines[1..($lines.Count - 1)]) {
    $i = $l.IndexOf(':')
    if ($i -gt 0) { $headers[$l.Substring(0, $i).Trim().ToLowerInvariant()] = $l.Substring($i + 1).Trim() }
  }
  $target = $parts[1]
  $path = $target; $query = @{}
  $q = $target.IndexOf('?')
  if ($q -ge 0) {
    $path = $target.Substring(0, $q)
    foreach ($kv in $target.Substring($q + 1).Split('&')) {
      $e = $kv.IndexOf('=')
      if ($e -gt 0) { $query[[Uri]::UnescapeDataString($kv.Substring(0, $e))] = [Uri]::UnescapeDataString($kv.Substring($e + 1).Replace('+', ' ')) }
    }
  }
  @{ Method = $parts[0].ToUpperInvariant(); Path = [Uri]::UnescapeDataString($path); Query = $query; Headers = $headers }
}

function Test-Token($S, $Req) {
  $t = [string]$S.Cfg.token
  if ($Req.Query['k'] -eq $t) { return $true }
  if ($Req.Headers['x-aktarim-key'] -eq $t) { return $true }
  $c = $Req.Headers['cookie']
  if ($c) { foreach ($p in $c.Split(';')) { if ($p.Trim() -eq "aktarim=$t") { return $true } } }
  $false
}

function Send-Static($S, $Out, [string]$Name, [bool]$SetCookie) {
  $p = Join-Path $S.Web $Name
  $types = @{ '.html' = 'text/html; charset=utf-8'; '.js' = 'text/javascript; charset=utf-8'; '.css' = 'text/css; charset=utf-8';
              '.svg' = 'image/svg+xml'; '.webmanifest' = 'application/manifest+json' }
  $h = @{ 'Content-Type' = $types[[IO.Path]::GetExtension($p)]; 'Cache-Control' = 'no-cache' }
  if ($SetCookie) { $h['Set-Cookie'] = "aktarim=$($S.Cfg.token); Path=/; Max-Age=31536000; SameSite=Strict; HttpOnly" }
  Send-Bytes $Out 200 'OK' $h ([IO.File]::ReadAllBytes($p))
}

function Send-Locked($Out) {
  $html = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Aktarım</title>" +
          "<body style='font-family:-apple-system,system-ui;padding:40px 20px;text-align:center;color:#1c1c1e'><h2>Aktarım</h2>" +
          "<p>Bağlanmak için bilgisayardaki Aktarım ekranında görünen QR kodunu telefonunun kamerasıyla okut.</p>"
  Send-Bytes $Out 403 'Forbidden' @{ 'Content-Type' = 'text/html; charset=utf-8' } ($Utf8.GetBytes($html))
}

function Send-FileItem($S, $Out, $Req, [string]$Id) {
  $it = Lock-Do $S { Find-Item $S $Id }
  if (-not $it -or $it.kind -ne 'file') { return Send-Error $Out 404 'dosya yok' }
  $p = Join-Path $S.Files $it.file
  if (-not (Test-Path -LiteralPath $p)) { return Send-Error $Out 404 'dosya diskte yok' }
  $fs = [IO.File]::Open($p, 'Open', 'Read', 'ReadWrite')
  try {
    $size = $fs.Length; $start = [long]0; $end = $size - 1; $status = 200; $reason = 'OK'
    $rng = $Req.Headers['range']
    if ($rng -and $size -gt 0 -and $rng -match '^bytes=(\d*)-(\d*)$') {
      if ($Matches[1]) { $start = [long]$Matches[1]; if ($Matches[2]) { $end = [Math]::Min([long]$Matches[2], $size - 1) } }
      elseif ($Matches[2]) { $start = [Math]::Max([long]0, $size - [long]$Matches[2]) }
      if ($start -gt $end) { return Send-Bytes $Out 416 'Range Not Satisfiable' @{ 'Content-Range' = "bytes */$size" } (New-Object byte[] 0) }
      $status = 206; $reason = 'Partial Content'
    }
    $disp = 'inline'; if ($Req.Query['dl']) { $disp = 'attachment' }
    $len = [long]0; if ($size -gt 0) { $len = $end - $start + 1 }
    $mime = $it.mime; if (-not $mime) { $mime = 'application/octet-stream' }
    $h = @{ 'Content-Type' = $mime; 'Accept-Ranges' = 'bytes'; 'Content-Length' = $len;
            'Content-Disposition' = "$disp; filename*=UTF-8''$([Uri]::EscapeDataString($it.name))"; 'Cache-Control' = 'private, max-age=3600' }
    if ($status -eq 206) { $h['Content-Range'] = "bytes $start-$end/$size" }
    Send-Bytes $Out $status $reason $h $null
    if ($Req.Method -eq 'HEAD' -or $len -eq 0) { return }
    [void]$fs.Seek($start, 'Begin')
    $buf = New-Object byte[] 1048576
    $remaining = $len
    while ($remaining -gt 0) {
      $n = $fs.Read($buf, 0, [int][Math]::Min($buf.Length, $remaining))
      if ($n -le 0) { break }
      $Out.Write($buf, 0, $n)
      $remaining -= $n
    }
  } finally { $fs.Dispose() }
}

$Static = @{ '/' = 'index.html'; '/app.js' = 'app.js'; '/style.css' = 'style.css'; '/manifest.webmanifest' = 'manifest.webmanifest'; '/icon.svg' = 'icon.svg' }

function Invoke-Route($S, $Req, $In, $Out) {
  $path = $Req.Path
  $src = Get-Device $Req.Headers['user-agent']
  if ($Req.Method -eq 'GET' -or $Req.Method -eq 'HEAD') {
    if ($Static.ContainsKey($path)) {
      if ($path -eq '/' -and -not (Test-Token $S $Req)) { return Send-Locked $Out }
      return Send-Static $S $Out $Static[$path] ($path -eq '/')
    }
    if (-not (Test-Token $S $Req)) { return Send-Error $Out 401 'bağlantı anahtarı gerekli — QR kodunu yeniden okutun' }
    if ($path -eq '/api/items') {
      $json = Lock-Do $S { ConvertTo-Json -InputObject (Get-Listing $S) -Depth 6 -Compress }
      return Send-Bytes $Out 200 'OK' @{ 'Content-Type' = 'application/json; charset=utf-8'; 'Cache-Control' = 'no-store' } ($Utf8.GetBytes($json))
    }
    if ($path -eq '/api/version') { return Send-Json $Out @{ version = [int]$S.Version } }
    if ($path -eq '/api/info') { return Send-Json $Out @{ urls = @($S.Urls); token = $S.Cfg.token; device = $src; data_dir = $S.Root } }
    if ($path -match '^/api/file/([0-9a-f]{12})(/.*)?$') { return Send-FileItem $S $Out $Req $Matches[1] }
    return Send-Error $Out 404 'bulunamadı'
  }
  if ($Req.Method -ne 'POST') { return Send-Error $Out 404 'bulunamadı' }
  if (-not (Test-Token $S $Req)) { return Send-Error $Out 401 'bağlantı anahtarı gerekli' }
  try {
    if ($path -eq '/api/upload') {
      if (-not $Req.Headers['content-length']) { return Send-Error $Out 411 'Content-Length gerekli' }
      $name = 'dosya'
      if ($Req.Headers['x-filename']) { $name = [Uri]::UnescapeDataString($Req.Headers['x-filename']) }
      $from = $src; if ($Req.Headers['x-source']) { $from = $Req.Headers['x-source'] }
      $item = Add-FileFromStream $S $name $In ([long]$Req.Headers['content-length']) $from $Req.Headers['content-type']
      return Send-Json $Out $item 201
    }
    $data = Read-JsonBody $In $Req
    switch ($path) {
      '/api/text'      { return Send-Json $Out (Add-Text $S ([string]$data.text) $src) 201 }
      '/api/delete'    { return Send-Json $Out (Set-SoftDelete $S ([string]$data.id) $data.days) }
      '/api/restore'   { return Send-Json $Out (Set-Restore $S ([string]$data.id)) }
      '/api/purge'     { Remove-Hard $S ([string]$data.id); return Send-Json $Out @{ ok = $true } }
      '/api/empty-bin' { return Send-Json $Out @{ removed = (Clear-Bin $S) } }
      '/api/settings'  {
        Test-Days $data.retention_days
        Lock-Do $S { $S.Cfg.retention_days = [int]$data.retention_days; Write-JsonFile $S.CfgPath $S.Cfg; $S.Version = [int]$S.Version + 1 }
        return Send-Json $Out @{ retention_days = [int]$S.Cfg.retention_days }
      }
    }
    return Send-Error $Out 404 'bulunamadı'
  } catch [Collections.Generic.KeyNotFoundException] {
    return Send-Error $Out 404 'öğe bulunamadı'
  } catch [ArgumentException] {
    return Send-Error $Out 400 $_.Exception.Message
  } catch {
    return Send-Error $Out 500 "hata: $($_.Exception.Message)"
  }
}

function Invoke-Client($Client, $S) {
  try {
    $Client.ReceiveTimeout = 30000
    $Client.SendTimeout = 60000
    $ns = $Client.GetStream()
    $in = New-Object IO.BufferedStream($ns, 65536)
    $req = Read-Request $in
    if ($req) { Invoke-Route $S $req $in $ns }
    $ns.Flush()
  } catch {
  } finally {
    $Client.Close()
  }
}
'@

. ([scriptblock]::Create($LibText))

function Get-DataDir {
  if ($Klasor) { return $Klasor }
  if ($env:AKTARIM_DIR) { return $env:AKTARIM_DIR }
  $desk = [Environment]::GetFolderPath('Desktop')
  if (-not $desk) { $desk = $HOME }
  Join-Path $desk 'Aktarım'
}

function Get-LocalIPs {
  $ips = New-Object System.Collections.Generic.List[string]
  try {
    $s = New-Object Net.Sockets.Socket([Net.Sockets.AddressFamily]::InterNetwork, [Net.Sockets.SocketType]::Dgram, [Net.Sockets.ProtocolType]::Udp)
    $s.Connect('10.255.255.255', 1)
    $ips.Add($s.LocalEndPoint.Address.ToString())
    $s.Close()
  } catch {}
  try {
    foreach ($ni in [Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
      if ($ni.OperationalStatus -ne 'Up' -or $ni.NetworkInterfaceType -eq 'Loopback') { continue }
      foreach ($a in $ni.GetIPProperties().UnicastAddresses) {
        $ip = $a.Address.ToString()
        if ($a.Address.AddressFamily -eq 'InterNetwork' -and -not $ip.StartsWith('169.254.') -and -not $ips.Contains($ip)) { $ips.Add($ip) }
      }
    }
  } catch {}
  if ($ips.Count -eq 0) { $ips.Add('127.0.0.1') }
  $ips
}

# ---------------------------------------------------------------------------
# Komutlar
# ---------------------------------------------------------------------------

if ($GonderKur) {
  $sendto = Join-Path $env:APPDATA 'Microsoft\Windows\SendTo'
  $bat = Join-Path $sendto 'Telefona gönder (Aktarım).bat'
  $ps1 = Join-Path $Here 'Aktarim.ps1'
  $text = "@echo off`r`nchcp 65001 >nul`r`npowershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ps1`" -Ekle %*`r`n"
  [IO.File]::WriteAllText($bat, $text, (New-Object System.Text.UTF8Encoding $false))
  Write-Host "Eklendi: dosyaya sağ tık → Gönder → Telefona gönder (Aktarım)" -ForegroundColor Green
  return
}

if ($GuvenlikDuvari) {
  $p = 8765; if ($Port) { $p = $Port }
  $admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if (-not $admin) {
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -GuvenlikDuvari -Port $p"
    return
  }
  & netsh advfirewall firewall delete rule name="Aktarim" | Out-Null
  & netsh advfirewall firewall add rule name="Aktarim" dir=in action=allow protocol=TCP localport=$p profile=private | Out-Null
  Write-Host "Güvenlik duvarı kuralı eklendi (özel ağ, TCP $p)." -ForegroundColor Green
  Start-Sleep -Seconds 2
  return
}

$DataDir = Get-DataDir

if ($Ekle) {
  $paths = New-Object System.Collections.Generic.List[string]
  foreach ($f in $Dosyalar) {
    if (Test-Path -LiteralPath $f -PathType Container) {
      Get-ChildItem -LiteralPath $f -Recurse -File | Sort-Object FullName | ForEach-Object { $paths.Add($_.FullName) }
    } elseif (Test-Path -LiteralPath $f) { $paths.Add((Resolve-Path -LiteralPath $f).ProviderPath) }
  }
  if ($paths.Count -eq 0) { Write-Host 'Gönderilecek dosya yok.'; return }
  $cfgPath = Join-Path $DataDir 'ayarlar.json'
  $cfg = $null
  if (Test-Path -LiteralPath $cfgPath) { $cfg = ConvertFrom-Json ([IO.File]::ReadAllText($cfgPath)) }
  $p = 8765; if ($Port) { $p = $Port } elseif ($cfg -and $cfg.port) { $p = [int]$cfg.port }
  $sent = 0
  try {
    foreach ($path in $paths) {
      $name = [IO.Path]::GetFileName($path)
      $req = [Net.HttpWebRequest]::Create("http://127.0.0.1:$p/api/upload")
      $req.Method = 'POST'; $req.Timeout = 600000; $req.AllowWriteStreamBuffering = $false
      $req.Headers.Add('X-Aktarim-Key', [string]$cfg.token)
      $req.Headers.Add('X-Filename', [Uri]::EscapeDataString($name))
      $req.Headers.Add('X-Source', 'Bilgisayar')
      $req.ContentType = Get-Mime $name
      $fs = [IO.File]::OpenRead($path)
      try { $req.ContentLength = $fs.Length; $rs = $req.GetRequestStream(); $fs.CopyTo($rs); $rs.Close() } finally { $fs.Dispose() }
      $req.GetResponse().Close()
      $sent++
      Write-Host "gönderildi: $name"
    }
  } catch [Net.WebException] {
    if ($_.Exception.Status -ne 'ConnectFailure') { throw }
    # sunucu kapalı: doğrudan klasöre ekle
    $S = New-Shared $DataDir
    foreach ($path in $paths[$sent..($paths.Count - 1)]) {
      $fs = [IO.File]::OpenRead($path)
      try { [void](Add-FileFromStream $S ([IO.Path]::GetFileName($path)) $fs $fs.Length 'Bilgisayar' $null) } finally { $fs.Dispose() }
      Write-Host "eklendi: $([IO.Path]::GetFileName($path))"
    }
  }
  return
}

# ---- sunucu ----
$S = New-Shared $DataDir
$S.Web = Join-Path $Here 'web'
if (-not (Test-Path -LiteralPath (Join-Path $S.Web 'index.html'))) { throw "web klasörü bulunamadı: $($S.Web)" }
if (-not $Port) { $Port = [int]$S.Cfg.port }

$listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Any, $Port)
try { $listener.Start() } catch {
  Write-Host "$Port numaralı kapı kullanımda, boş bir kapı seçiliyor..." -ForegroundColor Yellow
  $listener = New-Object Net.Sockets.TcpListener([Net.IPAddress]::Any, 0)
  $listener.Start()
}
$Port = $listener.LocalEndpoint.Port
$S.Urls = @(Get-LocalIPs | ForEach-Object { "http://${_}:$Port/?k=$($S.Cfg.token)" })
$local = "http://127.0.0.1:$Port/?k=$($S.Cfg.token)"

$pool = [RunspaceFactory]::CreateRunspacePool(1, 16)
$pool.Open()
$jobs = New-Object System.Collections.ArrayList
$clientScript = $LibText + "`nInvoke-Client `$args[0] `$args[1]"

Write-Host ''
Write-Host '  Aktarım çalışıyor' -ForegroundColor Cyan
Write-Host "  Klasör     : $($S.Root)"
Write-Host "  Bilgisayar : $local"
foreach ($u in $S.Urls) { Write-Host "  Telefon    : $u" -ForegroundColor Green }
Write-Host '  Telefon ile bilgisayar aynı Wi-Fi ağında olmalı. Kapatmak için bu pencereyi kapat ya da Ctrl+C.'
Write-Host ''
if (-not $TarayiciAcma) { Start-Process $local }

$lastPurge = Get-Date
try {
  while ($true) {
    if ($listener.Pending()) {
      $client = $listener.AcceptTcpClient()
      $ps = [PowerShell]::Create()
      $ps.RunspacePool = $pool
      [void]$ps.AddScript($clientScript).AddArgument($client).AddArgument($S)
      [void]$jobs.Add(@{ PS = $ps; Handle = $ps.BeginInvoke() })
    } else {
      Start-Sleep -Milliseconds 15
    }
    for ($i = $jobs.Count - 1; $i -ge 0; $i--) {
      $j = $jobs[$i]
      if ($j.Handle.IsCompleted) {
        try { [void]$j.PS.EndInvoke($j.Handle) } catch {}
        $j.PS.Dispose()
        $jobs.RemoveAt($i)
      }
    }
    if (((Get-Date) - $lastPurge).TotalMinutes -ge 10) {
      $n = Remove-Expired $S
      if ($n) { Write-Host "  Sonradan Sil: süresi dolan $n öğe kalıcı olarak silindi." }
      $lastPurge = Get-Date
    }
  }
} finally {
  $listener.Stop()
  foreach ($j in $jobs) { try { $j.PS.Stop(); $j.PS.Dispose() } catch {} }
  $pool.Close()
}
