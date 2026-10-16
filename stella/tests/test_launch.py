"""Requirement 16: every launch is a tmux window running the lead; Stella can type to it."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from conftest import sock_dir

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="needs tmux")

FAKE_CLAUDE = """#!/bin/sh
echo "$@" > "{out}/args.txt"
echo "$STELLA_TEAM $STELLA_ORDER" > "{out}/env.txt"
cat > "{out}/typed.txt"
"""


@pytest.fixture
def tmux(env):
    sock = sock_dir("st") / "s"
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
    seq = max(e["seq"] for e in env.events() if e["type"] == "order")
    env.run("launch", "builder", "--order", str(seq), "--name", "bz", env=tmux)
    env.hook("session-end", {"session_id": "L", "reason": "other"}, env={"STELLA_TEAM": "bz"})
    assert "exited unexpectedly" in env.run("attention").stdout


def test_no_tmux_falls_back_to_background(env, fake_claude):
    env.say("A", "S, build w")
    r = env.run("launch", "builder", "--order", "1", "--name", "bw", "--dry-run")
    assert "STELLA_TEAM=bw" in r.stdout


def test_survives_a_server_restart(env, fake_claude):
    """16b: kill the server, start a new one, launch again; nothing to reconfigure."""
    for i in range(2):
        sock = sock_dir("st") / "s"
        subprocess.run(["tmux", "-S", str(sock), "new-session", "-d", "-s", "work"], check=True, env=env.env)
        env.say("A", f"S, build round {i}")
        r = env.run("launch", "builder", "--text", f"round {i}", "--name", f"r{i}", env={"TMUX": f"{sock},0,0"})
        assert "tmux window" in r.stdout
        subprocess.run(["tmux", "-S", str(sock), "kill-server"], env=env.env)


ENV_CLAUDE = """#!/bin/sh
echo "${{DEMO_TOKEN:-unset}} ${{DEMO_OTHER:-unset}}" > "{out}/passed.txt"
"""


def test_launch_forwards_only_pass_env_variables(env, tmux, fake_claude):
    p = env.tmp / "claude-env"
    p.write_text(ENV_CLAUDE.format(out=fake_claude))
    p.chmod(0o755)
    secrets = env.tmp / "secrets"
    secrets.mkdir()
    (secrets / "DEMO_TOKEN").write_text("t0ken")
    env.write_config(claude_bin=str(p), claude_query_bin="false", pass_env=["DEMO_TOKEN"], pass_env_dir=str(secrets))
    env.run("pass-env", "on")
    env.say("A", "S, build z")
    seq = max(e["seq"] for e in env.events() if e["type"] == "order")
    env.run("launch", "builder", "--order", str(seq), "--name", "bz",
            env={**tmux, "DEMO_TOKEN": "fromcaller", "DEMO_OTHER": "nope"})
    assert _wait(fake_claude / "passed.txt").split() == ["t0ken", "unset"]
    script = (env.store / "launch" / "bz.sh").read_text()
    assert "t0ken" not in script


def _windows(sock):
    return subprocess.run(["tmux", "-S", sock, "list-windows", "-t", "work", "-F", "#{window_name}"],
                          capture_output=True, text=True).stdout.split()


def _pane(sock, window, fmt):
    return subprocess.run(["tmux", "-S", sock, "list-panes", "-t", f"work:{window}", "-F", fmt],
                          capture_output=True, text=True).stdout.strip()


def _ended(env, team):
    return [e for e in env.events() if e["type"] == "ended" and e["team"] == team]


def _type(sock, window, line, done, timeout=15):
    """Type into the window's shell until `done` (a file the line writes) appears: the shell may still be starting."""
    end = time.time() + timeout
    while time.time() < end and not (done.exists() and done.read_text().strip()):
        subprocess.run(["tmux", "-S", sock, "send-keys", "-t", f"work:{window}", line, "Enter"], check=True)
        time.sleep(0.7)
    return _wait(done, 3)


def _wait_for(cond, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.1)
    return False


def test_quitting_the_lead_leaves_a_shell_in_the_same_window_and_directory(env, tmux, fake_claude):
    (env.home / ".zshrc").write_text("")  # so a login zsh does not offer its first-run wizard
    quits = env.tmp / "claude-quits-now"
    quits.write_text(f'#!/bin/sh\necho "$@" > "{fake_claude}/args.txt"\nexit 0\n')
    quits.chmod(0o755)
    env.write_config(claude_bin=str(quits), tmux_session="work")
    sock = tmux["TMUX"].split(",")[0]
    where = env.tmp / "work dir"
    where.mkdir()
    env.say("A", "S, build q1")
    env.run("launch", "builder", "--order", "1", "--name", "q1", "--dir", str(where), env=tmux)
    _wait(fake_claude / "args.txt")
    # the lead ended: the window stays, as a shell, in the lead's directory
    assert _wait_for(lambda: _pane(sock, "q1", "#{@stella_lead_exited}") == "1")
    time.sleep(0.5)
    assert "q1" in _windows(sock)
    assert os.path.realpath(_pane(sock, "q1", "#{pane_current_path}")) == os.path.realpath(where)
    assert os.path.realpath(_type(sock, "q1", f"pwd > '{env.tmp}/shell.txt'", env.tmp / "shell.txt").strip()) == os.path.realpath(where)
    # nothing may be typed into that shell on the lead's behalf
    assert "no open Stella window" in env.run("tell", "q1", "hello", env=tmux).stdout
    assert not (env.tmp / "hello").exists()
    # the lead's STELLA_TEAM is still in that shell's environment
    assert _type(sock, "q1", f"echo $STELLA_TEAM > '{env.tmp}/team.txt'", env.tmp / "team.txt").strip() == "q1"
    # and a finished team's window is still closed by reap
    env.run("done", "q1", "finished")
    assert "closed q1" in env.run("reap", "q1", env=tmux).stdout
    assert "q1" not in _windows(sock)


def test_a_typed_quit_is_one_deliberate_end_and_a_crash_is_one_unexpected_end(env, tmux):
    sock = tmux["TMUX"].split(",")[0]
    stella = Path(__file__).resolve().parents[1] / "bin" / "stella"
    # /quit: Claude's SessionEnd hook runs, then it exits 0
    quits = env.tmp / "claude-quits"
    quits.write_text(f"#!/bin/sh\necho '{{\"reason\":\"prompt_input_exit\"}}' | {stella} hook session-end\nexit 0\n")
    # killed after its hook ran (a signal): still one end, not two
    both = env.tmp / "claude-both"
    both.write_text(f"#!/bin/sh\necho '{{\"reason\":\"other\"}}' | {stella} hook session-end\nexit 137\n")
    # crashed, no hook at all
    crashes = env.tmp / "claude-crashes"
    crashes.write_text("#!/bin/sh\nexit 1\n")
    for p in (quits, both, crashes):
        p.chmod(0o755)
    for name, claude in (("quits", quits), ("both", both), ("crashes", crashes)):
        env.write_config(claude_bin=str(claude), tmux_session="work")
        env.say("A", f"S, build {name}")
        env.run("launch", "builder", "--order", "1", "--name", name, env=tmux)
    assert _wait_for(lambda: all(_ended(env, n) for n in ("quits", "both", "crashes")))
    time.sleep(1)
    assert [e["reason"] for e in _ended(env, "quits")] == ["prompt_input_exit"]
    assert [e["reason"] for e in _ended(env, "both")] == ["other"]
    assert [e["reason"] for e in _ended(env, "crashes")] == ["other"]
    # every one of them keeps its window, as a shell, and is not mistaken for a live lead
    assert {"quits", "both", "crashes"} <= set(_windows(sock))
    attention = env.run("attention").stdout
    assert "crashes exited unexpectedly" in attention and "quits exited unexpectedly" not in attention
    assert "was closed by hand" not in env.run("attention").stderr


def test_lead_prompt_tells_the_team_to_state_requests_in_full(env, tmux, fake_claude):
    env.say("A", "S, build q")
    env.run("launch", "builder", "--order", "1", "--name", "bq", env=tmux)
    prompt = (env.store / "launch" / "bq.prompt.md").read_text()
    assert "STATES THE REQUEST IN FULL" in prompt and 'Never write "I have asked"' in prompt


def test_needs_you_report_reminds_the_team_to_say_it_in_the_window(env):
    env.say("A", "S, build r")
    out = env.run("report", "br", "which database?", "--needs-you").stdout
    assert "must state the request in full" in out
    assert "must state" not in env.run("report", "br", "built half").stdout


def test_launch_script_runs_the_lead_then_the_owners_shell(env, tmux, fake_claude):
    env.say("A", "S, build w")
    env.run("launch", "builder", "--order", "1", "--name", "bw", env=tmux)
    script = (env.store / "launch" / "bw.sh").read_text()
    assert "exec " not in script.split("rc=$?")[0]  # the lead is a child, not the window's process
    assert script.rstrip().endswith('exec "${SHELL:-/bin/sh}" -l')
    assert "export STELLA_TEAM=bw" in script
    sock = tmux["TMUX"].split(",")[0]
    opt = subprocess.run(["tmux", "-S", sock, "show-options", "-w", "-t", "work:bw", "remain-on-exit"],
                         capture_output=True, text=True).stdout
    assert "off" in opt


def test_launch_uses_the_configured_permission_mode_for_every_team(env, tmux, fake_claude):
    env.write_config(permission_mode="auto")
    env.say("A", "S, build m")
    env.run("launch", "builder", "--order", "1", "--name", "bm", env=tmux)
    env.run("launch", "investigator", "--order", "1", "--name", "im", env=tmux)
    for n in ("bm", "im"):
        assert "--permission-mode auto" in (env.store / "launch" / f"{n}.sh").read_text()


def test_launch_refuses_the_home_directory_unless_asked_for_it(env, tmux, fake_claude):
    env.say("A", "S, build h")
    r = env.run("launch", "builder", "--order", "1", "--name", "bh", env=tmux, cwd=env.home, check=False)
    assert r.returncode != 0 and "--dir" in (r.stderr + r.stdout)
    ok = env.run("launch", "builder", "--order", "1", "--name", "bh2", "--dir", "~", env=tmux, cwd=env.home)
    assert "launched" in ok.stdout


def test_reap_closes_the_window_of_a_finished_team(env, tmux, fake_claude):
    sock = tmux["TMUX"].split(",")[0]
    env.say("A", "S, build t")
    env.run("launch", "builder", "--order", "1", "--name", "bt", env=tmux)
    _wait(fake_claude / "args.txt")
    env.run("done", "bt", "finished")
    r = env.run("reap", "bt", env=tmux)
    assert "closed bt" in r.stdout
    windows = subprocess.run(["tmux", "-S", sock, "list-windows", "-t", "work", "-F", "#{window_name}"],
                             capture_output=True, text=True).stdout.split()
    assert "bt" not in windows


def test_the_lead_is_told_to_push_and_auto_push_launches_say_so(env, tmux, fake_claude):
    env.say("A", "S, build a tool")
    env.run("launch", "builder", "--order", "1", "--name", "pp", env=tmux)
    assert "Push duty" in (env.store / "launch" / "pp.prompt.md").read_text()
    assert "AUTO_PUSH" not in (env.store / "launch" / "pp.sh").read_text()
    env.run("launch", "builder", "--order", "1", "--name", "pq", "--auto-push", env=tmux)
    assert "told you up front to push" in (env.store / "launch" / "pq.prompt.md").read_text()
    assert "export STELLA_AUTO_PUSH=1" in (env.store / "launch" / "pq.sh").read_text()


def test_reopen_resumes_a_session_by_name_in_its_own_directory_and_lists_it(env, tmux, fake_claude):
    import json

    sock = tmux["TMUX"].split(",")[0]
    where = env.tmp / "monorepo"
    where.mkdir()
    sid = "11111111-2222-4333-8444-555555555555"
    d = env.tmp / "transcripts" / "-proj"
    d.mkdir(parents=True)
    t = d / f"{sid}.jsonl"
    t.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in (
        {"type": "user", "entrypoint": "sdk-cli", "cwd": str(where), "sessionId": sid},
        {"type": "custom-title", "customTitle": "pr-9-sam", "sessionId": sid})))
    old = time.time() - 3600
    os.utime(t, (old, old))
    out = env.run("reopen", "pr-9-sam", env=tmux).stdout
    assert "reopened pr-9-sam" in out and "now listed" in out
    args = _wait(fake_claude / "args.txt")
    assert f"--resume {sid}" in args and "--name pr-9-sam" in args
    assert "pr-9-sam" in _windows(sock)
    assert os.path.realpath(_pane(sock, "pr-9-sam", "#{pane_current_path}")) == os.path.realpath(where)
    assert '"sdk-cli"' not in t.read_text()
    # not a team: no team name in the window's environment, so no team hooks fire for it
    assert "STELLA_TEAM" not in (env.store / "launch" / "pr-9-sam.reopen.sh").read_text()
    assert "already open" in env.run("reopen", "pr-9-sam", env=tmux).stdout


def test_a_lead_that_ends_never_runs_claude_itself(env, tmux, fake_claude):
    """The farewell line names `claude --resume` in backticks; in a shell double-quoted string that would RUN
    the real `claude` (under the test's HOME, which has no keychain: macOS then asks to store its token)."""
    (env.home / ".zshrc").write_text("")
    shim = env.tmp / "shim"
    shim.mkdir()
    (shim / "claude").write_text(f'#!/bin/sh\necho "$@" >> "{env.tmp}/real-claude-ran.txt"\n')
    (shim / "claude").chmod(0o755)
    quits = env.tmp / "claude-quits-now"
    quits.write_text(f'#!/bin/sh\necho "$@" > "{fake_claude}/args.txt"\nexit 0\n')
    quits.chmod(0o755)
    env.write_config(claude_bin=str(quits), tmux_session="work")
    sock = tmux["TMUX"].split(",")[0]
    env.say("A", "S, build q2")
    env.run("launch", "builder", "--order", "1", "--name", "q2", env={**tmux, "PATH": f"{shim}:{env.env['PATH']}"}, cwd=env.tmp)
    _wait(fake_claude / "args.txt")
    assert _wait_for(lambda: _pane(sock, "q2", "#{@stella_lead_exited}") == "1")
    time.sleep(0.5)
    assert not (env.tmp / "real-claude-ran.txt").exists()
