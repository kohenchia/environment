"""No-op stand-in for the setproctitle package, macOS only.

On macOS the real package renames a process through private LaunchServices
calls (_LSSetApplicationInformationItem), and every rename is broadcast to
every GUI app, which answers it on its main thread with a synchronous call to
launchservicesd. pytest-xdist renames each worker before and after every
test, so one `pytest -n 4` over ~12k tests sends ~25k broadcasts, and several
agents running suites at once freeze Safari, Slack and the terminal for
minutes at a time with the CPU mostly idle.

local/.zshrc puts this directory on PYTHONPATH on macOS, ahead of every
venv's site-packages, so `import setproctitle` resolves here. The API matches
upstream's own pure-Python fallback (the one it uses when its C extension is
missing): process titles stop changing and nothing else does.
"""

import sys

__version__ = "0.0.0+noop"

__all__ = [
    "setproctitle",
    "getproctitle",
    "setthreadtitle",
    "getthreadtitle",
]


def setproctitle(title: str) -> None:
    return None


def getproctitle() -> str:
    return " ".join(sys.argv)


def setthreadtitle(title: str) -> None:
    return None


def getthreadtitle() -> str:
    return ""
