# Premiere Pro MCP (MIT, https://github.com/leancoderkavy/premiere-pro-mcp) - Adobe Premiere Pro'yu Claude'dan yonetmek icin.
# 1) npm paketini kurar (yayinlanmis surum, sabit)  2) Premiere kurulu ve kapaliysa Premiere baglayicisini (CEP) yukler
# 3) yerel denetim (--doctor). Claude Code'a kaydi `python scripts/factory.py mcp` yapar (Premiere kuruluysa).
# Kullanim (reels-factory klasorunden):
#   powershell -ExecutionPolicy Bypass -File scripts\install-premiere-mcp.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-premiere-mcp.ps1 -Remove
param([switch]$Remove)
$Version = "1.24.4"   # README'deki "Latest release"; npm'de dogrulandi (repo: leancoderkavy/premiere-pro-mcp)
function Ok($m) { Write-Host "    OK $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    ! $m" -ForegroundColor DarkYellow }

$premiere = @(Get-ChildItem "$env:ProgramFiles\Adobe" -Directory -Filter "Adobe Premiere Pro*" -ErrorAction SilentlyContinue)
$running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -like "Adobe Premiere Pro*" }

if ($Remove) {
  if (Get-Command premiere-pro-mcp -ErrorAction SilentlyContinue) {
    if ($running) { Warn "Premiere acik: baglayiciyi kaldirmak icin once Premiere'i kapatin." } else { premiere-pro-mcp --uninstall-cep }
  }
  npm uninstall -g premiere-pro-mcp
  Ok "Premiere Pro MCP kaldirildi (Claude Code kaydi icin: claude mcp remove -s user premiere-pro)"
  exit 0
}

npm install -g --silent "premiere-pro-mcp@$Version"
if ($LASTEXITCODE -ne 0) { Warn "premiere-pro-mcp kurulamadi (npm)."; exit 1 }
$ver = (premiere-pro-mcp --version) 2>$null
Ok "premiere-pro-mcp $ver"

if (-not $premiere.Count) {
  Warn "Adobe Premiere Pro bulunamadi: sunucu kuruldu ama Premiere olmadan calismaz. Premiere'i kurunca bu betigi tekrar calistirin."
  exit 0
}
$names = ($premiere | ForEach-Object { $_.Name }) -join ", "
Ok "Premiere: $names"
if ($running) {
  Warn "Premiere acik: baglayici (CEP paneli) kurulmadi. Premiere'i tamamen kapatip bu betigi tekrar calistirin."
} else {
  premiere-pro-mcp --install-cep
  if ($LASTEXITCODE -eq 0) { Ok "Premiere baglayicisi kuruldu (Window > Extensions > MCP for Adobe Premiere Pro)" }
  else { Warn "Baglayici kurulamadi; 'premiere-pro-mcp --doctor --plan-fixes' ile bakin." }
}
premiere-pro-mcp --doctor
