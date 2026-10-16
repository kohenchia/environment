"""The wrap-up sweep: which finished teams are closed, and why the others stay open."""

import datetime as dt
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


class Ledger:
    """Writes ledger events by hand so a team can have finished any number of minutes ago."""

    def __init__(self, env):
        self.env = env
        self.d = env.store / "ledger"
        self.d.mkdir(parents=True)
        self.seq = 0

    def add(self, type_, ago=0, **f):
        self.seq += 1
        ts = (dt.datetime.now().astimezone() - dt.timedelta(minutes=ago)).isoformat(timespec="seconds")
        with (self.d / f"{ts[:7]}.jsonl").open("a") as fh:
            fh.write(json.dumps({"seq": self.seq, "ts": ts, "type": type_, **f}) + "\n")
        (self.d / "seq").write_text(str(self.seq))
        return self.seq

    def team(self, name="alpha", archetype="builder", dir="/tmp", done_ago=10, window=None, socket=None, reports=(), **launch):
        base = 10 if done_ago is None else done_ago
        o = self.add("order", ago=base + 30, kind="instruction", text=f"build {name}", session="x", targets=[])
        self.add("launch", ago=base + 20, team=name, archetype=archetype, order=o, dir=dir, window=window,
                 socket=socket, **launch)
        self.add("started", ago=base + 20, team=name, session=f"sess-{name}")
        for text in reports:
            self.add("report", ago=base + 10, team=name, text=text)
        if done_ago is not None:
            self.add("done", ago=done_ago, team=name, text="built it")
        return o


@pytest.fixture
def led(env):
    return Ledger(env)


def _types(env):
    return [e["type"] for e in env.events()]


def _sweep(env, *flags):
    return env.run("wrapup", *flags).stdout


def _repo(env, name="proj", remote=True):
    r = env.tmp / "repos" / name
    r.mkdir(parents=True)
    env.git(r, "init", "-q")
    (r / "a.txt").write_text("a\n")
    env.git(r, "add", ".")
    env.git(r, "commit", "-q", "-m", "init")
    if remote:
        bare = env.tmp / f"{name}.git"
        subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True, env=env.env)
        env.git(r, "remote", "add", "origin", str(bare))
        env.git(r, "push", "-q", "-u", "origin", "main")
    return r


def test_clean_team_after_grace_is_wrapped_up(env, led):
    r = _repo(env)
    o = led.team(dir=str(r), done_ago=10)
    out = _sweep(env)
    assert "wrapped up alpha" in out
    assert "reaped" in _types(env) and "wrapped_up" in _types(env)
    ev = [e for e in env.events() if e["type"] == "wrapped_up"][0]
    assert ev["team"] == "alpha" and any("repos clean" in c for c in ev["checked"])
    assert "alpha" not in env.run("attention").stdout  # the finished notice was acked
    assert "Finished, not wrapped up" not in env.run("brief").stdout
    assert [x for x in env.run("orders", "--all").stdout.splitlines() if x.startswith(f"#{o} [done")]


def test_not_before_the_grace_period(env, led):
    r = _repo(env)
    led.team(dir=str(r), done_ago=2)
    assert "grace period" in _sweep(env)
    assert "wrapped_up" not in _types(env)
    env.write_config(wrapup_grace_minutes=1)
    assert "wrapped up alpha" in _sweep(env)


def test_owner_typing_restarts_the_grace_period(env, led):
    r = _repo(env)
    led.team(dir=str(r), done_ago=30)
    led.add("direct", ago=1, team="alpha", text="one more question")
    assert "grace period" in _sweep(env)


def test_dry_run_changes_nothing(env, led):
    r = _repo(env)
    led.team(dir=str(r), done_ago=10)
    before = _types(env)
    out = _sweep(env, "--dry-run")
    assert "would wrap up alpha" in out
    assert _types(env) == before


def test_needs_you_blocks(env, led):
    led.team(done_ago=None)
    led.add("report", ago=10, team="alpha", text="which db?", needs_you=True)
    led.add("ended", ago=10, team="alpha", reason="prompt_input_exit")
    assert "needs-you: which db?" in _sweep(env, "--dry-run")


def test_unfinished_team_is_not_touched(env, led):
    led.team(done_ago=None)
    out = _sweep(env)
    assert "wrapped_up" not in _types(env) and "still running" not in out  # not listed outside dry-run
    assert "still running" in _sweep(env, "--dry-run")


def test_keep_open_archetype_is_respected(env, led):
    env.extension(teams='[team.reviewer]\nsummary = "s"\nwhen = "w"\nkeep_open = true\n')
    r = _repo(env)
    led.team(archetype="reviewer", dir=str(r), done_ago=60)
    assert "keep_open" in _sweep(env)
    assert "wrapped_up" not in _types(env)


def test_unpushed_commits_block_and_pushing_unblocks(env, led):
    r = _repo(env)
    (r / "b.txt").write_text("b\n")
    env.git(r, "add", ".")
    env.git(r, "commit", "-q", "-m", "more")
    led.team(dir=str(r))
    assert "1 unpushed commit in proj" in _sweep(env)
    env.git(r, "push", "-q")
    assert "wrapped up alpha" in _sweep(env)


def test_repo_without_a_remote_needs_no_push(env, led):
    r = _repo(env, remote=False)
    led.team(dir=str(r))
    assert "wrapped up alpha" in _sweep(env)


def test_uncommitted_changes_block(env, led):
    r = _repo(env)
    (r / "a.txt").write_text("changed\n")
    led.team(dir=str(r))
    assert "uncommitted changes in proj" in _sweep(env)


def test_repo_named_in_a_report_is_checked(env, led):
    r = _repo(env)
    other = _repo(env, "named")
    (other / "wip.txt").write_text("x\n")
    led.team(dir=str(r), reports=[f"edited {other}/wip.txt"])
    assert "uncommitted changes in named" in _sweep(env)


def test_open_followup_blocks(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.add("followup", ago=5, text="then do Z", after=["alpha"])
    assert "follow-up #" in _sweep(env)


def test_deferred_push_blocks(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.add("push_question", ago=8, repo="proj", sha="abc1234", branch="x", session="sess-alpha")
    out = _sweep(env)
    assert "deferred push" in out and "wrapped_up" not in _types(env)
    led.add("push", repo="proj", sha="abc1234", ref="refs/heads/x")
    assert "wrapped up alpha" in _sweep(env)


def test_team_that_died_unexpectedly_stays_open(env, led):
    led.team(done_ago=None)
    led.add("ended", ago=10, team="alpha", reason="other")
    assert "exited unexpectedly" in _sweep(env)


def test_brief_lists_the_reason(env, led):
    r = _repo(env)
    led.team(dir=str(r), done_ago=1)
    brief = env.run("brief").stdout
    assert "Finished, not wrapped up:" in brief and "alpha" in brief and "grace period" in brief
    assert "Finished, not wrapped up" in env.say("S", "S, status?")


def test_wake_line_names_the_sweep(env):
    from stella import wake  # noqa: PLC0415

    assert "Finished, not wrapped up" in wake.instruction()


def test_attention_still_lists_a_team_that_cannot_be_wrapped(env, led):
    r = _repo(env)
    (r / "a.txt").write_text("changed\n")
    led.team(dir=str(r))
    _sweep(env)
    assert "alpha finished" in env.run("attention").stdout


# ---- with a real window, on a private tmux server

PROMPT = """#!/bin/sh
printf '\\n%s\\n❯ \\n%s\\n' "$LINE" "$LINE"
sleep 600
"""
BUSY = """#!/bin/sh
printf '\\n✻ Pondering… (3s · esc to interrupt)\\n%s\\n❯ \\n%s\\n' "$LINE" "$LINE"
sleep 600
"""


@pytest.fixture
def window(env):
    if not shutil.which("tmux"):
        pytest.skip("needs tmux")
    sock = Path(tempfile.mkdtemp(prefix="st", dir="/tmp")) / "s"
    tm = lambda *a: subprocess.run(["tmux", "-S", str(sock), *a], capture_output=True, text=True, env=env.env)  # noqa: E731
    tm("new-session", "-d", "-s", "work")
    line = "─" * 40

    def make(script):
        p = env.tmp / "fake.sh"
        p.write_text(script)
        p.chmod(0o755)
        wid = tm("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "=work:", "-n", "alpha", "-e", f"LINE={line}", str(p)).stdout.strip()
        import time

        time.sleep(0.5)
        return wid, str(sock), tm

    yield make
    tm("kill-server")


def test_idle_session_window_is_closed_and_verified(env, led, window):
    r = _repo(env)
    wid, sock, tm = window(PROMPT)
    led.team(dir=str(r), window=wid, socket=sock)
    out = env.run("wrapup", env={"TMUX": f"{sock},0,0"}).stdout
    assert "wrapped up alpha" in out and "session idle" in out
    assert "alpha" not in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_busy_session_is_left_open(env, led, window):
    r = _repo(env)
    wid, sock, tm = window(BUSY)
    led.team(dir=str(r), window=wid, socket=sock)
    out = env.run("wrapup", env={"TMUX": f"{sock},0,0"}).stdout
    assert "busy" in out
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_auto_sweep_is_off_by_default(env):
    from stella.config import Settings

    assert Settings().wrapup_auto is False


def test_wrap_closes_this_window_and_records_the_team(env, led, window):
    import time

    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    led.team(done_ago=10, window=wid, socket=sock)
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    e = {"TMUX": f"{sock},0,0", "TMUX_PANE": pane, "STELLA_TEAM": "alpha"}
    assert "would close" in env.run("wrap", "--dry-run", env=e).stdout
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout
    assert "closes in" in env.run("wrap", "--delay", "0.5", env=e).stdout
    assert "wrapped_up" in _types(env)
    time.sleep(2)
    assert "alpha" not in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_wrap_outside_tmux_says_so(env):
    assert "not inside tmux" in env.run("wrap").stdout
