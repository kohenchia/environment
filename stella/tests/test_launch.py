"""Requirement 16: every launch is a tmux window running the lead; Stella can type to it."""

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")

FAKE_CLAUDE = """#!/bin/sh
echo "$@" > "{out}/args.txt"
echo "$STELLA_TEAM $STELLA_ORDER" > "{out}/env.txt"
cat > "{out}/typed.txt"
"""


@pytest.fixture
def tmux(env):
    sock = Path(tempfile.mkdtemp(prefix="st", dir="/tmp")) / "s"
    subprocess.run(["tmux", "-S", str(sock), "new-session", "-d", "-s", "work"], check=True, env=env.env)
    yield {"TMUX": f"{sock},0,0"}
    subprocess.run(["tmux", "-S", str(sock), "kill-server"], env=env.env)


@pytest.fixture
def fake_claude(env):
    out = env.tmp / "fake"
    out.mkdir()
    p = env.tmp / "claude-fake"
    p.write_text(FAKE_CLAUDE.format(out=out))
    p.chmod(0o755)
    env.write_config(claude_bin=str(p), tmux_session="work")
    return out


def _wait(path, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and path.read_text().strip():
            return path.read_text()
        time.sleep(0.1)
    raise AssertionError(f"{path} never appeared")


def test_launch_opens_a_window_with_the_lead(env, tmux, fake_claude):
    env.say("A", "S, build a tool that renames photos")
    r = env.run("launch", "builder", "--order", "1", "--name", "photo-renamer", env=tmux)
    assert "tmux window" in r.stdout
    args = _wait(fake_claude / "args.txt")
    assert "--name photo-renamer" in args and "/stella:build S, build a tool" in args
    assert "--append-system-prompt-file" in args
    assert _wait(fake_claude / "env.txt").split() == ["photo-renamer", "1"]
    windows = subprocess.run(["tmux", "-S", tmux["TMUX"].split(",")[0], "list-windows", "-t", "work", "-F", "#{window_name}"],
                             capture_output=True, text=True).stdout.split()
    assert "photo-renamer" in windows
    ev = [e for e in env.events() if e["type"] == "launch"][0]
    assert ev["team"] == "photo-renamer" and ev["order"] == 1 and ev["window"].startswith("@")
    assert "photo-renamer" in env.run("brief").stdout


def test_tell_types_into_the_window(env, tmux, fake_claude):
    env.say("A", "S, build x")
    env.run("launch", "builder", "--order", "1", "--name", "bx", env=tmux)
    _wait(fake_claude / "args.txt")
    env.run("tell", "bx", "use sqlite", env=tmux)
    assert "[Stella] use sqlite" in _wait(fake_claude / "typed.txt")


def test_lead_reports_and_done_reach_attention(env, tmux, fake_claude):
    env.say("A", "S, build y")
    env.run("launch", "builder", "--order", "1", "--name", "by", env=tmux)
    env.run("report", "by", "which database?", "--needs-you")
    assert "needs you" in env.run("attention").stdout
    env.run("done", "by", "built it on branch y")
    att = env.run("attention").stdout
    assert "finished" in att
    assert "#1" not in env.run("orders").stdout  # the order closed with the team


def test_session_end_without_done_is_flagged(env, tmux, fake_claude):
    env.say("A", "S, build z")
    env.run("launch", "builder", "--order", "1", "--name", "bz", env=tmux)
    env.hook("session-end", {"session_id": "L", "reason": "exit"}, env={"STELLA_TEAM": "bz"})
    assert "without reporting done" in env.run("attention").stdout


def test_no_tmux_falls_back_to_background(env, fake_claude):
    env.say("A", "S, build w")
    r = env.run("launch", "builder", "--order", "1", "--name", "bw", "--dry-run")
    assert "STELLA_TEAM=bw" in r.stdout


def test_survives_a_server_restart(env, fake_claude):
    """16b: kill the server, start a new one, launch again; nothing to reconfigure."""
    for i in range(2):
        sock = Path(tempfile.mkdtemp(prefix="st", dir="/tmp")) / "s"
        subprocess.run(["tmux", "-S", str(sock), "new-session", "-d", "-s", "work"], check=True, env=env.env)
        env.say("A", f"S, build round {i}")
        r = env.run("launch", "builder", "--text", f"round {i}", "--name", f"r{i}", env={"TMUX": f"{sock},0,0"})
        assert "tmux window" in r.stdout
        subprocess.run(["tmux", "-S", str(sock), "kill-server"], env=env.env)
