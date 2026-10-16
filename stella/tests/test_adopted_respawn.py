"""An adopted (hand-opened) session is restarted as plain `claude --resume <id> --name <n> --permission-mode <m>`:
it never had a launch prompt file, and claude exits on a file that is not there (ledger #1357). A window left as the
owner's shell after a failed start is resumed in place, by `pass-env --respawn` and by `stella reopen`."""

import time

import pytest
from test_launch import fake_claude, tmux  # noqa: F401 - fixtures
from test_passenv import _lines, env_claude, needs_tmux  # noqa: F401 - fixtures
from test_respawn_all import SIDS, Server, srv  # noqa: F401 - fixtures

pytestmark = needs_tmux

SID = SIDS["hand"]


def _adopt(env, monkeypatch, srv, name, window, sid=SID):
    """The ledger events `adopt.register` writes for a hand-opened session, and its transcript."""
    from stella import ledger

    monkeypatch.setenv("STELLA_STORE", str(env.store))
    ledger.append("launch", by="adopt", team=name, archetype="adopted", order=None, dir=str(env.tmp), window=window,
                  socket=srv.sock, via="adopted: started by hand")
    ledger.append("started", by="hook", team=name, session=sid)
    srv.transcript(sid)
    assert not (env.store / "launch" / f"{name}.prompt.md").exists()


def _resumed(out, n):
    return _lines(out / "args.txt", n)[-1]


def test_a_live_adopted_session_is_resumed_without_a_prompt_file(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    out, _ = env_claude
    env.write_config(permission_mode="plan")
    w, pid = srv.window("pr-pavan", "--name", "pr-pavan", "--resume", SID)
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    srv.agents([{"pid": pid, "cwd": str(env.tmp), "name": "pr-pavan", "sessionId": SID, "kind": "interactive"}])
    r = env.run("pass-env", "--respawn", "--team", "pr-pavan", env=tmux)
    assert "restarted" in r.stdout
    args = _resumed(out, 1)
    assert f"--resume {SID}" in args and "--name pr-pavan" in args and "--permission-mode plan" in args
    assert "prompt-file" not in args and "prompt.md" not in args


def test_a_window_left_as_a_shell_after_a_failed_start_is_resumed_in_place(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    out, _ = env_claude
    w = srv.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "work:", "-n", "pr-pavan", "exec sleep 60")  # the shell
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    r = env.run("pass-env", "--respawn", "--team", "pr-pavan", env=tmux)
    assert "pr-pavan" in r.stdout and "restarted" in r.stdout, r.stdout
    args = _resumed(out, 1)
    assert f"--resume {SID}" in args and "--name pr-pavan" in args and "prompt" not in args
    assert srv.names().count("pr-pavan") == 1  # reused, not a second window
    assert srv.tmux("list-windows", "-t", "work", "-F", "#{window_id} #{window_name}").count(w) == 1


def test_a_shell_with_a_job_running_in_it_is_not_taken_over(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    w = srv.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "work:", "-n", "pr-pavan", "sleep 60; true")
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    r = env.run("pass-env", "--respawn", "--team", "pr-pavan", env=tmux)
    assert "no open window" in r.stdout
    assert not (env.tmp / "fake" / "args.txt").exists()


def test_a_session_without_a_transcript_says_why_and_is_logged(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    w, pid = srv.window("pr-pavan", "--name", "pr-pavan", "--resume", SID)
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    (env.tmp / "transcripts" / "proj" / f"{SID}.jsonl").unlink()
    srv.agents([{"pid": pid, "cwd": str(env.tmp), "name": "pr-pavan", "sessionId": SID, "kind": "interactive"}])
    r = env.run("pass-env", "--respawn", "--team", "pr-pavan", env=tmux)
    assert "skipped, its conversation has no transcript" in r.stdout
    assert "pr-pavan" in (env.store / "runs" / "respawn.log").read_text()


def test_a_missing_prompt_file_is_never_named_for_a_launched_team(env, tmux, env_claude):  # noqa: F811
    from test_passenv import _launch

    out, _ = env_claude
    _launch(env, tmux, "t-lost")
    _lines(out / "args.txt", 1)
    (env.store / "launch" / "t-lost.prompt.md").unlink()
    env.hook("session-start", {"session_id": "sid-9", "source": "startup"}, env={"STELLA_TEAM": "t-lost"})
    (env.tmp / "transcripts" / "proj").mkdir(parents=True, exist_ok=True)
    (env.tmp / "transcripts" / "proj" / "sid-9.jsonl").write_text("{}\n")
    env.run("pass-env", "--respawn", "--team", "t-lost", env=tmux)
    args = _lines(out / "args.txt", 2)[1]
    assert "--resume sid-9" in args and "prompt-file" not in args


def test_reopen_reuses_a_window_whose_claude_has_exited(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    out, _ = env_claude
    w = srv.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "work:", "-n", "pr-pavan", "exec sleep 60")
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    before = srv.names()
    r = env.run("reopen", "pr-pavan", env=tmux)
    assert "reopened pr-pavan" in r.stdout and "reused" in r.stdout, r.stdout + r.stderr
    assert f"--resume {SID}" in _resumed(out, 1) and "prompt-file" not in _resumed(out, 1)
    assert srv.names() == before


def test_reopen_still_refuses_a_window_with_claude_running(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    w, _ = srv.window("pr-pavan", "--name", "pr-pavan", "--resume", SID)
    time.sleep(1)  # let the pane's shell exec the stand-in claude
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    r = env.run("reopen", "pr-pavan", env=tmux)
    assert "already open with its claude running" in r.stdout


# ---- the permission mode on restart is the current setting (ledger #1364)

def test_restart_applies_the_current_permission_mode_not_the_old_processes(env, tmux, srv, env_claude, monkeypatch):  # noqa: F811
    out, _ = env_claude
    env.write_config(permission_mode="bypassPermissions")
    w, pid = srv.window("pr-pavan", "--name", "pr-pavan", "--resume", SID, "--permission-mode", "auto")
    _adopt(env, monkeypatch, srv, "pr-pavan", w)
    srv.agents([{"pid": pid, "cwd": str(env.tmp), "name": "pr-pavan", "sessionId": SID, "kind": "interactive"}])
    r = env.run("pass-env", "--respawn", "--team", "pr-pavan", env=tmux)
    assert "[mode auto -> bypass]" in r.stdout, r.stdout
    args = _resumed(out, 1)
    assert "--permission-mode bypassPermissions" in args and "--permission-mode auto" not in args


def test_a_launched_team_follows_the_setting_unless_its_mode_was_named_at_launch(env, tmux, env_claude):  # noqa: F811
    from test_passenv import _launch

    out, _ = env_claude
    env.write_config(permission_mode="auto")
    _launch(env, tmux, "t-plain")
    env.say("A", "S, build t-named")
    seq = max(e["seq"] for e in env.events() if e["type"] == "order")
    env.run("launch", "builder", "--order", str(seq), "--name", "t-named", "--mode", "plan", env=tmux)
    _lines(out / "args.txt", 2)
    for n, sid in (("t-plain", "sid-p"), ("t-named", "sid-n")):
        env.hook("session-start", {"session_id": sid, "source": "startup"}, env={"STELLA_TEAM": n})
        (env.tmp / "transcripts" / "proj").mkdir(parents=True, exist_ok=True)
        (env.tmp / "transcripts" / "proj" / f"{sid}.jsonl").write_text("{}\n")
    env.write_config(permission_mode="bypassPermissions")
    env.run("pass-env", "--respawn", "--team", "t-plain", "--team", "t-named", env=tmux)
    resumed = {ln.split("--resume ")[1].split()[0]: ln for ln in _lines(out / "args.txt", 4) if "--resume" in ln}
    assert "--permission-mode bypassPermissions" in resumed["sid-p"]
    assert "--permission-mode plan" in resumed["sid-n"]
