#!/bin/bash
# Install huixuewaiyu-readingpart skill for Claude Code
# Usage: bash install.sh

set -e
SKILL_NAME="huixuewaiyu-readingpart"
SKILL_DIR="$HOME/.claude/skills/$SKILL_NAME"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "========================================"
echo "  Installing $SKILL_NAME"
echo "========================================"

# Check Python
command -v python3 >/dev/null 2>&1 && PYTHON=python3 || PYTHON=python
command -v "$PYTHON" >/dev/null 2>&1 || { echo "ERROR: Python not found. Install Python 3.8+ first."; exit 1; }
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 8 ]; }; then
    echo "ERROR: Python 3.8+ required, found $PY_VER"
    exit 1
fi
if [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -ge 13 ]; then
    echo "WARNING: Python $PY_VER detected. ddddocr depends on opencv-python which may"
    echo "  not have wheels for Python 3.13+ yet. If install fails, use Python 3.11–3.12."
    echo "  conda create -n elang python=3.12 && conda activate elang"
    echo ""
fi
echo "[OK] Python: $($PYTHON --version)"

# Copy skill files (before venv so SKILL.md is in place)
echo ""
echo "Copying skill files..."
mkdir -p "$SKILL_DIR/scripts" "$SKILL_DIR/references" "$SKILL_DIR/assets"
cp "$SCRIPT_DIR/scripts/elang_reader.py" "$SKILL_DIR/scripts/"
cp "$SCRIPT_DIR/references/api_reference.md" "$SKILL_DIR/references/"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/"
cp "$SCRIPT_DIR/.env.example" "$SKILL_DIR/assets/"
cp "$SCRIPT_DIR/requirements.txt" "$SKILL_DIR/assets/"
echo "[OK] Files copied to $SKILL_DIR"

# Create virtual environment (isolated from global/conda Python)
echo ""
echo "Creating virtual environment..."
"$PYTHON" -m venv "$SKILL_DIR/.venv"
# Detect venv python path (differs between Unix and Windows)
if [ -f "$SKILL_DIR/.venv/bin/python" ]; then
    VENV_PYTHON="$SKILL_DIR/.venv/bin/python"
elif [ -f "$SKILL_DIR/.venv/Scripts/python.exe" ]; then
    VENV_PYTHON="$SKILL_DIR/.venv/Scripts/python.exe"
else
    VENV_PYTHON="$SKILL_DIR/.venv/Scripts/python"
fi
echo "[OK] venv created at $SKILL_DIR/.venv"

# Install Python dependencies into venv
echo ""
echo "Installing Python dependencies (into venv)..."
"$VENV_PYTHON" -m pip install --upgrade pip -q
"$VENV_PYTHON" -m pip install -r "$SKILL_DIR/assets/requirements.txt" || {
    echo "ERROR: pip install failed. Try manually: $VENV_PYTHON -m pip install -r $SKILL_DIR/assets/requirements.txt"
    exit 1
}
echo "[OK] Dependencies installed"

# Install Playwright browser (uses venv's playwright)
echo ""
echo "Installing Chromium browser for Playwright..."
"$VENV_PYTHON" -m playwright install chromium || {
    echo "WARNING: playwright install chromium failed."
    echo "Run manually: $VENV_PYTHON -m playwright install chromium"
}
echo "[OK] Chromium ready"

# Setup .env
echo ""
if [ ! -f "$SKILL_DIR/.env" ]; then
    echo "Setting up credentials..."
    echo "Your ZJU student ID (学号) and CAS password are needed for auto-login."
    echo "These are stored locally in $SKILL_DIR/.env and never sent anywhere."
    echo ""
    read -p "Student ID (学号): " STUDENT_ID
    read -sp "CAS Password: " CAS_PASS
    echo ""
    cat > "$SKILL_DIR/.env" << EOF
CAS_USERNAME=$STUDENT_ID
CAS_PASSWORD=$CAS_PASS
EOF
    echo "[OK] Credentials saved to .env"
else
    echo "[OK] .env already exists — skipping credential setup"
fi

# Also install to ~/.agents/
echo ""
read -p "Also install as general agent to ~/.agents/? (y/N): " INSTALL_AGENTS
if [ "$INSTALL_AGENTS" = "y" ] || [ "$INSTALL_AGENTS" = "Y" ]; then
    AGENTS_DIR="$HOME/.agents/$SKILL_NAME"
    mkdir -p "$AGENTS_DIR/scripts" "$AGENTS_DIR/references" "$AGENTS_DIR/assets"
    cp "$SKILL_DIR/scripts/elang_reader.py" "$AGENTS_DIR/scripts/"
    cp "$SKILL_DIR/references/api_reference.md" "$AGENTS_DIR/references/"
    cp "$SKILL_DIR/SKILL.md" "$AGENTS_DIR/"
    cp "$SKILL_DIR/assets/.env.example" "$AGENTS_DIR/assets/"
    cp "$SKILL_DIR/assets/requirements.txt" "$AGENTS_DIR/assets/"
    if [ -f "$SKILL_DIR/.env" ]; then
        cp "$SKILL_DIR/.env" "$AGENTS_DIR/"
    fi
    # Create venv for agents dir too
    "$PYTHON" -m venv "$AGENTS_DIR/.venv"
    if [ -f "$AGENTS_DIR/.venv/bin/python" ]; then
        AGENTS_PYTHON="$AGENTS_DIR/.venv/bin/python"
    elif [ -f "$AGENTS_DIR/.venv/Scripts/python.exe" ]; then
        AGENTS_PYTHON="$AGENTS_DIR/.venv/Scripts/python.exe"
    else
        AGENTS_PYTHON="$AGENTS_DIR/.venv/Scripts/python"
    fi
    "$AGENTS_PYTHON" -m pip install --upgrade pip -q
    "$AGENTS_PYTHON" -m pip install -r "$AGENTS_DIR/assets/requirements.txt" -q
    echo "[OK] Agent files copied to $AGENTS_DIR"
fi

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo "Skill directory: $SKILL_DIR"
echo "Python: $VENV_PYTHON"
echo ""
echo "Usage in Claude Code:"
echo "  /huixuewaiyu-readingpart"
echo "  or say: 慧学外语刷题"
