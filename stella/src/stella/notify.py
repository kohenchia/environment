"""Desktop notifications, best effort, on whatever this machine has."""

from __future__ import annotations

import shutil
import subprocess
import sys


def _osa_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def notify(title: str, message: str) -> bool:
    message = " ".join(message.split())[:220]
    try:
        if sys.platform == "darwin" and shutil.which("osascript"):
            script = f'display notification "{_osa_escape(message)}" with title "{_osa_escape(title)}" sound name "Glass"'
            return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0
        if shutil.which("notify-send"):
            return subprocess.run(["notify-send", title, message], capture_output=True).returncode == 0
        if shutil.which("tmux"):
            return subprocess.run(["tmux", "display-message", f"{title}: {message}"], capture_output=True).returncode == 0
    except OSError:
        pass
    return False
