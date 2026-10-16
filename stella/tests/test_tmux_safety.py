"""The suite can never reach the owner's real tmux server or signal a process that is not the test's own (see stella.safety)."""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import SOCK_ROOT

from stella import direct, safety, tmuxctl

REAL_DEFAULT = f"/private/tmp/tmux-{os.getuid()}/default"


def test_the_environment_is_cut_off_from_the_real_server():
    assert "TMUX" not in os.environ and "TMUX_PANE" not in os.environ
    assert Path(os.environ["TMUX_TMPDIR"]).resolve().is_relative_to(SOCK_ROOT)
    assert os.environ["STELLA_CLAUDE_PID"] == "0"  # no walking up to the real Claude session
    assert Path(safety.default_socket()).resolve() != Path(REAL_DEFAULT)


@pytest.mark.parametrize("sock", [REAL_DEFAULT, "/tmp/tmux-501/default", "/private/tmp/tmux-501/../tmux-501/default", "/var/empty/x"])
def test_a_socket_outside_the_tests_directories_is_refused(sock):
    with pytest.raises(safety.UnsafeSocket):
        safety.check_socket(sock)
    with pytest.raises(safety.UnsafeSocket):
        tmuxctl.Server(["tmux", "-S", sock], sock, "caller").run("list-sessions")
    with pytest.raises(safety.UnsafeSocket):
        tmuxctl._alive(["tmux", "-S", sock])


def test_a_bare_tmux_or_a_stale_tmux_variable_cannot_reach_the_real_default_socket(monkeypatch):
    monkeypatch.setenv("TMUX_TMPDIR", "/tmp")  # the shell pytest started in
    with pytest.raises(safety.UnsafeSocket):
        tmuxctl._alive(["tmux"])
    monkeypatch.setenv("TMUX", f"{REAL_DEFAULT},123,0")
    with pytest.raises(safety.UnsafeSocket):
        tmuxctl.find_server()


def test_find_server_finds_nothing_when_no_test_server_runs():
    assert tmuxctl.find_server() is None


def test_a_subprocess_inherits_the_refusal(env):
    r = subprocess.run([sys.executable, "-c", "from stella import safety; safety.check_socket(%r)" % REAL_DEFAULT],
                       env={**os.environ, "PYTHONPATH": str(Path(safety.__file__).parents[1])}, capture_output=True, text=True)
    assert r.returncode != 0 and "UnsafeSocket" in r.stderr
    assert env.env["STELLA_TEST_ROOTS"] == os.environ["STELLA_TEST_ROOTS"]


def test_signals_never_reach_pid_one_ourselves_or_our_ancestors():
    for pid in (1, os.getpid(), os.getppid()):
        with pytest.raises(safety.UnsafeSignal):
            safety.kill(pid, signal.SIGTERM)
    with pytest.raises(safety.UnsafeSignal):
        direct._signal(direct.Proc(os.getppid(), 0, "x", 0), signal.SIGKILL)


def test_a_process_outside_the_tests_tree_is_not_signalled():
    # a detached process with none of the test run's environment (new session, reparented) is the shape of the owner's own shell
    p = subprocess.Popen(["/usr/bin/perl", "-e", "use POSIX; exit if fork; POSIX::setsid(); sleep 30"], stdout=subprocess.DEVNULL,
                         env={k: v for k, v in os.environ.items() if not k.startswith("STELLA_TEST")})
    p.wait()
    time.sleep(0.3)
    pids = subprocess.run(["pgrep", "-f", "POSIX::setsid\\(\\); sleep 30"], capture_output=True, text=True).stdout.split()
    try:
        assert pids
        with pytest.raises(safety.UnsafeSignal):
            safety.kill(int(pids[0]), signal.SIGTERM)
    finally:
        for pid in pids:
            os.kill(int(pid), signal.SIGKILL)


def test_a_child_of_the_test_may_be_signalled():
    p = subprocess.Popen(["sleep", "30"])
    safety.kill(p.pid, signal.SIGTERM)
    assert p.wait(5) == -signal.SIGTERM


def test_gg_without_a_pinned_claude_pid_closes_nothing_of_ours(env):
    """The shape of the original accident: a hook subprocess that walks the real process tree finds the real Claude session and its
    window. The tree above pytest must never be signalled, whatever it holds."""
    import json

    e = {k: v for k, v in env.env.items() if k != "STELLA_CLAUDE_PID"}
    r = subprocess.run([str(env.run.__globals__["BIN"]), "hook", "prompt"], capture_output=True, text=True, env=e, cwd=env.tmp,
                       input=json.dumps({"prompt": "gg", "session_id": "s", "cwd": str(env.tmp)}))
    assert os.getppid() > 1 and direct.info(os.getppid())  # still here
    assert "Wrapped up." not in r.stdout or "UnsafeSignal" in r.stderr
