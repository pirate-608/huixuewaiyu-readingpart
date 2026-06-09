# Install huixuewaiyu-readingpart skill for Claude Code (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$SKILL_NAME = "huixuewaiyu-readingpart"
$SKILL_DIR = "$env:USERPROFILE\.claude\skills\$SKILL_NAME"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installing $SKILL_NAME" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Find a Windows-native Python (prefer over MSYS2/Cygwin Python which creates
# Unix-layout venvs with bin/ instead of Scripts/, breaking path assumptions).
function Find-NativePython {
    $candidates = @()
    # Check common install locations first
    foreach ($pyDir in @("C:\Python314", "C:\Python313", "C:\Python312", "C:\Python311",
                          "$env:LOCALAPPDATA\Programs\Python\Python314",
                          "$env:LOCALAPPDATA\Programs\Python\Python313",
                          "$env:LOCALAPPDATA\Programs\Python\Python312",
                          "$env:APPDATA\Python\Python314",
                          "$env:APPDATA\Python\Python313")) {
        $pyExe = Join-Path $pyDir "python.exe"
        if (Test-Path $pyExe) { $candidates += $pyExe }
    }
    # Fall back to whatever `where.exe python` finds, filtering for Windows-native paths
    $whereResults = & where.exe python 2>$null | Where-Object { $_ -match '\.exe$' -and $_ -notmatch 'msys|cygwin|mingw' }
    foreach ($r in $whereResults) { if ($r -notin $candidates) { $candidates += $r } }
    # Last resort: bare python (might be MSYS2)
    try { $barePath = (Get-Command python -ErrorAction Stop).Source; if ($barePath -notin $candidates) { $candidates += $barePath } } catch {}
    return $candidates
}

function Get-VenvPython {
    param([string]$VenvDir)
    # Detect venv layout: Windows uses Scripts/, MSYS2/Cygwin uses bin/
    $winPath  = Join-Path $VenvDir "Scripts\python.exe"
    $unixPath = Join-Path $VenvDir "bin\python.exe"
    if (Test-Path $winPath)  { return $winPath }
    if (Test-Path $unixPath) { return $unixPath }
    # Try without .exe extension
    $unixScript = Join-Path $VenvDir "bin\python"
    if (Test-Path $unixScript) { return $unixScript }
    return $null
}

$NATIVE_PYTHONS = @(Find-NativePython)
if ($NATIVE_PYTHONS.Count -eq 0) {
    Write-Host "ERROR: No Python found. Install Python 3.11–3.12 from https://python.org" -ForegroundColor Red
    exit 1
}
$PYTHON_EXE = $NATIVE_PYTHONS[0]

# Warn if the selected Python looks non-Windows (MSYS2/Cygwin)
if ($PYTHON_EXE -match 'msys|cygwin|mingw') {
    Write-Host "WARNING: Selected Python appears to be MSYS2/Cygwin:" -ForegroundColor Yellow
    Write-Host "  $PYTHON_EXE" -ForegroundColor Yellow
    Write-Host "  This creates Unix-layout venvs. Consider installing native Windows Python." -ForegroundColor Yellow
    Write-Host "  https://python.org" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "Using Python: $PYTHON_EXE" -ForegroundColor Green
Write-Host ""

# Check Python version
$pyFull = & $PYTHON_EXE -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pyMajor, $pyMinor = $pyFull -split '\.'
if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 8)) {
    Write-Host "ERROR: Python 3.8+ required, found $pyFull" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Python $pyFull" -ForegroundColor Green

# Copy skill files (before venv so SKILL.md is in place)
Write-Host ""
Write-Host "Copying skill files..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "$SKILL_DIR\scripts" | Out-Null
New-Item -ItemType Directory -Force -Path "$SKILL_DIR\references" | Out-Null
New-Item -ItemType Directory -Force -Path "$SKILL_DIR\assets" | Out-Null
Copy-Item -Force "$SCRIPT_DIR\scripts\elang_reader.py" "$SKILL_DIR\scripts\"
Copy-Item -Force "$SCRIPT_DIR\references\api_reference.md" "$SKILL_DIR\references\"
Copy-Item -Force "$SCRIPT_DIR\SKILL.md" "$SKILL_DIR\"
Copy-Item -Force "$SCRIPT_DIR\.env.example" "$SKILL_DIR\assets\"
Copy-Item -Force "$SCRIPT_DIR\requirements.txt" "$SKILL_DIR\assets\"
Write-Host "[OK] Files copied to $SKILL_DIR" -ForegroundColor Green

# Create virtual environment (isolated from global/conda Python)
Write-Host ""
Write-Host "Creating virtual environment..." -ForegroundColor Yellow
& $PYTHON_EXE -m venv "$SKILL_DIR\.venv"
$VENV_PYTHON = Get-VenvPython "$SKILL_DIR\.venv"
if (-not $VENV_PYTHON) {
    Write-Host "ERROR: Failed to find python in venv at $SKILL_DIR\.venv" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] venv created at $SKILL_DIR\.venv (layout: $(Split-Path $VENV_PYTHON -Parent | Split-Path -Leaf)/$(Split-Path $VENV_PYTHON -Leaf))" -ForegroundColor Green

# Install Python dependencies into venv
Write-Host ""
Write-Host "Installing Python dependencies (into venv)..." -ForegroundColor Yellow
& "$VENV_PYTHON" -m pip install --upgrade pip -q
& "$VENV_PYTHON" -m pip install -r "$SKILL_DIR\assets\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed. Try manually: $VENV_PYTHON -m pip install -r $SKILL_DIR\assets\requirements.txt" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# Install Playwright browser (uses venv's playwright)
Write-Host ""
Write-Host "Installing Chromium browser for Playwright..." -ForegroundColor Yellow
& "$VENV_PYTHON" -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: playwright install chromium failed." -ForegroundColor Yellow
    Write-Host "Run manually: $VENV_PYTHON -m playwright install chromium" -ForegroundColor Yellow
}
Write-Host "[OK] Chromium ready" -ForegroundColor Green

# Setup .env
Write-Host ""
if (-not (Test-Path "$SKILL_DIR\.env")) {
    Write-Host "Setting up credentials..." -ForegroundColor Yellow
    Write-Host "Your ZJU student ID and CAS password are needed for auto-login."
    Write-Host "These are stored locally in $SKILL_DIR\.env and never sent anywhere."
    Write-Host ""
    $studentId = Read-Host "Student ID (学号)"
    $securePass = Read-Host "CAS Password" -AsSecureString
    $pass = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePass)
    )
    # Write UTF-8 WITHOUT BOM - python-dotenv chokes on BOM
    $envContent = "CAS_USERNAME=$studentId`nCAS_PASSWORD=$pass`n"
    [System.IO.File]::WriteAllText("$SKILL_DIR\.env", $envContent, [System.Text.UTF8Encoding]::new($false))
    Write-Host "[OK] Credentials saved to .env" -ForegroundColor Green
} else {
    Write-Host "[OK] .env already exists - skipping credential setup" -ForegroundColor Green
}

# Also install to ~/.agents/
Write-Host ""
$installAgents = Read-Host "Also install as general agent to ~/.agents/? (y/N)"
if ($installAgents -eq "y" -or $installAgents -eq "Y") {
    $AGENTS_DIR = "$env:USERPROFILE\.agents\$SKILL_NAME"
    New-Item -ItemType Directory -Force -Path "$AGENTS_DIR\scripts" | Out-Null
    New-Item -ItemType Directory -Force -Path "$AGENTS_DIR\references" | Out-Null
    New-Item -ItemType Directory -Force -Path "$AGENTS_DIR\assets" | Out-Null
    Copy-Item -Force "$SKILL_DIR\scripts\elang_reader.py" "$AGENTS_DIR\scripts\"
    Copy-Item -Force "$SKILL_DIR\references\api_reference.md" "$AGENTS_DIR\references\"
    Copy-Item -Force "$SKILL_DIR\SKILL.md" "$AGENTS_DIR\"
    Copy-Item -Force "$SKILL_DIR\assets\.env.example" "$AGENTS_DIR\assets\"
    Copy-Item -Force "$SKILL_DIR\assets\requirements.txt" "$AGENTS_DIR\assets\"
    if (Test-Path "$SKILL_DIR\.env") {
        Copy-Item -Force "$SKILL_DIR\.env" "$AGENTS_DIR\"
    }
    # Create venv for agents dir too
    & $PYTHON_EXE -m venv "$AGENTS_DIR\.venv"
    $AGENTS_PYTHON = Get-VenvPython "$AGENTS_DIR\.venv"
    if ($AGENTS_PYTHON) {
        & "$AGENTS_PYTHON" -m pip install --upgrade pip -q
        & "$AGENTS_PYTHON" -m pip install -r "$AGENTS_DIR\assets\requirements.txt" -q
    }
    Write-Host "[OK] Agent files copied to $AGENTS_DIR" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Skill directory: $SKILL_DIR"
Write-Host "Python: $VENV_PYTHON"
Write-Host ""
Write-Host "Usage in Claude Code:"
Write-Host "  /huixuewaiyu-readingpart"
Write-Host "  or say: 慧学外语刷题"
