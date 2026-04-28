#!/bin/bash
# Install huixuewaiyu-readingpart skill for Claude Code
# Usage: bash install.sh

SKILL_NAME="huixuewaiyu-readingpart"
SKILL_DIR="$HOME/.claude/skills/$SKILL_NAME"

echo "Installing $SKILL_NAME..."

# Check dependencies
command -v python >/dev/null 2>&1 || { echo "ERROR: Python not found. Install Python 3.8+ first."; exit 1; }
echo "[OK] Python: $(python --version)"

python -c "import playwright" 2>/dev/null || { 
    echo "Installing playwright..."
    pip install playwright && playwright install chromium || {
        echo "ERROR: Failed to install playwright. Run manually: pip install playwright && playwright install chromium"
        exit 1
    }
}
echo "[OK] Playwright installed"

# Copy skill files
mkdir -p "$SKILL_DIR/scripts" "$SKILL_DIR/references"
cp scripts/elang_reader.py "$SKILL_DIR/scripts/"
cp references/api_reference.md "$SKILL_DIR/references/"
cp SKILL.md "$SKILL_DIR/"

echo ""
echo "Installation complete!"
echo "Skill directory: $SKILL_DIR"
echo ""
echo "Usage in Claude Code:"
echo "  /huixuewaiyu-readingpart"
echo "  or say: 慧学外语刷题"
