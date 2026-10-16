"""What Stella must never touch from a test run: the owner's real tmux server, and processes that are not the test's own.

Under pytest, conftest sets `STELLA_TEST_ROOTS` (directories, `os.pathsep`-separated) and `STELLA_TEST_PID` (the pytest process).
Both are inherited by every `stella` subprocess a test starts. When they are set:

    tmux socket   must be under one of the roots, or `UnsafeSocket` is raised (tmuxctl checks every tmux call)
    signal to pid must be a descendant of a tmux server whose socket is under a root (a test's pane), or of the test process;
                  never the test process, its ancestors, or a tmux server

Outside a test run only the structural refusals apply: never pid <= 1, never ourselves, never a tmux server. A process group is
never signalled (nothing here calls killpg), so "our own group" cannot be hit by a stray negative pid.
"""

from __future__ import annotations

import os
import subprocess

ROOTS_ENV = "STELLA_TEST_ROOTS"
PID_ENV = "STELLA_TEST_PID"


class UnsafeSocket(RuntimeError):
    """A test tried to reach a tmux socket that is not under the test's own directories."""


class UnsafeSignal(RuntimeError):
    """A test tried to signal a process that is not the test's own."""


def roots() -> list[str] | None:
    """The directories a test may use sockets in, or None when not under test."""
    raw = os.environ.get(ROOTS_ENV)
    return [os.path.realpath(r) for r in raw.split(os.pathsep) if r] if raw else None


def default_socket() -> str:
    """Where a bare `tmux` (no -S, no $TMUX) would look: `$TMUX_TMPDIR/tmux-<uid>/default`."""
    return os.path.join(os.environ.get("TMUX_TMPDIR") or "/tmp", f"tmux-{os.getuid()}", "default")


def _under(path: str, roots: list[str]) -> bool:
    p = os.path.realpath(path)
    return any(p == r or p.startswith(r + os.sep) for r in roots)


def check_socket(sock: str) -> None:
    allowed = roots()
    if allowed is not None and not _under(sock, allowed):
        raise UnsafeSocket(f"refusing tmux socket {sock}: not under the test's directories {allowed}")


def socket_of(args: list[str]) -> str:
    """The socket a tmux command line (`["tmux", "-S", path, ...]` or `["tmux", ...]`) will use."""
    if "-S" in args:
        return args[args.index("-S") + 1]
    tm = os.environ.get("TMUX", "")
    return tm.split(",", 1)[0] if tm else default_socket()


def check_tmux(args: list[str]) -> None:
    """Refuse a tmux call whose socket is not the test's own. `-L name` sockets live under TMUX_TMPDIR."""
    if roots() is None:
        return
    if "-L" in args:
        check_socket(os.path.join(os.environ.get("TMUX_TMPDIR") or "/tmp", f"tmux-{os.getuid()}", args[args.index("-L") + 1]))
    else:
        check_socket(socket_of(args))


def _ppid(pid: int) -> int:
    from stella import direct

    p = direct.info(pid)
    return p.ppid if p else 0


def _test_server_pids(roots: list[str]) -> set[int]:
    """Pids of the tmux servers whose sockets are under the roots (the test's own servers)."""
    out: set[int] = set()
    for root in roots:
        for dirpath, dirs, files in os.walk(root):
            if dirpath[len(root):].count(os.sep) >= 4:
                dirs[:] = []
            for name in files + dirs:
                path = os.path.join(dirpath, name)
                try:
                    if not os.path.exists(path) or (os.stat(path).st_mode & 0o170000) != 0o140000:
                        continue
                    r = subprocess.run(["tmux", "-S", path, "display-message", "-p", "#{pid}"], capture_output=True, text=True, timeout=5)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                if r.returncode == 0 and r.stdout.strip().isdigit():
                    out.add(int(r.stdout.strip()))
    return out


def _stamped(pid: int, runner: int) -> bool:
    """True when the process inherited this test run's environment (a daemon a test started, detached from the process tree)."""
    try:
        out = subprocess.run(["ps", "eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return f"{PID_ENV}={runner} " in out + " " or out.rstrip().endswith(f"{PID_ENV}={runner}")


def check_signal(pid: int) -> None:
    """Raise UnsafeSignal unless signalling `pid` is acceptable (see the module docstring)."""
    from stella import direct

    if pid <= 1 or pid == os.getpid():
        raise UnsafeSignal(f"refusing to signal pid {pid}")
    now = direct.info(pid)
    if now and direct.is_tmux(now):
        raise UnsafeSignal(f"refusing to signal pid {pid}: a tmux server")
    allowed = roots()
    if allowed is None:
        return
    runner = int(os.environ.get(PID_ENV) or 0)
    ancestors, p = set(), runner
    while p > 1 and p not in ancestors:
        ancestors.add(p)
        p = _ppid(p)
    if pid in ancestors:
        raise UnsafeSignal(f"refusing to signal pid {pid}: the test process or one of its ancestors")
    if _stamped(pid, runner):
        return
    servers = _test_server_pids(allowed)
    chain, p = [], pid
    while p > 1 and p not in chain and len(chain) < 60:
        chain.append(p)
        p = _ppid(p)
    if not (set(chain[1:]) & (servers | {runner})):
        raise UnsafeSignal(f"refusing to signal pid {pid}: not a descendant of a test tmux server or of the test process")


def kill(pid: int, sig: int) -> None:
    """os.kill behind the checks. Signal 0 (an existence probe) is never refused."""
    if sig:
        check_signal(pid)
    os.kill(pid, sig)
