"""
Milo's tools — capabilities the LLM can call to actually *do* things.

Each tool is a plain Python function with a clear docstring; the google-genai SDK
reads the signature + docstring to build the function declaration and can call it
automatically. Keep tools safe and non-destructive.
"""
import os
import subprocess

import requests


# Friendly name -> what to launch. Falls back to `start <name>` (resolves App Paths).
_APP_ALIASES = {
    "notepad": "notepad",
    "calculator": "calc",
    "calc": "calc",
    "paint": "mspaint",
    "explorer": "explorer",
    "file explorer": "explorer",
    "files": "explorer",
    "settings": "ms-settings:",
    "chrome": "chrome",
    "google chrome": "chrome",
    "brave": "brave",
    "spotify": "spotify",
    "notion": "notion",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "terminal": "wt",
    "cmd": "cmd",
    "task manager": "taskmgr",
}


def open_application(app_name: str) -> str:
    """Open or launch an application on the user's Windows computer.

    Args:
        app_name: Name of the app to open, e.g. 'notepad', 'chrome', 'spotify',
            'calculator', 'file explorer', 'settings', 'vscode'.

    Returns:
        A short status string describing what happened.
    """
    key = (app_name or "").strip().lower()
    target = _APP_ALIASES.get(key, key)
    try:
        # `start` (cmd builtin) resolves registered app paths and protocols.
        subprocess.Popen(f'start "" "{target}"', shell=True)
        return f"Opened {app_name}."
    except Exception as e:
        return f"Could not open {app_name}: {e}"


def get_tech_news(count: int = 5) -> str:
    """Get the latest top technology news headlines (from Hacker News).

    Args:
        count: How many headlines to fetch (default 5, max 10).

    Returns:
        A newline-separated list of current tech headlines.
    """
    count = max(1, min(int(count or 5), 10))
    try:
        ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=6
        ).json()[:count]
        titles = []
        for i in ids:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{i}.json", timeout=6
            ).json()
            if item and item.get("title"):
                titles.append(f"- {item['title']}")
        if not titles:
            return "I couldn't find any headlines right now."
        return "Latest tech headlines:\n" + "\n".join(titles)
    except Exception as e:
        return f"Could not fetch tech news: {e}"


def get_my_recent_activity(limit: int = 15) -> str:
    """Get a summary of what the user has recently been doing on their computer.

    This reads the recent foreground windows/apps the user has been using, so you can
    reference it (e.g. "what was I working on before lunch?").

    Args:
        limit: How many recent activity entries to include (default 15, max 40).

    Returns:
        A newline-separated, time-stamped list of recent activity.
    """
    import activity_logger

    limit = max(1, min(int(limit or 15), 40))
    entries = activity_logger.read_recent(limit)
    if not entries:
        return "No activity has been logged yet (the logger may have just started)."
    return "Recent activity (oldest first):\n" + "\n".join(
        f"- {e.get('ts', '')}: {e.get('window', '')}" for e in entries
    )


# The tool set exposed to the LLM. Add new tools here.
ALL_TOOLS = [open_application, get_tech_news, get_my_recent_activity]
