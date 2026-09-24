#!/usr/bin/env bash
# Install task-reminder as a launchd agent so it runs on its own, at login,
# with no terminal window open.
set -euo pipefail

LABEL="com.taskreminder.agent"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$HERE/.venv/bin/python"
SCRIPT="$HERE/task-reminder.py"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/task-reminder.log"
DOMAIN="gui/$(id -u)"
LEADS="${LEADS:-10,1}"
INTERVAL="${INTERVAL:-60}"

write_plist() {
  mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
  cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$SCRIPT</string>
    <string>--once</string>
    <string>--lead</string>
    <string>$LEADS</string>
  </array>
  <!-- --once plus StartInterval, rather than one long-lived process: launchd
       restarts it on wake and after crashes, and already-sent pings live in
       the state file, so nothing is lost between runs. -->
  <key>StartInterval</key><integer>$INTERVAL</integer>
  <key>RunAtLoad</key><true/>
  <key>ProcessType</key><string>Background</string>
  <key>EnvironmentVariables</key>
  <dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PLIST_EOF
}

case "${1:-install}" in
  install)
    [ -x "$PY" ] || { echo "No venv at $PY -- run: python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"; exit 1; }
    write_plist
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    launchctl kickstart -k "$DOMAIN/$LABEL"
    echo "Installed $LABEL (every ${INTERVAL}s, pinging ${LEADS} min ahead)."
    echo "Log: $LOG"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "Removed $LABEL."
    ;;
  status)
    launchctl print "$DOMAIN/$LABEL" 2>/dev/null | grep -E "state|last exit|program =" || echo "Not loaded."
    ;;
  logs) tail -n 20 "$LOG" 2>/dev/null || echo "No log yet at $LOG." ;;
  *) echo "usage: $0 [install|uninstall|status|logs]"; exit 1 ;;
esac
