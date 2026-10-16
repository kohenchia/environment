"""The pass_env switch: every session Stella starts runs on the shared credentials, or none does."""

import json
import shutil
import subprocess
import time

import pytest
from test_launch import _wait, fake_claude, tmux  # noqa: F401 - fixtures

needs_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")

ENV_CLAUDE = """#!/bin/sh
echo "$@" >> "{out}/args.txt"
echo "${{DEMO_TOKEN:-unset}}" >> "{out}/passed.txt"
sleep 30
"""


@pytest.fixture
def env_claude(env, fake_claude):  # noqa: F811
    p = env.tmp / "claude-env"
    p.write_text(ENV_CLAUDE.format(out=fake_claude))
    p.chmod(0o755)
    secrets = env.tmp / "secrets"
    secrets.mkdir()
    env.write_config(claude_bin=str(p), claude_query_bin="false", pass_env=["DEMO_TOKEN"], pass_env_dir=str(secrets))
    return fake_claude, secrets


def _launch(env, tmux, name, extra=None):  # noqa: F811
    env.say("A", f"S, build {name}")
    seq = max(e["seq"] for e in env.events() if e["type"] == "order")
    env.run("launch", "builder", "--order", str(seq), "--name", name, env={**tmux, **(extra or {})})


def _lines(path, n, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if path.exists() and len(path.read_text().splitlines()) >= n:
            return path.read_text().splitlines()
        time.sleep(0.1)
    raise AssertionError(f"{path} has fewer than {n} lines")


@needs_tmux
def test_off_removes_the_variable_even_when_tmux_has_it(env, tmux, env_claude):  # noqa: F811
    out, _ = env_claude
    sock = tmux["TMUX"].split(",")[0]
    subprocess.run(["tmux", "-S", sock, "set-environment", "-g", "DEMO_TOKEN", "fromtmux"], check=True)
    env.run("pass-env", "off")
    _launch(env, tmux, "t-off", {"DEMO_TOKEN": "fromcaller"})
    assert _wait(out / "passed.txt").split() == ["unset"]
    assert "unset DEMO_TOKEN" in (env.store / "launch" / "t-off.sh").read_text()


@needs_tmux
def test_on_reads_the_value_from_the_file_when_the_caller_lacks_it(env, tmux, env_claude):  # noqa: F811
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile\n")
    env.run("pass-env", "on")
    _launch(env, tmux, "t-on")
    assert _wait(out / "passed.txt").split() == ["fromfile"]
    assert "fromfile" not in (env.store / "launch" / "t-on.sh").read_text()


def test_on_without_any_value_refuses_to_launch(env, env_claude):
    r = env.run("pass-env", "on", check=False)
    assert r.returncode != 0 and "DEMO_TOKEN has no value" in (r.stdout + r.stderr)
    assert "switch: off (never set" in env.run("pass-env").stdout  # the failed switch left nothing behind


def test_scheduler_waits_rather_than_run_on_the_wrong_credentials(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("pass-env", "on")
    (secrets / "DEMO_TOKEN").unlink()  # the value disappears after the switch
    r = env.run("launch", "builder", "--text", "build q", "--name", "q", "--dry-run", check=False)
    assert r.returncode != 0 and "DEMO_TOKEN" in r.stderr
    env.run("scheduler", "--once")
    assert not (env.store / "scheduler.json").exists()  # the day is not marked done; it is retried
    assert any(e.get("key") == "scheduler:pass-env" for e in env.events())


def test_unset_switch_is_off_whatever_the_caller_has(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.say("A", "S, build u")
    for caller in (None, {"DEMO_TOKEN": "x"}):
        r = env.run("launch", "builder", "--order", "1", "--name", "u", "--dry-run", env=caller)
        assert "unset DEMO_TOKEN" in r.stdout
    assert any(e["type"] == "pass_env" and e["mode"] == "off" and e["by"] == "default" for e in env.events())


@pytest.mark.parametrize("switch, caller, expected", [("off", "fromcaller", "unset"), ("on", None, "fromfile")])
def test_scheduler_headless_runs_follow_the_switch(env, env_claude, switch, caller, expected):
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile")
    env.run("pass-env", switch)
    env.run("nightly", "--date", "2026-01-02", env={"DEMO_TOKEN": caller} if caller else None)
    assert (out / "passed.txt").read_text().split() == [expected]


@needs_tmux
def test_respawn_resumes_a_running_team_on_the_new_setting(env, tmux, env_claude):  # noqa: F811
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile")
    env.run("pass-env", "off")
    _launch(env, tmux, "t-re")
    assert _lines(out / "passed.txt", 1) == ["unset"]
    env.hook("session-start", {"session_id": "sid-1", "source": "startup"}, env={"STELLA_TEAM": "t-re"})
    (env.tmp / "transcripts" / "proj").mkdir(parents=True)
    (env.tmp / "transcripts" / "proj" / "sid-1.jsonl").write_text("{}\n")

    r = env.run("pass-env", "on", "--respawn", "--team", "t-re", env=tmux)
    assert "t-re: restarted" in r.stdout
    assert _lines(out / "passed.txt", 2)[1] == "fromfile"
    args = _lines(out / "args.txt", 2)[1]
    assert "--resume sid-1" in args and "Restarted with pass_env on" in args
    # the old process's SessionEnd is not mistaken for the team quitting
    env.hook("session-end", {"session_id": "sid-1", "reason": "other"}, env={"STELLA_TEAM": "t-re"})
    assert "ended (reason" not in env.run("attention").stdout
    assert any(e["type"] == "respawned" and e["team"] == "t-re" for e in env.events())


@needs_tmux
def test_two_respawns_expect_two_old_processes_and_keep_needs_you(env, tmux, env_claude):  # noqa: F811
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile")
    _launch(env, tmux, "t-two")
    _lines(out / "passed.txt", 1)
    env.hook("session-start", {"session_id": "sid-2", "source": "startup"}, env={"STELLA_TEAM": "t-two"})
    (env.tmp / "transcripts" / "proj").mkdir(parents=True)
    (env.tmp / "transcripts" / "proj" / "sid-2.jsonl").write_text("{}\n")
    env.run("report", "t-two", "which database?", "--needs-you")
    env.run("pass-env", "on", "--respawn", "--team", "t-two", env=tmux)
    _lines(out / "passed.txt", 2)
    env.run("pass-env", "--respawn", "--team", "t-two", env=tmux)
    _lines(out / "passed.txt", 3)
    for _ in range(2):  # both killed processes report their end, late
        env.hook("session-end", {"session_id": "sid-2", "reason": "other"}, env={"STELLA_TEAM": "t-two"})
    att = env.run("attention").stdout
    assert "ended (reason" not in att and "needs you" in att
    env.hook("session-end", {"session_id": "sid-2", "reason": "exit"}, env={"STELLA_TEAM": "t-two"})
    assert "ended (reason: exit)" in env.run("attention").stdout  # a third end is a real exit


def test_respawn_skips_a_team_without_a_window(env, env_claude):
    env.say("A", "S, build g")
    env.run("launch", "builder", "--order", "1", "--name", "g", "--dry-run")
    assert "no such team" in env.run("pass-env", "--respawn", "--team", "g").stdout


def test_switch_is_recorded_in_the_ledger(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("pass-env", "on")
    env.run("pass-env", "on")  # unchanged: no second event
    evs = [e for e in env.events() if e["type"] == "pass_env"]
    assert [e["mode"] for e in evs] == ["on"]
    assert json.loads((env.store / "pass-env.json").read_text())["mode"] == "on"
    assert "switch: on" in env.run("pass-env").stdout


def test_catch_up_waits_for_a_session_on_the_same_credentials(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("pass-env", "on")
    hook_env = {"STELLA_NO_CATCHUP": "0"}
    env.hook("session-start", {"session_id": "S1", "source": "startup"}, env=hook_env)  # no DEMO_TOKEN here
    time.sleep(2)
    assert not (env.store / "catch-up.stamp").exists()
    env.hook("session-start", {"session_id": "S2", "source": "startup"}, env={**hook_env, "DEMO_TOKEN": "v"})
    assert (env.store / "catch-up.stamp").exists()  # this one started the pass


@needs_tmux
@pytest.mark.parametrize("switch, caller", [("on", None), ("on", "x"), ("off", None), ("off", "x")])
def test_plain_run_leaves_the_switch_alone(env, tmux, env_claude, switch, caller):  # noqa: F811
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("pass-env", switch)
    env.run("run", env={**tmux, **({"DEMO_TOKEN": caller} if caller else {})}, check=False)
    assert f"switch: {switch}" in env.run("pass-env").stdout
    env.run("scheduler", "--stop")


@needs_tmux
def test_run_with_a_flag_sets_the_switch(env, tmux, env_claude):  # noqa: F811
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("run", "--pass-env", "on", env=tmux, check=False)
    assert "switch: on" in env.run("pass-env").stdout
    env.run("run", "--pass-env", "off", "--fresh", env=tmux, check=False)
    assert "switch: off" in env.run("pass-env").stdout
    env.run("scheduler", "--stop")


@needs_tmux
def test_run_with_no_switch_recorded_defaults_to_off_and_says_so(env, tmux, env_claude):  # noqa: F811
    r = env.run("run", env={**tmux, "DEMO_TOKEN": "x"}, check=False)
    assert "never set" in r.stdout and "OFF" in r.stdout
    assert "switch: off" in env.run("pass-env").stdout
    env.run("scheduler", "--stop")


def test_status_lists_each_session_without_a_value(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("topsecret")
    env.run("pass-env", "on")
    out = env.run("pass-env").stdout
    assert "sessions (token read" in out and "topsecret" not in out


def test_in_use_reads_names_from_a_process_environment(monkeypatch):
    import os
    import types

    from stella import passenv

    monkeypatch.setattr(passenv, "settings", lambda: types.SimpleNamespace(pass_env=["DEMO_TOKEN"]))
    with_t = subprocess.Popen(["sleep", "5"], env={**os.environ, "DEMO_TOKEN": "s3cret"})
    without = subprocess.Popen(["sleep", "5"], env={k: v for k, v in os.environ.items() if k != "DEMO_TOKEN"})
    try:
        assert passenv.in_use(with_t.pid) == "project"
        assert passenv.in_use(without.pid) == "personal"
        assert passenv.in_use(None) is None
    finally:
        with_t.kill()
        without.kill()


def test_scheduler_alerts_once_while_waiting(env, env_claude):
    _, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("v")
    env.run("pass-env", "on")
    (secrets / "DEMO_TOKEN").unlink()
    for _ in range(3):
        env.run("scheduler", "--once")
    assert sum(e.get("key") == "scheduler:pass-env" for e in env.events()) == 1


def test_headless_runs_are_listed_by_the_resume_picker(env, env_claude):
    """`claude -p` defaults to the `sdk-cli` entrypoint, which the resume picker hides."""
    out, _ = env_claude
    probe = env.tmp / "claude-entry"
    probe.write_text(f'#!/bin/sh\necho "$CLAUDE_CODE_ENTRYPOINT" >> "{out}/entry.txt"\n')
    probe.chmod(0o755)
    env.write_config(claude_bin=str(probe))
    env.run("nightly", "--date", "2026-01-02", env={"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})
    entries = (out / "entry.txt").read_text().split()
    assert entries and set(entries) == {"stella"}
