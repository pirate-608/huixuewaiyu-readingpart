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
echo "[OK] Python: $($PYTHON --version)"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
"$PYTHON" -m pip install -r "$SCRIPT_DIR/requirements.txt" || {
    echo "ERROR: pip install failed. Try manually: pip install -r requirements.txt"
    exit 1
}
echo "[OK] Dependencies installed"

# Install Playwright browser
echo ""
echo "Installing Chromium browser for Playwright..."
"$PYTHON" -m playwright install chromium || {
    echo "WARNING: playwright install chromium failed."
    echo "Run manually: playwright install chromium"
}
echo "[OK] Chromium ready"

# Copy skill files
echo ""
echo "Copying skill files..."
mkdir -p "$SKILL_DIR/scripts" "$SKILL_DIR/references" "$SKILL_DIR/assets"
cp "$SCRIPT_DIR/scripts/elang_reader.py" "$SKILL_DIR/scripts/"
cp "$SCRIPT_DIR/references/api_reference.md" "$SKILL_DIR/references/"
cp "$SCRIPT_DIR/SKILL.md" "$SKILL_DIR/"
cp "$SCRIPT_DIR/.env.example" "$SKILL_DIR/assets/"
cp "$SCRIPT_DIR/requirements.txt" "$SKILL_DIR/assets/"
echo "[OK] Files copied to $SKILL_DIR"

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
    echo "[OK] Agent files copied to $AGENTS_DIR"
fi

echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo "Skill directory: $SKILL_DIR"
echo ""
echo "Usage in Claude Code:"
echo "  /huixuewaiyu-readingpart"
echo "  or say: 慧学外语刷题"
