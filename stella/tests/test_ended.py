"""A team's session ending: what is said, what notifies, what raises attention."""

import json
import stat

import pytest

TEAM = {"STELLA_TEAM": "alpha"}


@pytest.fixture
def notified(env):
    """Fake desktop notifiers on PATH that append their arguments to a file."""
    bin_ = env.tmp / "fakebin"
    bin_.mkdir()
    log = env.tmp / "notifications.log"
    for name in ("osascript", "notify-send"):
        f = bin_ / name
        f.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> {log}\n')
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    env.env["PATH"] = f"{bin_}:{env.env['PATH']}"
    env.env["STELLA_NO_NOTIFY"] = "0"  # these fakes are safe; let the real code path run
    return lambda: log.read_text() if log.exists() else ""


@pytest.fixture
def team(env):
    """Order #1 is open and team alpha is launched for it (a launch event, no tmux window)."""
    d = env.store / "ledger"
    d.mkdir(parents=True)
    evs = [
        {"seq": 1, "type": "order", "kind": "instruction", "text": "build the thing", "session": "x", "targets": []},
        {"seq": 2, "type": "launch", "team": "alpha", "archetype": "builder", "order": 1},
    ]
    with (d / "2026-10.jsonl").open("w") as f:
        for e in evs:
            f.write(json.dumps({"ts": "2026-10-15T10:00:00+00:00", **e}) + "\n")
    (d / "seq").write_text("2")
    return env


def _end(env, reason):
    env.hook("session-end", {"session_id": "s", "reason": reason}, env=TEAM)


def _attention(env):
    return env.run("attention").stdout


def test_unexpected_exit_notifies_with_reason_and_last_report(team, notified):
    team.run("report", "alpha", "halfway through the tests")
    _end(team, "other")
    msg = notified()
    assert "Team alpha exited unexpectedly. Last report: halfway through the tests" in msg
    assert "team alpha exited unexpectedly. Last report: halfway" in _attention(team)
    assert team.events()[-1]["reason"] == "other"


def test_missing_reason_is_unexpected(team, notified):
    _end(team, None)
    assert "Team alpha exited unexpectedly" in notified()


def test_unknown_reason_is_shown_raw(team, notified):
    _end(team, "cosmic_ray")
    assert "Team alpha ended (reason: cosmic_ray)" in notified()


def test_deliberate_exit_with_open_order_is_attention_only(team, notified):
    _end(team, "prompt_input_exit")
    assert notified() == ""
    assert team.events()[-1]["type"] == "ended"
    assert "team alpha was closed by hand with its order still open" in _attention(team)
    assert "alpha was closed by hand" in team.run("brief").stdout


def test_deliberate_exit_with_closed_order_shows_nothing(team, notified):
    team.run("close", "1", "--status", "cancelled")
    _end(team, "prompt_input_exit")
    assert notified() == ""
    assert team.events()[-1]["type"] == "ended"
    assert "alpha" not in _attention(team)
    assert "team alpha" not in team.run("brief").stdout.split("Open orders")[0]


def test_done_team_never_raises_it(team, notified):
    team.run("done", "alpha", "all finished")
    before = notified()
    for reason in ("other", "prompt_input_exit"):
        _end(team, reason)
    assert notified() == before
    assert not [e for e in team.events() if e["type"] == "ended"]
    assert "exited" not in _attention(team) and "closed by hand" not in _attention(team)
