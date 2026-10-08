#!/usr/bin/env bash
# Keep the app running in the background on macOS: starts at login and restarts if it stops.
#   scripts/launch-agent.sh install    start now and at every login
#   scripts/launch-agent.sh uninstall  stop and remove
#   scripts/launch-agent.sh status     show whether it is running
#   scripts/launch-agent.sh logs       follow the server log
set -euo pipefail
cd "$(dirname "$0")/.."

LABEL="local.personal-finance-tool"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
# macOS only lets background processes read ~/Documents (and similar folders) through an app the
# user has allowed, so launchd opens this small hidden app, which runs the server.
APP="$HOME/Applications/Personal Finance Tool Server.app"
ROOT="$(pwd)"
PORT="${PFT_PORT:-8020}"
LOG="$ROOT/data/logs/server.log"
DOMAIN="gui/$(id -u)"
SERVER_PATTERN="uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port $PORT\$"

if [ "$(uname)" != "Darwin" ]; then
  echo "This script is for macOS. On Linux, use a systemd user service that runs scripts/dev.sh --no-reload." >&2
  exit 1
fi

xml_escape() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' <<<"$1"; }
applescript_escape() { sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' <<<"$1"; }

wait_until_up() {
  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
      echo "Running at http://127.0.0.1:$PORT/ (log: $LOG)"
      return 0
    fi
    sleep 1
  done
  echo "Installed, but the app is not answering yet." >&2
  echo "If macOS asked whether \"Personal Finance Tool Server\" may access files in a folder, click Allow;" >&2
  echo "otherwise allow it under System Settings > Privacy & Security > Files and Folders. Log: $LOG" >&2
  return 1
}

build_app() {
  local dev log script
  dev="$(applescript_escape "$ROOT/scripts/dev.sh")"
  log="$(applescript_escape "$LOG")"
  script="try
  do shell script \"export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin PFT_PORT=$PORT; \" & ¬
    \"exec /bin/bash \" & quoted form of \"$dev\" & \" --no-reload >> \" & quoted form of \"$log\" & \" 2>&1\"
end try"
  # Folder permission is tied to this exact build, so keep it unless the script changes.
  local stamp="$APP/Contents/Resources/launcher-script.txt"
  if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$script" ]; then
    return
  fi
  rm -rf "$APP"
  mkdir -p "$(dirname "$APP")"
  osacompile -o "$APP" -e "$script"
  printf '%s' "$script" >"$stamp"
  plutil -replace LSUIElement -bool YES "$APP/Contents/Info.plist"  # no Dock icon
  plutil -replace CFBundleIdentifier -string "$LABEL" "$APP/Contents/Info.plist"
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1
}

stop_server() {
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  pkill -f "$SERVER_PATTERN" >/dev/null 2>&1 || true
  pkill -f "$ROOT/scripts/dev.sh --no-reload" >/dev/null 2>&1 || true  # still waiting for folder permission
}

case "${1:-}" in
  install)
    if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1 && ! pgrep -f "$SERVER_PATTERN" >/dev/null; then
      echo "Port $PORT is in use (is the dev server running?). Stop it first, or set PFT_PORT." >&2
      exit 1
    fi
    ./scripts/dev.sh --setup-only
    stop_server
    mkdir -p "$(dirname "$PLIST")" "$(dirname "$LOG")"
    build_app
    cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-W</string>
    <string>-g</string>
    <string>$(xml_escape "$APP")</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
    launchctl bootstrap "$DOMAIN" "$PLIST"
    wait_until_up
    ;;
  uninstall)
    stop_server
    rm -f "$PLIST"
    rm -rf "$APP"
    echo "Removed. The app no longer starts at login."
    ;;
  status)
    if [ -f "$PLIST" ]; then
      echo "Installed (starts at login)."
      curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1 \
        && echo "Answering at http://127.0.0.1:$PORT/" || echo "Not answering on port $PORT; see $LOG"
    else
      echo "Not installed."
    fi
    ;;
  logs)
    exec tail -f "$LOG"
    ;;
  *)
    sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
