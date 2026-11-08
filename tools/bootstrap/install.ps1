# elang offline installer
#
# Installs the elang tool from THIS bundle with no network access:
#   cpython-*-install_only*.tar.gz   python-build-standalone runtime
#   wheels/                          every dependency as a wheel
#   SHA256SUMS                       hashes for the runtime and every wheel
#
# Resulting tree (default Target = %LOCALAPPDATA%\elang):
#   <Target>\runtime\          interpreter
#   <Target>\venv\             site-packages (playwright lives here)
#   <Target>\bin\elang.cmd     launcher
#   <Target>\manifest.json     what this installer created (used by -Uninstall)
#
# WHY .NET INSTEAD OF CMDLETS: this script deliberately uses [System.IO.*] and
# [System.Security.Cryptography.*] rather than Get-FileHash / Get-Content /
# Get-ChildItem. Measured failure during development: Windows PowerShell 5.1
# started from a PowerShell 7 parent inherits pwsh7's PSModulePath, so
# module-provided cmdlets such as Get-FileHash are NOT found and the install died
# on its first hash check. An installer must not depend on module autoloading.
#
# Usage:
#   install.cmd                     install to %LOCALAPPDATA%\elang
#   install.cmd -Target D:\x\elang  install elsewhere
#   install.cmd -Check              report only, change nothing
#   install.cmd -Uninstall          remove what this installer created
#   install.cmd -NoDoctor           skip the post-install self check
#   install.cmd -NoPath             do not touch the user PATH
param(
    [string]$Target = (Join-Path $env:LOCALAPPDATA 'elang'),
    [switch]$Check,
    [switch]$Uninstall,
    [switch]$NoDoctor,
    [switch]$NoPath
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$manifestPath = Join-Path $Target 'manifest.json'
$venvPy = Join-Path $Target 'venv\Scripts\python.exe'
$shim = Join-Path $Target 'bin\elang.cmd'
$binDir = Join-Path $Target 'bin'

function Say($msg) { Write-Host "  $msg" }
function Fail($msg) { Write-Host "  FAILED: $msg" -ForegroundColor Red; exit 1 }
function MakeDir($p) {
    if (-not [System.IO.Directory]::Exists($p)) { [void][System.IO.Directory]::CreateDirectory($p) }
}

function Get-Sha256($path) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $fs = [System.IO.File]::OpenRead($path)
        try { $bytes = $sha.ComputeHash($fs) } finally { $fs.Dispose() }
    } finally { $sha.Dispose() }
    $sb = New-Object System.Text.StringBuilder
    foreach ($b in $bytes) { [void]$sb.Append($b.ToString('x2')) }
    return $sb.ToString()
}

function Remove-PathEntry($dir) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $userPath) { return $false }
    $parts = $userPath -split ';' | Where-Object { $_ -ne '' -and $_ -ne $dir }
    $new = ($parts -join ';')
    if ($new -ne $userPath) {
        [Environment]::SetEnvironmentVariable('Path', $new, 'User')
        return $true
    }
    return $false
}

# ---------------------------------------------------------------- uninstall
if ($Uninstall) {
    Write-Host '================================================================'
    Write-Host '  elang reading solver - uninstall'
    Write-Host '================================================================'
    Say "target : $Target"
    if (-not (Test-Path -LiteralPath $Target)) { Say 'nothing to remove'; exit 0 }

    # Only remove a PATH entry this installer added. A `uv tool install` entry
    # lives elsewhere and must survive.
    if (Remove-PathEntry $binDir) { Say "removed from user PATH: $binDir" }

    $userData = Join-Path $env:USERPROFILE '.elang'
    Say "keeping user data (browser profile, config): $userData"
    Remove-Item -LiteralPath $Target -Recurse -Force
    Say 'removed the installed tree'
    Write-Host '  done.'
    exit 0
}

Write-Host '================================================================'
Write-Host '  elang reading solver - offline install'
Write-Host '================================================================'
Say "bundle : $here"
Say "target : $Target"

$wheelsDir = Join-Path $here 'wheels'
$sumsFile = Join-Path $here 'SHA256SUMS'

# ---------------------------------------------------------------- preflight
if ($Check) {
    Say ''
    Say "runtime installed : $(Test-Path -LiteralPath (Join-Path $Target 'runtime\python.exe'))"
    Say "venv installed    : $(Test-Path -LiteralPath $venvPy)"
    Say "launcher present  : $(Test-Path -LiteralPath $shim)"
    if (Test-Path -LiteralPath $manifestPath) {
        Say "manifest          : $([System.IO.File]::ReadAllText($manifestPath))"
    }
    if (Test-Path -LiteralPath $venvPy) {
        $v = & $venvPy -c "import elang; print('import ok')" 2>&1
        Say "import elang      : $v"
        & $venvPy -m elang.cli doctor --json > $null 2>&1
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $wheelsDir)) { Fail "bundle is incomplete: no wheels/ in $here" }
if (-not (Test-Path -LiteralPath $sumsFile)) { Fail "bundle is incomplete: no SHA256SUMS in $here" }

$tarballs = [System.IO.Directory]::GetFiles($here, 'cpython-*-install_only*.tar.gz')
if ($tarballs.Count -eq 0) { Fail "bundle is incomplete: no cpython-*.tar.gz runtime in $here" }
$tarball = $tarballs[0]
Say "runtime: $([System.IO.Path]::GetFileName($tarball))"

$bundleVersion = 'unknown'
$versionFile = Join-Path $here 'VERSION'
if (Test-Path -LiteralPath $versionFile) {
    $bundleVersion = [System.IO.File]::ReadAllText($versionFile).Trim()
    Say "version: $bundleVersion"
}

# ------------------------------------------------------------- verify bundle
Say ''
Say '-- verifying bundle --'
$expected = @{}
foreach ($line in [System.IO.File]::ReadAllLines($sumsFile)) {
    if ($line -match '^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$') {
        $expected[$Matches[2]] = $Matches[1].ToLower()
    }
}
Say "  manifest entries: $($expected.Count)"
$checked = 0
foreach ($name in @($expected.Keys)) {
    $p = Join-Path $here $name
    if (-not [System.IO.File]::Exists($p)) { Fail "missing from bundle: $name" }
    if ((Get-Sha256 $p) -ne $expected[$name]) { Fail "hash mismatch: $name" }
    $checked++
}
Say "  verified: $checked file(s)"

# ------------------------------------------------------------------- runtime
MakeDir $Target
$targetRuntime = Join-Path $Target 'runtime'
$py = Join-Path $targetRuntime 'python.exe'
if (-not [System.IO.File]::Exists($py)) {
    $tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
    if (-not [System.IO.File]::Exists($tarExe)) {
        Fail 'tar.exe not found (it ships with Windows 10 1803+). Extract the runtime archive manually into <Target>\runtime.'
    }
    Say ''
    Say '-- extracting runtime --'
    $staging = Join-Path $Target '.staging'
    if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
    MakeDir $staging
    & $tarExe -xzf $tarball -C $staging
    if ($LASTEXITCODE -ne 0) { Fail 'tar extraction failed' }
    $inner = Join-Path $staging 'python'
    if (-not (Test-Path -LiteralPath $inner)) { Fail 'unexpected archive layout: no python/ inside the runtime archive' }
    if (Test-Path -LiteralPath $targetRuntime) { Remove-Item -LiteralPath $targetRuntime -Recurse -Force }
    [System.IO.Directory]::Move($inner, $targetRuntime)
    Remove-Item -LiteralPath $staging -Recurse -Force
}
if (-not [System.IO.File]::Exists($py)) { Fail "runtime install failed: $py missing" }
Say "  interpreter: $(& $py --version)"

# ----------------------------------------------------------------------- venv
Say ''
Say '-- installing elang (offline) --'
if (-not [System.IO.File]::Exists($venvPy)) {
    & $py -m venv (Join-Path $Target 'venv')
    if ($LASTEXITCODE -ne 0) { Fail 'venv creation failed' }
}
$env:PIP_NO_INDEX = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
& $venvPy -m pip install --no-index --find-links $wheelsDir elang_reading
if ($LASTEXITCODE -ne 0) { Fail 'pip install failed (the bundle may be incomplete)' }

# -------------------------------------------------------------------- launcher
Say ''
Say '-- writing launcher --'
MakeDir $binDir
$content = "@echo off`r`n`"$venvPy`" -m elang.cli %*`r`n"
[System.IO.File]::WriteAllText($shim, $content, [System.Text.Encoding]::ASCII)
Say "  launcher: $shim"

$pathAdded = $false
if (-not $NoPath) {
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -notlike "*$binDir*") {
        [Environment]::SetEnvironmentVariable('Path', "$userPath;$binDir", 'User')
        $pathAdded = $true
        Say "  added to user PATH: $binDir"
        Say '  (open a NEW terminal for it to take effect)'
    } else {
        Say "  already on user PATH: $binDir"
    }
}

# ------------------------------------------------------------------- manifest
$installedVersion = (& $venvPy -c "import elang; print(getattr(elang,'__version__',''))" 2>&1)
$manifest = [ordered]@{
    bundleVersion = $bundleVersion
    packageVersion = "$installedVersion".Trim()
    target = $Target
    launcher = $shim
    pathEntry = $(if ($pathAdded -or ($NoPath -eq $false)) { $binDir } else { $null })
    installedAt = (Get-Date).ToString('s')
}
[System.IO.File]::WriteAllText($manifestPath, ($manifest | ConvertTo-Json), [System.Text.Encoding]::UTF8)
Say "  manifest: $manifestPath"

# -------------------------------------------------------------------- verify
Say ''
Say '-- verifying --'
& $venvPy -c "import elang, elang_reader, playwright; print('imports ok')"
if ($LASTEXITCODE -ne 0) { Fail 'the installed tree cannot import its modules' }

if (-not $NoDoctor) {
    Say ''
    Say '-- elang doctor --'
    & $venvPy -m elang.cli doctor
    if ($LASTEXITCODE -ne 0) {
        Say "  doctor reported problems (exit $LASTEXITCODE); follow the hints above"
    }
}

Write-Host ''
Write-Host '================================================================'
Write-Host "  installed: $shim"
Write-Host '  next: elang init-env     (credentials template)'
Write-Host '        elang doctor       (verify)'
Write-Host '  remove: install.cmd -Uninstall'
Write-Host '================================================================'
exit 0