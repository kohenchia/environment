"""The wake line: a team's news is typed into Stella's own window, merged, rate-limited, never as an order.

Delivery tests type into fake windows on a private tmux socket and inject the clock; nothing sleeps
out the real merge window or gap.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from stella import config, ledger, scheduler, wake

needs_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")
OWN = {"STELLA_SELF": "1"}
RULE = "─" * 40
IDLE = f"⏺ ok\n✻ Crunched for 2s · done 1:11 AM\n{RULE}\n❯ \n{RULE}\n  ? for shortcuts\n"
BUSY = f"❯ build it\n✢ Pontificating…\n{RULE}\n❯ \n{RULE}\n  ? for shortcuts\n"
FAKE_PANE = """#!/bin/sh
cat "{screen}"
stty -echo
exec cat >> "{typed}"
"""


def _later(seconds: float) -> dt.datetime:
    return ledger.now() + dt.timedelta(seconds=seconds)


# ---------------------------------------------------------------- idle detection, on real captures


@pytest.mark.parametrize("screen, expected", [
    (IDLE, True),
    (BUSY, False),
    # the hint shown in an empty box is dim, with the cursor (reverse video) on its first letter
    (f"{RULE}\n\x1b[39m❯ \x1b[7mT\x1b[0;2mry\x1b[0m \x1b[2m\"refactor\x1b[0m \x1b[2m.vimrc\"\x1b[0m\n{RULE}\n", True),
    (f"{RULE}\n\x1b[39m❯ \x1b[7m \x1b[0m\n{RULE}\n", True),
    # the owner's draft: typing now would add to it and send it
    (f"{RULE}\n\x1b[39m❯ \x1b[38;5;231mThink about it\x1b[39m\x1b[7m \x1b[0m\n{RULE}\n", False),
    (f"✻ Thinking… (5s · esc to interrupt)\n{RULE}\n❯ \n{RULE}\n", False),
    ("Do you want to proceed?\n❯ 1. Yes\n  2. No\n", False),  # a permission prompt replaces the box
    (f"╭{'─' * 40}╮\n│ >                                      │\n╰{'─' * 40}╯\n", True),
    ("$ \n", False),  # a shell, not Claude Code
])
def test_idle_reads_claude_codes_screen(screen, expected):
    assert wake.idle(screen) is expected


# ---------------------------------------------------------------- what wakes her (ledger only)


@pytest.fixture
def quiet(env):
    """No helper processes: these tests drive delivery themselves."""
    env.env["STELLA_NO_WAKE"] = "1"
    return env


def _check(env):
    return env.run("scheduler", "--wake-check").stdout.strip()


def test_done_needs_you_and_unexpected_exit_are_pending(quiet):
    env = quiet
    assert _check(env) == "nothing pending"
    env.run("done", "alpha", "built it")
    assert _check(env) == "not-running"  # pending, but she isn't running, so nothing is typed
    for ev, expected in [({"type": "done", "team": "a"}, "finished"),
                         ({"type": "report", "team": "a", "needs_you": True}, "needs you"),
                         ({"type": "ended", "team": "a", "reason": "other"}, "exited unexpectedly"),
                         ({"type": "ended", "team": "a"}, "exited unexpectedly")]:
        assert wake.phrase(ev) == expected


def test_plain_report_and_hand_closed_windows_never_wake(quiet):
    env = quiet
    env.run("report", "alpha", "halfway")
    for reason in ("prompt_input_exit", "clear", "logout"):
        assert wake.phrase({"type": "ended", "team": "a", "reason": reason}) is None
    assert wake.phrase({"type": "ended", "team": "a", "reason": "other", "window_closed": True}) is None
    env.hook("session-end", {"session_id": "s", "reason": "prompt_input_exit"}, env={"STELLA_TEAM": "alpha"})
    assert _check(env) == "nothing pending"


# ---------------------------------------------------------------- follow-ups


def _launch_event(env, team, window=None, socket=None):
    d = env.store / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    seq = int((d / "seq").read_text()) + 1 if (d / "seq").exists() else 1
    ev = {"seq": seq, "ts": ledger.now().isoformat(timespec="seconds"), "type": "launch", "team": team,
          "archetype": "builder", "window": window, "socket": socket}
    with (d / f"{ledger.now():%Y-%m}.jsonl").open("a") as f:
        f.write(json.dumps({k: v for k, v in ev.items() if v is not None}) + "\n")
    (d / "seq").write_text(str(seq))


def test_followup_is_waiting_then_ready(quiet):
    env = quiet
    _launch_event(env, "alpha")
    _launch_event(env, "beta")
    out = env.run("followup", "add", "clean up the worktrees", "--after", "alpha, beta").stdout
    assert "waiting on alpha (running), beta (running)" in out
    env.run("done", "alpha", "ok")
    brief = env.run("brief").stdout
    assert "Follow-ups:" in brief and "#3 waiting on beta (running)" in brief
    env.run("done", "beta", "ok")
    listed = env.run("followup", "list").stdout
    assert "#3 READY (alpha, beta finished)" in listed and "clean up the worktrees" in listed
    env.run("followup", "close", "3")
    assert "No open follow-ups" in env.run("followup", "list").stdout
    assert "[done]" in env.run("followup", "list", "--all").stdout
    assert "Follow-ups" not in env.run("brief").stdout


def test_followup_names_teams_not_launched_and_crashed(quiet):
    env = quiet
    _launch_event(env, "alpha")
    env.hook("session-end", {"session_id": "s", "reason": "other"}, env={"STELLA_TEAM": "alpha"})
    out = env.run("followup", "add", "merge both", "--after", "alpha,gamma").stdout
    assert "alpha (ended), gamma (not launched)" in out
    r = env.run("followup", "done", "99", check=False)
    assert r.returncode != 0 and "no follow-up #99" in r.stderr


def test_followup_already_ready_when_added(quiet):
    env = quiet
    _launch_event(env, "alpha")
    env.run("done", "alpha", "ok")
    assert "READY now" in env.run("followup", "add", "ship it", "--after", "alpha").stdout


# ---------------------------------------------------------------- the hook: a wake line is not an order


def test_wake_line_is_a_system_note_not_an_order(quiet):
    env = quiet
    env.say("H", "rename the photos", env=OWN)  # the owner's order #1
    _launch_event(env, "alpha")
    env.run("followup", "add", "tidy up", "--after", "alpha")
    env.run("done", "alpha", "built it")
    before = [e for e in env.events() if e["type"] in {"order", "close"}]
    out = env.say("H", "[Stella] Team alpha finished. Review your open follow-ups and the fleet.", env=OWN)
    assert "not by the user" in out and "It is not an order" in out
    assert "#3 READY (alpha finished)" in out
    assert "Recorded as ledger" not in out
    assert [e for e in env.events() if e["type"] in {"order", "close"}] == before
    assert "#1" in env.run("orders").stdout  # still open: the line closed nothing
    assert "POSSIBLE CONFLICT" not in out


def test_owner_turn_carries_what_came_while_she_was_busy(quiet):
    env = quiet
    env.hook("session-start", {"session_id": "H", "source": "startup"}, env=OWN)
    env.run("done", "alpha", "built it")
    out = env.say("H", "what's up?", env=OWN)
    assert "Since your last turn: Team alpha finished" in out
    assert "Recorded as ledger" in out  # the owner's own message is still recorded
    again = env.say("H", "and now?", env=OWN)
    assert "Since your last turn" not in again  # delivered once
    assert _check(env) == "nothing pending"


def test_stella_prefix_in_a_team_window_is_unchanged(quiet):
    env = quiet
    team = {"STELLA_TEAM": "alpha"}
    env.hook("prompt", {"prompt": "/stella:build x", "session_id": "T", "cwd": "/tmp"}, env=team)
    assert env.hook("prompt", {"prompt": "[Stella] use sqlite", "session_id": "T", "cwd": "/tmp"}, env=team) is None
    assert not [e for e in env.events() if e["type"] in {"order", "direct"}]


# ---------------------------------------------------------------- delivery into fake windows


class Fake:
    def __init__(self, env, sock: Path):
        self.env, self.sock = env, sock
        self.n = 0

    def tmux(self, *a):
        return subprocess.run(["tmux", "-S", str(self.sock), *a], capture_output=True, text=True,
                              env=self.env.env).stdout.strip()

    def window(self, name="stella", screen=IDLE):
        self.n += 1
        d = self.env.tmp / f"pane{self.n}"
        d.mkdir()
        (d / "screen").write_text(screen)
        (d / "typed").write_text("")
        script = d / "run.sh"
        script.write_text(FAKE_PANE.format(screen=d / "screen", typed=d / "typed"))
        script.chmod(0o755)
        out = self.tmux("new-window", "-d", "-P", "-F", "#{window_id} #{pane_id}", "-t", "work:", "-n", name, str(script))
        wid, pid = out.split()
        _wait_for(lambda: "❯" in self.tmux("capture-pane", "-p", "-t", pid) or "$" in screen)
        return wid, pid, d / "typed"

    def stella_running(self, pane=None):
        rec = {"pid": os.getpid(), "socket": str(self.sock), "pane": pane}
        (self.env.store / "stella-session.json").write_text(json.dumps(rec))


def _wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _typed(path: Path, timeout=3.0) -> str:
    _wait_for(lambda: path.read_text().strip(), timeout)
    return path.read_text()


@pytest.fixture
def fake(quiet, monkeypatch):
    sock = Path(tempfile.mkdtemp(prefix="sw", dir="/tmp")) / "s"
    subprocess.run(["tmux", "-S", str(sock), "new-session", "-d", "-s", "work"], check=True, env=quiet.env)
    for k in ("STELLA_STORE", "STELLA_CONFIG", "TMUX_TMPDIR", "HOME", "STELLA_NO_WAKE"):
        monkeypatch.setenv(k, quiet.env[k])
    monkeypatch.setenv("TMUX", f"{sock},0,0")
    config.settings.cache_clear()
    yield Fake(quiet, sock)
    subprocess.run(["tmux", "-S", str(sock), "kill-server"], env=quiet.env)
    config.settings.cache_clear()


@needs_tmux
def test_events_within_the_merge_window_share_one_line_and_lines_are_a_minute_apart(fake):
    _, pane, typed = fake.window()
    fake.stella_running(pane)
    ledger.append("done", team="alpha", text="ok")
    ledger.append("report", team="beta", text="which db?", needs_you=True)
    assert wake.deliver(_later(5)).status == "wait"  # still collecting
    assert typed.read_text() == ""
    r = wake.deliver(_later(21))
    assert r.status == "sent"
    first = _typed(typed)
    assert first.startswith("[Stella] Team alpha finished; team beta needs you. Review your open follow-ups")
    assert first.count("[Stella]") == 1
    ledger.append("done", team="beta", text="ok")
    r = wake.deliver(_later(50))
    assert r.status == "wait" and r.wait > 0  # under a minute since the last line
    assert wake.deliver(_later(82)).status == "sent"
    assert _wait_for(lambda: typed.read_text().count("[Stella]") == 2)
    assert "Team beta finished." in typed.read_text().splitlines()[-1]
    assert wake.deliver(_later(200)).status == "nothing"
    assert [e["type"] for e in fake.env.events()].count("wake") == 2


@needs_tmux
def test_busy_waits_then_delivers_when_idle(fake, monkeypatch):
    _, pane, typed = fake.window()
    fake.stella_running(pane)
    ledger.append("done", team="alpha", text="ok")
    shown = {"screen": BUSY}
    monkeypatch.setattr(wake, "screen", lambda t: shown["screen"])
    assert wake.deliver(_later(30)).status == "busy"
    time.sleep(0.3)
    assert typed.read_text() == ""
    shown["screen"] = IDLE
    assert wake.deliver(_later(33)).status == "sent"
    assert "Team alpha finished" in _typed(typed)


@needs_tmux
def test_helper_waits_out_a_busy_turn(fake, monkeypatch):
    _, pane, typed = fake.window()
    fake.stella_running(pane)
    ledger.append("done", team="alpha", text="ok")
    screens = iter([BUSY, BUSY])
    monkeypatch.setattr(wake, "screen", lambda t: next(screens, IDLE))
    clock = iter(range(0, 10_000, 1))
    real = wake.deliver
    monkeypatch.setattr(wake, "deliver", lambda now=None: real(_later(30)))
    log = wake.helper(sleep=lambda s: None, clock=lambda: next(clock))
    assert [x.split()[1] for x in log] == ["busy", "busy", "sent", "nothing"]
    assert "Team alpha finished" in _typed(typed)


@needs_tmux
def test_no_window_or_two_windows_types_nothing_and_alerts(fake):
    fake.stella_running()
    ledger.append("done", team="alpha", text="ok")
    r = wake.deliver(_later(30))
    assert r.status == "no-window" and "0 tmux windows named 'stella'" in r.detail
    _, _, t1 = fake.window()
    _, _, t2 = fake.window()
    r = wake.deliver(_later(31))
    assert r.status == "no-window" and "2 tmux windows" in r.detail
    time.sleep(0.3)
    assert t1.read_text() == t2.read_text() == ""
    alerts = [e for e in fake.env.events() if e["type"] == "alert" and e["key"] == wake.ALERT_KEY]
    assert len(alerts) == 2  # one per distinct problem, not one per attempt
    wake.deliver(_later(32))
    assert len([e for e in fake.env.events() if e["type"] == "alert"]) == 2
    assert "wake line not typed" in fake.env.run("attention").stdout


@needs_tmux
def test_never_types_into_a_team_window(fake):
    wid, _, typed = fake.window(name="stella")
    _launch_event(fake.env, "alpha", window=wid, socket=str(fake.sock))  # a team's window, whatever its name
    fake.stella_running()
    ledger.append("done", team="alpha", text="ok")
    assert wake.deliver(_later(30)).status == "no-window"
    time.sleep(0.3)
    assert typed.read_text() == ""


@needs_tmux
def test_hand_closed_team_window_does_not_wake(fake):
    wid, _, _ = fake.window(name="alpha", screen="$ \n")
    _launch_event(fake.env, "alpha", window=wid, socket=str(fake.sock))
    fake.tmux("kill-window", "-t", wid)
    fake.env.hook("session-end", {"session_id": "s", "reason": "other"}, env={"STELLA_TEAM": "alpha"})
    ended = [e for e in fake.env.events() if e["type"] == "ended"][0]
    assert ended["window_closed"] is True
    fake.stella_running()
    assert wake.deliver(_later(30)).status == "nothing"


@needs_tmux
def test_backstop_sends_a_ready_followup_and_is_silent_otherwise(fake, monkeypatch):
    _, pane, typed = fake.window()
    fake.stella_running(pane)
    called = []
    real_target = wake.target
    monkeypatch.setattr(wake, "target", lambda: called.append(1) or real_target())
    assert scheduler.wake_backstop(_later(0)) is None
    assert called == []  # nothing pending: her window is not even looked at
    _launch_event(fake.env, "alpha")
    fake.env.run("followup", "add", "tidy up", "--after", "alpha")
    ledger.append("done", team="alpha", text="ok")
    wake.cover_all()  # say the done event's own line was typed, but the follow-up was never mentioned
    with wake._locked() as w:
        w["followups_seen"] = []
    assert "sent" in scheduler.wake_backstop(_later(30))
    assert "[Stella] Follow-up #2 is READY." in _typed(typed)
    assert scheduler.wake_backstop(_later(3600)) is None  # told once


# ---------------------------------------------------------------- end to end, through the CLI


@needs_tmux
def test_stella_done_types_the_wake_line_into_her_window(fake):
    env = fake.env
    del env.env["STELLA_NO_WAKE"]
    env.write_config(wake_merge_seconds=1)
    _, pane, typed = fake.window()
    fake.stella_running(pane)
    env.run("done", "alpha", "built it on branch a", env={"TMUX": f"{fake.sock},0,0"})
    assert _wait_for(lambda: "[Stella]" in typed.read_text(), timeout=10)
    assert typed.read_text().startswith("[Stella] Team alpha finished. Review your open follow-ups")
    assert [e for e in env.events() if e["type"] == "wake"][0]["pane"] == pane
