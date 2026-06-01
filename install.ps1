# Install huixuewaiyu-readingpart skill for Claude Code (Windows)
# Usage: powershell -ExecutionPolicy Bypass -File install.ps1

$ErrorActionPreference = "Stop"
$SKILL_NAME = "huixuewaiyu-readingpart"
$SKILL_DIR = "$env:USERPROFILE\.claude\skills\$SKILL_NAME"
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installing $SKILL_NAME" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check Python
try {
    $pythonVer = python --version 2>&1
    $pyFull = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $pyMajor, $pyMinor = $pyFull -split '\.'
    if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 8)) {
        Write-Host "ERROR: Python 3.8+ required, found $pyFull" -ForegroundColor Red
        exit 1
    }
    if ([int]$pyMajor -eq 3 -and [int]$pyMinor -ge 13) {
        Write-Host "WARNING: Python $pyFull detected. ddddocr depends on opencv-python which may" -ForegroundColor Yellow
        Write-Host "  not have wheels for Python 3.13+ yet. If install fails, use Python 3.11–3.12." -ForegroundColor Yellow
        Write-Host "  conda create -n elang python=3.12 && conda activate elang" -ForegroundColor Yellow
        Write-Host ""
    }
    Write-Host "[OK] Python: $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found. Install Python 3.8+ from https://python.org" -ForegroundColor Red
    exit 1
}

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
python -m venv "$SKILL_DIR\.venv"
$VENV_PYTHON = "$SKILL_DIR\.venv\Scripts\python.exe"
Write-Host "[OK] venv created at $SKILL_DIR\.venv" -ForegroundColor Green

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
    @"
CAS_USERNAME=$studentId
CAS_PASSWORD=$pass
"@ | Out-File -FilePath "$SKILL_DIR\.env" -Encoding utf8
    Write-Host "[OK] Credentials saved to .env" -ForegroundColor Green
} else {
    Write-Host "[OK] .env already exists — skipping credential setup" -ForegroundColor Green
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
    python -m venv "$AGENTS_DIR\.venv"
    $AGENTS_PYTHON = "$AGENTS_DIR\.venv\Scripts\python.exe"
    & "$AGENTS_PYTHON" -m pip install --upgrade pip -q
    & "$AGENTS_PYTHON" -m pip install -r "$AGENTS_DIR\assets\requirements.txt" -q
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
