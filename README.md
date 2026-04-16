# whisper-service

A lightweight voice-input daemon that pre-loads OpenAI Whisper and types transcribed speech at your cursor position. Triggered by a keyboard shortcut.

## How it works

- `whisper_daemon.py` — long-running process that pre-loads the Whisper model and listens on a Unix socket (`/tmp/whisper_daemon.sock`) for commands.
- `whisper_toggle.py` — lightweight script you bind to a hotkey. Each press toggles recording on/off. When stopped, the audio is transcribed and typed at the current cursor.

## Requirements

- Python 3.10+
- `arecord` (alsa-utils)
- `ydotool` (Wayland) and/or `xdotool` (X11) for text injection
- `notify-send` (libnotify) for desktop notifications

## Installation

```bash
chmod +x install.sh
./install.sh
```

This will:
1. Create a Python virtual environment (`venv/`)
2. Install Python dependencies (`openai-whisper`, `torch`)
3. Install system packages (arecord, ydotool, notify-send)
4. Install and enable a systemd user service that auto-starts on login

## Usage

Start the daemon:
```bash
systemctl --user start whisper-daemon
```

Stop the daemon:
```bash
systemctl --user stop whisper-daemon
```

Check logs:
```bash
journalctl --user -u whisper-daemon -f
# or
tail -f /tmp/whisper_daemon.log
```

### Keyboard shortcut

Bind the following command to a hotkey (e.g. `Super+Shift+W`):
```
/path/to/whisper-service/venv/bin/python /path/to/whisper-service/whisper_toggle.py
```

In GNOME: **Settings → Keyboard → Custom Shortcuts**.

### Toggle commands

`whisper_toggle.py` accepts an optional argument:

| Command | Effect |
|---------|--------|
| `toggle` (default) | Start recording, or stop and transcribe |
| `stop` | Stop and transcribe |
| `cancel` | Stop and discard recording |
| `status` | Print `recording` or `idle` |

## Configuration

Set the Whisper model via an environment variable (default: `large`):

```ini
# ~/.config/systemd/user/whisper-daemon.service
Environment=WHISPER_MODEL=medium
```

Available models: `tiny`, `base`, `small`, `medium`, `large`

After changing, reload:
```bash
systemctl --user daemon-reload && systemctl --user restart whisper-daemon
```
