#!/usr/bin/env python3
"""
whisper_toggle.py — Send 'toggle' to the whisper daemon.
Bound to Super+Shift+W in GNOME keyboard shortcuts.
"""

import os
import socket
import sys
import subprocess

SOCKET_PATH = "/tmp/whisper_daemon.sock"


def send(command: str) -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(5)
        s.connect(SOCKET_PATH)
        s.sendall(command.encode())
        return s.recv(256).decode().strip()


def notify(msg: str) -> None:
    try:
        subprocess.Popen(
            ["notify-send", "-u", "critical", "-t", "4000", "Whisper", msg],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"

    if not os.path.exists(SOCKET_PATH):
        notify("Daemon not running.\nStart it with: systemctl --user start whisper-daemon")
        sys.exit(1)

    try:
        response = send(cmd)
        print(response)
    except (ConnectionRefusedError, TimeoutError, OSError) as exc:
        notify(f"Could not reach daemon: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
