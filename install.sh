#!/usr/bin/env bash
# Installs Agent HUD as a per-user launchd service (macOS only).
set -euo pipefail

TOOL_DIR="$HOME/.claude/tools/agent-hud"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON3="$(command -v python3)"
PLIST="$HOME/Library/LaunchAgents/com.agent-hud.plist"

mkdir -p "$TOOL_DIR"
cp "$SRC_DIR/server.py" "$TOOL_DIR/server.py"

if [ ! -f "$TOOL_DIR/modes.json" ]; then
  cp "$SRC_DIR/modes.json.example" "$TOOL_DIR/modes.json"
  echo "Created $TOOL_DIR/modes.json from the example — edit it to match your own plugins."
fi

# Token counting is optional: if this fails, the dashboard still works and shows "not measured".
# It installs tiktoken into a private venv inside $TOOL_DIR (nothing global) and downloads the public
# o200k_base vocabulary once. Skill text never leaves this computer.
if env -u AGENT_HUD_HOME "$PYTHON3" "$TOOL_DIR/server.py" tokens setup; then
  TOKENS_STATUS="Token counting: ready."
else
  TOKENS_STATUS="Token counting: setup FAILED (the dashboard works without it). Retry: $PYTHON3 $TOOL_DIR/server.py tokens setup"
fi

sed -e "s#__HOME__#$HOME#g" -e "s#__PYTHON3__#$PYTHON3#g" \
  "$SRC_DIR/com.agent-hud.plist.template" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo ""
echo "Agent HUD installed and running (launchd service com.agent-hud)."
echo "Dashboard: http://127.0.0.1:41717"
echo "$TOKENS_STATUS"
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
            "command": "nohup python3 \"$HOME/.claude/tools/agent-hud/server.py\" --register \"$PWD\" >/dev/null 2>&1 & disown"
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
