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
    Write-Host "[OK] Python: $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python not found. Install Python 3.8+ from https://python.org" -ForegroundColor Red
    exit 1
}

# Install Python dependencies
Write-Host ""
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install -r "$SCRIPT_DIR\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed. Try manually: pip install -r requirements.txt" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Dependencies installed" -ForegroundColor Green

# Install Playwright browser
Write-Host ""
Write-Host "Installing Chromium browser for Playwright..." -ForegroundColor Yellow
python -m playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: playwright install chromium failed." -ForegroundColor Yellow
    Write-Host "Run manually: playwright install chromium" -ForegroundColor Yellow
}
Write-Host "[OK] Chromium ready" -ForegroundColor Green

# Copy skill files
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
    Write-Host "[OK] Agent files copied to $AGENTS_DIR" -ForegroundColor Green
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Installation complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Skill directory: $SKILL_DIR"
Write-Host ""
Write-Host "Usage in Claude Code:"
Write-Host "  /huixuewaiyu-readingpart"
Write-Host "  or say: 慧学外语刷题"
