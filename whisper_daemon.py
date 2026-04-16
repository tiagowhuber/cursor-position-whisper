#!/usr/bin/env python3
"""
Whisper Voice Input Daemon
- Listens on a Unix socket for toggle commands
- Pre-loads the whisper model to avoid startup lag
- Records audio with arecord, transcribes with whisper
- Types the result at the current cursor position via ydotool
"""

import os
import sys
import socket
import subprocess
import threading
import signal
import time
import logging
import stat
import unicodedata

# ── Configuration ──────────────────────────────────────────────────────────────
SOCKET_PATH  = "/tmp/whisper_daemon.sock"
AUDIO_FILE   = "/tmp/whisper_audio.wav"
LOG_FILE     = "/tmp/whisper_daemon.log"
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large")      # tiny / base / small / medium
SAMPLE_RATE  = 16000
YDOTOOL_SOCKET = os.environ.get("YDOTOOL_SOCKET", "/tmp/.ydotool_socket")

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


def notify(summary: str, body: str = "", urgency: str = "normal") -> None:
    """Send a desktop notification (best-effort, never raises)."""
    try:
        subprocess.Popen(
            ["notify-send", "-u", urgency, "-t", "3000", summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def load_model():
    import torch
    import whisper

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Loading whisper model '%s' on %s …", WHISPER_MODEL, device)
    if device == "cuda":
        log.info("GPU: %s", torch.cuda.get_device_name(0))

    model = whisper.load_model(WHISPER_MODEL, device=device)
    log.info("Model loaded.")
    return model, device


# ── Daemon ─────────────────────────────────────────────────────────────────────

class WhisperDaemon:
    def __init__(self):
        self.model = None
        self.device = "cpu"
        self.recording_proc = None
        self.is_recording = False
        self._lock = threading.Lock()

    # ── Server ────────────────────────────────────────────────────────────────

    def run(self):
        self.model, self.device = load_model()
        notify("Whisper ready", f"Model: {WHISPER_MODEL}  Device: {self.device}")

        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(SOCKET_PATH)
        # Allow only the current user to connect
        os.chmod(SOCKET_PATH, stat.S_IRUSR | stat.S_IWUSR)
        server.listen(5)
        log.info("Listening on %s", SOCKET_PATH)

        while True:
            try:
                conn, _ = server.accept()
                threading.Thread(
                    target=self._handle_conn, args=(conn,), daemon=True
                ).start()
            except OSError:
                break

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            data = conn.recv(256).decode().strip()
            response = self._dispatch(data)
            conn.sendall(response.encode())
        except Exception as exc:
            log.exception("Handler error: %s", exc)
        finally:
            conn.close()

    def _dispatch(self, cmd: str) -> str:
        if cmd == "toggle":
            return self._toggle()
        if cmd == "status":
            return "recording" if self.is_recording else "idle"
        if cmd == "stop":
            return self._stop_and_transcribe()
        if cmd == "cancel":
            return self._cancel()
        return "unknown_command"

    # ── Recording / Transcription ─────────────────────────────────────────────

    def _toggle(self) -> str:
        with self._lock:
            if self.is_recording:
                return self._stop_and_transcribe()
            return self._start_recording()

    def _start_recording(self) -> str:
        if os.path.exists(AUDIO_FILE):
            os.remove(AUDIO_FILE)

        self.recording_proc = subprocess.Popen(
            ["arecord", "-f", "S16_LE", "-r", str(SAMPLE_RATE), "-c", "1", AUDIO_FILE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.is_recording = True
        log.info("Recording started (pid %d)", self.recording_proc.pid)
        notify("Whisper  ●  Recording", "Press Super+Shift+W again to stop")
        return "started"

    def _stop_and_transcribe(self) -> str:
        if not self.is_recording:
            return "not_recording"

        self.recording_proc.terminate()
        self.recording_proc.wait()
        self.is_recording = False
        log.info("Recording stopped.")
        notify("Whisper  ◼  Transcribing…")

        # Run transcription in a background thread so the hotkey returns fast
        threading.Thread(target=self._transcribe_and_type, daemon=True).start()
        return "transcribing"

    def _cancel(self) -> str:
        with self._lock:
            if not self.is_recording:
                return "not_recording"
            self.recording_proc.terminate()
            self.recording_proc.wait()
            self.is_recording = False
            if os.path.exists(AUDIO_FILE):
                os.remove(AUDIO_FILE)
        log.info("Recording cancelled.")
        notify("Whisper  ✕  Cancelled")
        return "cancelled"

    def _transcribe_and_type(self) -> None:
        try:
            if not os.path.exists(AUDIO_FILE):
                log.warning("Audio file missing — nothing to transcribe.")
                return

            result = self.model.transcribe(
                AUDIO_FILE,
                fp16=(self.device == "cuda"),
            )
            text: str = result["text"].strip()
            # Hotfix: strip accent marks (tildes) and problematic chars
            text = ''.join(
                c for c in unicodedata.normalize('NFD', text)
                if unicodedata.category(c) != 'Mn'
            )
            text = text.replace('¿', '')
            log.info("Transcribed: %r", text)

            if not text:
                notify("Whisper", "No speech detected.", "low")
                return

            # Brief pause so the window focus is settled after the hotkey press
            time.sleep(0.15)
            self._type_text(text)
            notify("Whisper  ✔", text[:80] + ("…" if len(text) > 80 else ""))

        except Exception as exc:
            log.exception("Transcription error: %s", exc)
            notify("Whisper  ✗  Error", str(exc), "critical")
        finally:
            if os.path.exists(AUDIO_FILE):
                os.remove(AUDIO_FILE)

    def _type_text(self, text: str) -> None:
        """
        Type text at the current cursor position using ydotool.
        Falls back to xdotool for XWayland apps if ydotool fails.
        """
        env = os.environ.copy()
        env["YDOTOOL_SOCKET"] = YDOTOOL_SOCKET

        try:
            subprocess.run(
                ["ydotool", "type", "--key-delay=12", "--", text],
                env=env,
                check=True,
                timeout=30,
            )
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            log.warning("ydotool failed (%s), trying xdotool…", exc)
            try:
                subprocess.run(
                    ["xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text],
                    check=True,
                    timeout=30,
                )
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Last resort: clipboard paste
                log.warning("xdotool also failed, using clipboard fallback.")
                self._clipboard_paste(text)

    def _clipboard_paste(self, text: str) -> None:
        """Copy text to clipboard and simulate Ctrl+V."""
        for tool in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
            try:
                subprocess.run(tool, input=text.encode(), check=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
            # Small delay then paste
            time.sleep(0.05)
            try:
                subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], timeout=5)
            except FileNotFoundError:
                subprocess.run(["xdotool", "key", "ctrl+v"], timeout=5)
            return
        log.error("All text injection methods failed.")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    daemon = WhisperDaemon()

    def _shutdown(sig, frame):
        log.info("Received signal %s, shutting down.", sig)
        if os.path.exists(SOCKET_PATH):
            os.remove(SOCKET_PATH)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    daemon.run()


if __name__ == "__main__":
    main()
