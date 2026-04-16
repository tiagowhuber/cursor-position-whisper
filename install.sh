#!/usr/bin/env bash
# install.sh — Set up the whisper-service environment and systemd user service
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Creating virtual environment…"
python3 -m venv "$SCRIPT_DIR/venv"

echo "==> Installing Python dependencies…"
"$SCRIPT_DIR/venv/bin/pip" install --upgrade pip
"$SCRIPT_DIR/venv/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo "==> Installing system dependencies (arecord, ydotool, notify-send)…"
if command -v apt-get &>/dev/null; then
    sudo apt-get install -y alsa-utils ydotool libnotify-bin
elif command -v pacman &>/dev/null; then
    sudo pacman -S --needed alsa-utils ydotool libnotify
elif command -v dnf &>/dev/null; then
    sudo dnf install -y alsa-utils ydotool libnotify
else
    echo "  WARNING: Could not detect package manager. Install alsa-utils, ydotool, and libnotify manually."
fi

echo "==> Installing systemd user service…"
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"

cat > "$SERVICE_DIR/whisper-daemon.service" <<EOF
[Unit]
Description=Whisper Voice Input Daemon
After=default.target

[Service]
Type=simple
ExecStart=$SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/whisper_daemon.py
Restart=on-failure
RestartSec=5
Environment=WHISPER_MODEL=large

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable whisper-daemon.service

echo ""
echo "Done! To start the daemon:"
echo "  systemctl --user start whisper-daemon"
echo ""
echo "Bind $SCRIPT_DIR/venv/bin/python $SCRIPT_DIR/whisper_toggle.py"
echo "to a keyboard shortcut (e.g. Super+Shift+W) to toggle recording."
