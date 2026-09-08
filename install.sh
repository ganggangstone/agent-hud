#!/usr/bin/env bash
# Installs Claude HUD as a per-user launchd service (macOS only).
set -euo pipefail

TOOL_DIR="$HOME/.claude/tools/claude-hud"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON3="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/com.claude-hud.plist"

mkdir -p "$TOOL_DIR"
cp "$SRC_DIR/server.py" "$TOOL_DIR/server.py"

if [ ! -f "$TOOL_DIR/modes.json" ]; then
  cp "$SRC_DIR/modes.json.example" "$TOOL_DIR/modes.json"
  echo "Created $TOOL_DIR/modes.json from the example — edit it to match your own plugins."
fi

sed -e "s#__HOME__#$HOME#g" -e "s#__PYTHON3__#$PYTHON3#g" \
  "$SRC_DIR/com.claude-hud.plist.template" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Claude HUD installed and running (launchd service com.claude-hud)."
echo "Dashboard: check \$HOME/.claude/tools/claude-hud/.port for the live port (starts at 7717)."
echo ""
echo "To have each Claude Code session register itself with the dashboard, add this to"
echo "~/.claude/settings.json under \"hooks\" -> \"SessionStart\":"
echo ""
cat <<'EOF'
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "nohup python3 \"$HOME/.claude/tools/claude-hud/server.py\" --register \"$PWD\" >/dev/null 2>&1 & disown"
          }
        ]
      }
    ]
  }
}
EOF
echo ""
echo "(Merge this into your existing settings.json by hand — this script does not touch it,"
echo "since it may already contain other hooks you don't want overwritten.)"
