"""
Lightweight local activity logger.

Records the title of the foreground window whenever it changes, so Milo can answer
"what was I just working on?". Everything stays on-device in `activity_log.jsonl`
(gitignored). Uses the Windows API via ctypes — no extra dependencies.
"""
import os
import json
import ctypes
from datetime import datetime

LOG_PATH = os.path.join(os.path.dirname(__file__), "activity_log.jsonl")
MAX_LINES = 5000  # keep the log from growing unbounded


def get_active_window_title() -> str:
    """Return the title of the current foreground window (Windows only)."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return (buf.value or "").strip()
    except Exception:
        return ""


def record_once(last_title: str) -> str:
    """Append an entry if the active window changed. Returns the new last title."""
    title = get_active_window_title()
    if title and title != last_title:
        entry = {"ts": datetime.now().isoformat(timespec="seconds"), "window": title}
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            _trim_if_needed()
        except Exception as e:
            print(f"[activity] write error: {e}")
        return title
    return last_title


def _trim_if_needed():
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > MAX_LINES:
            with open(LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(lines[-MAX_LINES:])
    except Exception:
        pass


def read_recent(limit: int = 40) -> list:
    """Return the most recent activity entries (list of {ts, window})."""
    if not os.path.exists(LOG_PATH):
        return []
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()[-limit:]
    except Exception:
        return []
    out = []
    for ln in lines:
        try:
            out.append(json.loads(ln))
        except Exception:
            pass
    return out
