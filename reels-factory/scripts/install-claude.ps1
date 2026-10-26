# Claude Code kurulumu + girisi + Reels Fabrikasi entegrasyonu (Windows).
# Uygulamadaki "Claude Code'u kur ve bagla" dugmesi bunu calistirir; elle de calisir:
#   powershell -ExecutionPolicy Bypass -File scripts\install-claude.ps1
$ErrorActionPreference = "Continue"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $root
$bin = Join-Path $env:USERPROFILE ".local\bin"
$Host.UI.RawUI.WindowTitle = "Claude Code kurulumu - Reels Fabrikasi"

function Find-Claude {
  $c = Get-Command claude -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  $p = Join-Path $bin "claude.exe"
  if (Test-Path $p) { return $p }
  return $null
}
function Is-LoggedIn($exe) {
  try { return [bool]((& $exe auth status 2>$null | Out-String | ConvertFrom-Json).loggedIn) } catch { return $false }
}

$exe = Find-Claude
if (-not $exe) {
  Write-Host "> Claude Code indiriliyor ve kuruluyor (resmi yukleyici, 1-2 dk; ilerleme gosterilmez)..."
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
  $exe = Find-Claude
}
if (-not $exe) {
  Write-Host "X Claude Code kurulamadi. Alternatif: winget install Anthropic.ClaudeCode"
  Read-Host "Kapatmak icin Enter"; exit 1
}

# Yeni terminallerde 'claude' komutu bulunsun
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ((Split-Path $exe) -eq $bin -and ($userPath -split ";") -notcontains $bin) {
  [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $bin), "User")
  Write-Host "> PATH'e eklendi: $bin"
}
Write-Host ("> Kurulu: " + (& $exe --version))

if (-not (Is-LoggedIn $exe)) {
  Write-Host ""
  Write-Host "> Giris: tarayici acilacak; Claude hesabinizla (Pro/Max) giris yapip izin verin."
  & $exe auth login
}

if (Is-LoggedIn $exe) {
  # Masaustu kisayolu: Claude Code'u Reels Fabrikasi klasorunde acar (CLAUDE.md ve SKILL.md ile)
  $shell = New-Object -ComObject WScript.Shell
  $lnk = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "Claude Code (Reels).lnk"))
  $lnk.TargetPath = "powershell.exe"
  $lnk.Arguments = "-NoExit -Command `"& '$exe'`""
  $lnk.WorkingDirectory = $root
  $lnk.Description = "Claude Code - Reels Fabrikasi klasorunde"
  $lnk.Save()
  Write-Host ""
  Write-Host "OK Claude Code hazir ve Reels Fabrikasi'na bagli."
  Write-Host "   Uygulamadaki 'Uret' dugmesi ve otomatik mod artik senaryolari Claude Code ile yazar."
  Write-Host "   Masaustundeki 'Claude Code (Reels)' kisayolu ile dogrudan sohbet edebilirsiniz."
} else {
  Write-Host "X Giris tamamlanmadi. Bu pencereyi kapatip uygulamadaki dugmeye tekrar basin."
}
Read-Host "Kapatmak icin Enter"
