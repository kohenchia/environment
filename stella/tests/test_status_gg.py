"""The status line every turn ends with (Stop hook), and `gg` (UserPromptSubmit hook) with `wrapup <team>`.
Windows are throwaway tmux servers on temp sockets, never the owner's."""

import json
import subprocess
import time

import pytest
from test_gate import _commit
from test_wrapup import _repo, _types, led  # noqa: F401 - fixtures
from test_wrapup import window as _bw  # noqa: F401


@pytest.fixture
def window(_bw):
    """Windows whose command is a script named claude-*, so the process tree holds a "Claude" as in real life."""
    return lambda script, name="alpha": _bw(script, name, True)


SESS = "sess-alpha"
TEAM = {"STELLA_TEAM": "alpha"}


def _stop(env, text, cwd, active=False, extra=None, sid=SESS):
    r = env.run("hook", "stop", input=json.dumps({"session_id": sid, "cwd": str(cwd), "stop_hook_active": active,
                                                  "last_assistant_message": text}), env=TEAM if extra is None else extra)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _transcript(env, text):
    p = env.tmp / "t.jsonl"
    p.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "go"}}) + "\n"
                 + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n")
    return p


# ---------------------------------------------------------------- the status line


def test_a_missing_line_is_blocked_once_with_the_exact_line(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    out = _stop(env, "I built it. Everything is in main.", r)
    assert out["decision"] == "block" and "ALL DONE: ready to wrap up. Type gg." in out["reason"]
    assert _stop(env, "I built it.", r, active=True) == {}  # at most one block per turn: no loop


def test_the_transcripts_last_assistant_text_is_what_is_read(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    data = {"session_id": SESS, "cwd": str(r), "transcript_path": str(_transcript(env, "Done.\nALL DONE: ready to wrap up. Type gg."))}
    assert env.run("hook", "stop", input=json.dumps(data), env=TEAM).stdout.strip() == ""
    data["transcript_path"] = str(_transcript(env, "Done, nothing else."))
    assert json.loads(env.run("hook", "stop", input=json.dumps(data), env=TEAM).stdout)["decision"] == "block"


@pytest.mark.parametrize("line", ["ALL DONE: ready to wrap up. Type gg.", "NEXT FOR YOU: pick a name", "WORKING: the eval run",
                                  "**ALL DONE: ready to wrap up. Type gg.**"])
def test_each_line_passes_when_the_facts_allow_it(env, led, line):
    r = _repo(env)
    led.team(dir=str(r))
    assert _stop(env, f"Summary.\n\n{line}\n", r) == {}


def test_all_done_with_uncommitted_changes_is_blocked(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "wip.txt").write_text("x\n")
    out = _stop(env, "Done.\nALL DONE: ready to wrap up. Type gg.", r)
    assert "uncommitted in proj: wip.txt" in out["reason"] and "NEXT FOR YOU: commit or discard the changes in proj" in out["reason"]
    assert _stop(env, "Done.\nNEXT FOR YOU: commit wip.txt", r) == {}


def test_all_done_with_an_open_question_is_blocked(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.add("report", ago=1, team="alpha", text="which database?", needs_you=True)
    out = _stop(env, "ALL DONE: ready to wrap up. Type gg.", r)
    assert "an open question: which database?" in out["reason"]


def test_unpushed_commits_get_the_push_block_with_the_rule_then_next_for_you(env, led, repo):
    led.team(dir=str(repo))
    _commit(env, repo)
    first = _stop(env, "Committed.", repo)
    assert "git -C" in first["reason"] and "LAST line" in first["reason"]  # one block carries both
    assert _stop(env, "Committed.", repo, active=True) == {}
    again = _stop(env, "All set.\nALL DONE: ready to wrap up. Type gg.", repo)  # next turn: the push was not made
    assert again["decision"] == "block" and "1 unpushed commit in dotfiles" in again["reason"]
    assert "NEXT FOR YOU: approve the push of dotfiles main (1 commit)" in again["reason"]


def test_a_deferred_push_is_next_for_you_until_it_is_dropped(env, led, repo):
    led.team(dir=str(repo))
    _commit(env, repo)
    pre = {"tool_name": "Bash", "tool_input": {"command": "git push -u origin main"}, "cwd": str(repo), "session_id": SESS}
    _stop(env, "x", repo)
    env.hook("pretool", pre, env=TEAM)  # the prompt appeared; the owner said no
    _stop(env, "NEXT FOR YOU: x", repo)  # recorded as deferred
    for bad in ("ALL DONE: ready to wrap up. Type gg.", "WORKING: nothing"):
        out = _stop(env, bad, repo)
        assert out["decision"] == "block" and "push of dotfiles main" in out["reason"] and "was deferred" in out["reason"]
    assert _stop(env, "NEXT FOR YOU: push of dotfiles is deferred; push it or drop it", repo) == {}
    key = json.loads(env.run("attention", "--json").stdout)[0]["key"]
    env.run("ack", key)  # dropped
    assert _stop(env, "ALL DONE: ready to wrap up. Type gg.", repo) == {}


def test_stellas_session_lists_attention_items_and_has_no_gg(env, led):
    own = {"STELLA_SELF": "1"}
    out = _stop(env, "Hello.", "/tmp", extra=own, sid="stella-s")
    assert "ALL DONE: nothing needs you." in out["reason"] and "Type gg" not in out["reason"]
    assert _stop(env, "Quiet.\nALL DONE: nothing needs you.", "/tmp", extra=own, sid="stella-s") == {}
    led.add("alert", key="k1", text="the nightly sweep failed")
    out = _stop(env, "All fine.\nALL DONE: nothing needs you.", "/tmp", extra=own, sid="stella-s")
    assert "NEXT FOR YOU: the nightly sweep failed" in out["reason"]


def test_a_session_outside_tmux_and_not_a_team_is_not_held_to_it(env):
    assert _stop(env, "no status line at all", "/tmp", extra={}, sid="free") == {}


def test_the_rule_is_in_the_per_turn_context_the_lead_prompt_and_the_skills(env, led):
    from stella import launch
    from pathlib import Path

    r = _repo(env)
    led.team(dir=str(r))
    env.say(SESS, "hello", env=TEAM)  # first prompt (seen_first)
    ctx = env.hook("prompt", {"prompt": "next", "session_id": SESS, "cwd": str(r)}, env=TEAM)["additionalContext"]
    assert "NEXT FOR YOU" in ctx and "ALL DONE: ready to wrap up. Type gg." in ctx
    assert "ALL DONE: ready to wrap up. Type gg." in launch.lead_prompt("t", "adhoc", 1, "do it")
    assert "ALL DONE: ready to wrap up. Type gg." in env.run("context", "--team").stdout
    root = Path(__file__).resolve().parents[1] / "plugin"
    for f in ("skills/build/SKILL.md", "skills/investigate/SKILL.md", "skills/stella/SKILL.md", "agents/stella.md"):
        assert "NEXT FOR YOU" in (root / f).read_text(), f


# ---------------------------------------------------------------- gg


def _pane_claude(sock, pane):
    """The pid of the fake Claude in a real pane, or None for a pane that does not exist (a hook's view of the world)."""
    from stella import windows

    r = subprocess.run(["tmux", "-S", sock, "display-message", "-p", "-t", pane, "#{pane_pid}"], capture_output=True, text=True)
    if not r.stdout.strip().isdigit():
        return None
    procs = windows._procs()
    return next((p for p in windows._descendants(int(r.stdout), procs) if windows._is_claude(procs[p][1])), None)


def _gg_env(env, sock, pane, **extra):
    """What a hook sees: no tmux answer is needed. It knows its Claude ancestor (STELLA_CLAUDE_PID stands in for the process tree)."""
    pid = _pane_claude(sock, pane)
    sessions = env.tmp / "claude-sessions"
    sessions.mkdir(exist_ok=True)
    return {"TMUX": f"{sock},0,0", "TMUX_PANE": pane, "STELLA_GG_DELAY": "0.2", "STELLA_CLAUDE_SESSIONS": str(sessions),
            **({"STELLA_CLAUDE_PID": str(pid)} if pid else {}), **extra}


def _gg(env, e, text="gg", cwd="/tmp", sid=SESS):
    r = env.run("hook", "prompt", input=json.dumps({"prompt": text, "session_id": sid, "cwd": str(cwd)}), env=e)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _wait_gone(tm, name="alpha", secs=5):
    end = time.time() + secs
    while time.time() < end:
        if name not in tm("list-windows", "-a", "-F", "#{window_name}").stdout:
            return True
        time.sleep(0.1)
    return False


def _claude_pid(tm, pane):
    """The pid of the fake Claude (a script named claude-*) running in the pane, as the scheduler would see it."""
    from stella import windows

    procs = windows._procs()
    root = int(tm("display-message", "-p", "-t", pane, "#{pane_pid}").stdout.strip())
    return next(p for p in windows._descendants(root, procs) if windows._is_claude(procs[p][1]))


def _setup(env, led, window, archetype="builder", status="done", **kw):
    r = _repo(env)
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    led.team(dir=str(r), window=wid, socket=sock, archetype=archetype, done_ago=10 if status == "done" else None, **kw)
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    return r, wid, sock, tm, pane


def test_gg_closes_a_clean_team_and_its_window_and_orders(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), " GG\n", cwd=r)
    assert out["decision"] == "block" and out["reason"] == "Wrapped up."  # the prompt never goes to the model
    assert _wait_gone(tm)
    assert "wrapped_up" in _types(env) and "reaped" in _types(env)
    assert [e for e in env.events() if e["type"] == "wrapped_up"][0]["by"] == "owner"
    assert "alpha" not in env.run("attention").stdout


@pytest.mark.parametrize("text", ["gg please", "g g", "ggg", "/gg", "no gg"])
def test_only_exactly_gg_is_gg(env, led, window, text):
    r, wid, sock, tm, pane = _setup(env, led, window)
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), text, cwd=r)
    assert "decision" not in out
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_gg_closes_a_keep_open_team(env, led, window):
    env.extension(teams='[team.reviewer]\nsummary = "s"\nwhen = "w"\nkeep_open = true\n')
    r, wid, sock, tm, pane = _setup(env, led, window, archetype="reviewer", status="running")
    _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    assert _wait_gone(tm) and "wrapped_up" in _types(env)
    assert [e for e in env.events() if e["type"] == "close"][0]["order"] == 1  # its open order is closed


def test_gg_does_not_close_with_uncommitted_changes(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    (r / "wip.txt").write_text("x\n")
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    assert out["decision"] == "block" and out["reason"].startswith("gg: not closing, uncommitted in proj: wip.txt")
    assert "\n" not in out["reason"]
    time.sleep(0.7)
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout and "wrapped_up" not in _types(env)


def test_gg_does_not_close_while_the_team_asks_the_owner(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    led.add("report", ago=1, team="alpha", text="which database?", needs_you=True)
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    assert "open question: which database?" in out["reason"]
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_gg_with_an_unpushed_commit_raises_the_push_prompt_instead_of_a_command(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    _commit(env, r)
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    ctx = out["hookSpecificOutput"]["additionalContext"]  # the model runs the push, so Claude Code asks
    assert "typed `gg`" in ctx and "1 unpushed commit in proj" in ctx and "push -u origin main" in ctx and "tell" in ctx
    time.sleep(0.7)
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout
    # once the push is done, gg closes it
    env.git(r, "push", "-q", "origin", "main")
    _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    assert _wait_gone(tm)


def test_gg_with_a_deferred_push_does_not_ask_again(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    _commit(env, r)
    led.add("push_deferred", ago=1, team="alpha", repo="proj", path=str(r), sha=env.git(r, "rev-parse", "HEAD").stdout.strip(),
            branch="main", session=SESS)
    led.add("alert", ago=1, key=f"push-deferred:proj@{env.git(r, 'rev-parse', 'HEAD').stdout.strip()}", text="deferred push: proj")
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), cwd=r)
    assert out["decision"] == "block" and "push of proj main" in out["reason"] and "deferred" in out["reason"]


def test_gg_in_a_hand_opened_session_closes_just_that_window(env, window):
    r = _repo(env)
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    (env.store / "stella-session.json").write_text(json.dumps({"socket": sock}))  # the server Stella works in
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    out = _gg(env, _gg_env(env, sock, pane), cwd=r, sid="hand")
    assert out["decision"] == "block" and out["reason"] == "Wrapped up."
    assert _wait_gone(tm)
    assert "wrapped_up" not in _types(env)


def test_gg_in_a_hand_opened_session_checks_too(env, window):
    r = _repo(env)
    (r / "wip.txt").write_text("x\n")
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    (env.store / "stella-session.json").write_text(json.dumps({"socket": sock}))
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    assert "uncommitted" in _gg(env, _gg_env(env, sock, pane), cwd=r, sid="hand")["reason"]
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout


def test_gg_is_refused_in_stellas_own_session(env, window):
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    out = _gg(env, _gg_env(env, sock, pane, STELLA_SELF="1"))
    assert out == {"decision": "block", "reason": "gg: Stella's own session is never wrapped up."}
    time.sleep(0.7)
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout
    assert env.events() == []  # not an order either


def test_gg_outside_a_stella_tmux_server_closes_nothing(env):
    assert _gg(env, {})["reason"].startswith("gg: nothing closed:")


def test_wrapup_by_team_name_is_the_same_checks_and_closing(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    (r / "wip.txt").write_text("x\n")
    e = {"TMUX": f"{sock},0,0"}
    assert "not closing, uncommitted in proj" in env.run("wrapup", "alpha", env=e).stdout
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout
    (r / "wip.txt").unlink()
    assert "wrapped up alpha" in env.run("wrapup", "alpha", env=e).stdout
    assert "alpha" not in tm("list-windows", "-a", "-F", "#{window_name}").stdout  # verified gone, synchronously
    assert "wrapped_up" in _types(env)


def test_wrap_and_wrapup_are_documented_with_gg(env):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for f in ("README.md", "plugin/skills/wrap-up/SKILL.md"):
        assert "`gg`" in (root / f).read_text(), f
    assert "gg:" in env.run("--help").stdout and "NEXT FOR YOU" in env.run("--help").stdout


def test_gg_needs_neither_tmux_nor_the_scheduler(env, led, window):
    """The hook's sandbox denies the tmux socket: here the socket is not even there. The window closes anyway, at once, silently."""
    r, wid, sock, tm, pane = _setup(env, led, window)
    e = _gg_env(env, sock, pane, **TEAM)
    deny = env.tmp / "deny"  # a tmux that is refused, as in the hook's sandbox
    deny.mkdir()
    (deny / "tmux").write_text("#!/bin/sh\necho 'error connecting (Operation not permitted)' >&2\nexit 1\n")
    (deny / "tmux").chmod(0o755)
    e["PATH"] = f"{deny}:{env.env['PATH']}"
    out = _gg(env, e, cwd=r)
    assert out["reason"] == "Wrapped up."  # one calm line; no scheduler, pane or "blocked" in it
    assert _wait_gone(tm) and "wrapped_up" in _types(env)
    assert not (env.store / "gg").exists()  # no queue


def test_gg_closes_a_window_whose_claude_runs_under_a_shell(env, led, window):
    """The launch script keeps a shell above Claude; the shell is the pane process, Claude is its child."""
    r = _repo(env)
    wid, sock, tm = window("#!/bin/sh\n(exec -a x sh -c 'exec /bin/sleep 600') &\nsleep 600\n")
    led.team(dir=str(r), window=wid, socket=sock, done_ago=10)
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    shell = int(tm("display-message", "-p", "-t", pane, "#{pane_pid}").stdout)
    kid = env.tmp / "claude-kid.sh"
    kid.write_text("#!/bin/sh\nsleep 600\n")
    kid.chmod(0o755)
    tm("respawn-pane", "-k", "-t", pane, f"/bin/sh -c '{kid}; exec sleep 600'")
    time.sleep(0.6)
    e = _gg_env(env, sock, pane, **TEAM)
    assert e.get("STELLA_CLAUDE_PID") and int(e["STELLA_CLAUDE_PID"]) != int(tm("display-message", "-p", "-t", pane, "#{pane_pid}").stdout)
    assert _gg(env, e, cwd=r)["reason"] == "Wrapped up."
    assert _wait_gone(tm) and "wrapped_up" in _types(env)


def test_gg_reports_one_clear_line_when_it_cannot_find_its_window(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    e = _gg_env(env, sock, pane, **TEAM)
    e["STELLA_CLAUDE_PID"] = "1"  # launchd: not under any tmux pane
    out = _gg(env, e, cwd=r)
    assert out["reason"].startswith("gg: nothing closed:") and "\n" not in out["reason"]
    time.sleep(0.5)
    assert "alpha" in _names(tm) and "wrapped_up" not in _types(env)


# ---------------------------------------------------------------- gg closes only the session it was typed in


def _names(tm):
    return set(tm("list-windows", "-a", "-F", "#{window_name}").stdout.split())


def _three(env, led, window):
    """Three clean finished teams in three windows of one server, the sweep able to close any of them."""
    env.write_config(wrapup_auto=True)
    wins = {}
    for name in ("alpha", "beta", "gamma"):
        r = _repo(env, name)
        wid, sock, tm = window("#!/bin/sh\nsleep 600\n", name)
        led.team(name=name, dir=str(r), window=wid, socket=sock, done_ago=10)
        wins[name] = (r, wid, tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0])
    return sock, tm, wins


def test_gg_in_one_of_three_windows_closes_only_that_one_and_records_only_that_team(env, led, window):
    sock, tm, wins = _three(env, led, window)
    r, wid, pane = wins["beta"]
    out = _gg(env, _gg_env(env, sock, pane, STELLA_TEAM="beta"), cwd=r, sid="sess-beta")
    assert out["reason"] == "Wrapped up."
    assert _wait_gone(tm, "beta")
    time.sleep(1)
    assert {"alpha", "gamma"} <= _names(tm)  # the others, though the sweep could close them, stay
    assert [e["team"] for e in env.events() if e["type"] in {"wrapped_up", "reaped"}] == ["beta", "beta"]


def test_gg_never_runs_or_triggers_the_sweep():
    import inspect

    from stella import adopt, hooks, wrapup

    for fn in (wrapup.wrap_session, wrapup.wrap_team, wrapup.process_requests, wrapup.finish_wrap,
               hooks._gg, adopt.process_requests):
        src = inspect.getsource(fn)
        assert "sweep(" not in src and "evaluate(" not in src, fn.__name__


def test_bare_wrapup_is_not_the_sweep(env):
    r = env.run("wrapup", check=False)
    assert r.returncode != 0 and "stella sweep" in (r.stderr + r.stdout)
    assert "ONE named team" in env.run("wrapup", "--help").stdout and "EVERY finished team" in env.run("sweep", "--help").stdout


def test_gg_signals_only_its_own_windows_processes(env, led, window):
    """A hook's identity is its process tree, not an environment variable: a stale TMUX_PANE of another window changes nothing."""
    sock, tm, wins = _three(env, led, window)
    r, wid, pane = wins["beta"]
    e = _gg_env(env, sock, pane, STELLA_TEAM="beta")
    e["TMUX_PANE"] = wins["alpha"][2]
    _gg(env, e, cwd=r, sid="sess-beta")
    assert _wait_gone(tm, "beta")
    time.sleep(0.7)
    assert {"alpha", "gamma"} <= _names(tm)


def test_gg_refuses_when_the_session_file_names_another_session(env, led, window):
    sock, tm, wins = _three(env, led, window)
    r, wid, pane = wins["beta"]
    e = _gg_env(env, sock, pane, STELLA_TEAM="beta")
    (env.tmp / "claude-sessions" / "1.json").write_text(json.dumps({"pid": int(e["STELLA_CLAUDE_PID"]), "sessionId": "someone-else"}))
    out = _gg(env, e, cwd=r, sid="sess-beta")
    assert "not this session" in out["reason"]
    time.sleep(0.5)
    assert {"alpha", "beta", "gamma"} <= _names(tm) and "wrapped_up" not in _types(env)


def test_a_window_that_also_holds_another_claude_is_not_closed(env, led, window):
    sock, tm, wins = _three(env, led, window)
    r, wid, pane = wins["beta"]
    p = env.tmp / "claude-second.sh"
    p.write_text("#!/bin/sh\nsleep 600\n")
    p.chmod(0o755)
    tm("split-window", "-d", "-t", wid, str(p))
    time.sleep(0.5)
    e = _gg_env(env, sock, pane, STELLA_TEAM="beta")
    other = _pane_claude(sock, tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[-1])
    assert other and other != int(e["STELLA_CLAUDE_PID"])
    # a second pane is another pane process: only the pane that typed gg is closed, and the window stays with the other
    _gg(env, e, cwd=r, sid="sess-beta")
    time.sleep(1.2)
    assert tm("list-panes", "-t", wid).stdout.count("\n") == 1 or "beta" in _names(tm)


def _process(env, sock):
    env.run("wrapup", "--process-requests", env={"TMUX": f"{sock},0,0"})


def test_the_sweeps_notice_names_the_window_it_closed(env, led, window, monkeypatch):
    from stella import state, wrapup

    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_CONFIG", str(env.config))
    sock, tm, wins = _three(env, led, window)
    st = state.fold()
    assert wrapup._named(st, wrapup.Verdict("beta", "done", True)) == f"beta (window {wins['beta'][1]})"
    assert wrapup._named(st, wrapup.Verdict("beta", "gone", True, gone=True)) == "beta (no window left to close)"


# ---------------------------------------------------------------- adopting hand-started sessions


def _hand(env, window, name="review"):
    r = _repo(env, "wt")
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n", name)
    (env.store / "stella-session.json").write_text(json.dumps({"socket": sock}))
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    return r, wid, sock, tm, pane


def test_a_hand_started_session_is_adopted_under_its_window_name_on_its_first_prompt(env, window):
    r, wid, sock, tm, pane = _hand(env, window)
    e = _gg_env(env, sock, pane)
    assert "decision" not in _gg(env, e, "hello", cwd=r, sid="hand-1")
    ev = [x for x in env.events() if x["type"] == "launch"][0]
    assert ev["team"] == "review" and ev["archetype"] == "adopted" and ev["window"] == wid and ev["socket"] == sock
    n = len(env.events())
    _gg(env, e, "again", cwd=r, sid="hand-1")
    assert len(env.events()) == n  # asked once per session


def test_an_adopted_session_is_never_closed_by_the_sweep_but_wrapup_and_gg_close_it(env, led, window):
    env.write_config(wrapup_auto=True)
    r, wid, sock, tm, pane = _hand(env, window)
    e = _gg_env(env, sock, pane)
    _gg(env, e, "hello", cwd=r, sid="hand-1")
    led.seq = max(x["seq"] for x in env.events())
    led.add("done", team="review", text="reviewed")
    out = env.run("sweep", env={"TMUX": f"{sock},0,0"}).stdout
    assert "kept open review" in out and "adopted" in out
    assert "review" in _names(tm) and "wrapped_up" not in _types(env)
    assert "wrapped up review" in env.run("wrapup", "review", env={"TMUX": f"{sock},0,0"}).stdout
    assert "review" not in _names(tm)


def test_gg_closes_an_adopted_session_and_records_it(env, window):
    r, wid, sock, tm, pane = _hand(env, window)
    e = _gg_env(env, sock, pane)
    _gg(env, e, "hello", cwd=r, sid="hand-1")
    out = _gg(env, e, "gg", cwd=r, sid="hand-1")
    assert out["reason"] == "Wrapped up." and _wait_gone(tm, "review")
    assert [x["team"] for x in env.events() if x["type"] == "wrapped_up"] == ["review"]


def test_an_adoption_queued_by_a_sandboxed_hook_is_registered_by_the_scheduler_after_the_check(env, window):
    r, wid, sock, tm, pane = _hand(env, window)
    _gg(env, _gg_env(env, sock, "%999"), "hello", cwd=r, sid="hand-1")
    assert "launch" not in _types(env)
    [req] = list((env.store / "adopt").glob("*.json"))
    req.write_text(json.dumps({**json.loads(req.read_text()), "pane": pane, "claude_pid": _claude_pid(tm, pane)}))
    _process(env, sock)
    assert [x["team"] for x in env.events() if x["type"] == "launch"] == ["review"]
    # a request whose pane does not hold that session adopts nothing
    _gg(env, _gg_env(env, sock, "%999"), "hello", cwd=r, sid="hand-2")
    [req] = list((env.store / "adopt").glob("*.json"))
    req.write_text(json.dumps({**json.loads(req.read_text()), "pane": pane, "claude_pid": 1}))
    _process(env, sock)
    assert len([x for x in env.events() if x["type"] == "launch"]) == 1


# ---------------------------------------------------------------- tyfp: every session that is done


def _fleet(env, led, window):
    """Windows: ok1, ok2 (clean, idle), busy (a screen that is working), blocked (uncommitted), keep (a keep_open archetype),
    pushy (an unpushed commit), and the session the word is typed in (typer, clean)."""
    env.extension(teams='[team.reviewer]\nsummary = "s"\nwhen = "w"\nkeep_open = true\n')
    from test_wrapup import BUSY, PROMPT

    w = {}
    for name, script, arch in (("ok1", PROMPT, "builder"), ("ok2", PROMPT, "builder"), ("busy", BUSY, "builder"),
                               ("blocked", PROMPT, "builder"), ("keep", PROMPT, "reviewer"), ("pushy", PROMPT, "builder"),
                               ("typer", "#!/bin/sh\nsleep 600\n", "builder")):
        r = _repo(env, name)
        wid, sock, tm = window(script, name)
        led.team(name=name, archetype=arch, dir=str(r), window=wid, socket=sock, done_ago=10)
        pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
        w[name] = (r, wid, pane)
    (w["blocked"][0] / "wip.txt").write_text("x\n")
    _commit(env, w["pushy"][0])
    (env.store / "stella-session.json").write_text(json.dumps({"socket": sock}))
    return sock, tm, w


def test_tyfp_closes_exactly_the_clean_idle_ones_and_reports_once(env, led, window):
    sock, tm, w = _fleet(env, led, window)
    r, wid, pane = w["typer"]
    out = _gg(env, _gg_env(env, sock, pane, STELLA_TEAM="typer", STELLA_CLAUDE_PID=str(_claude_pid(tm, pane))), " TYFP ", cwd=r, sid="sess-typer")
    assert out["hookSpecificOutput"]["additionalContext"]  # the unpushed one raises the push prompt through the session
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "wrapped up: " in ctx and "ok1" in ctx and "ok2" in ctx and "keep" in ctx and "typer" in ctx
    assert "left open: busy: its session is busy" in ctx
    assert "left open: blocked: uncommitted in blocked: wip.txt" in ctx
    assert "left open: pushy: 1 unpushed commit in pushy" in ctx
    assert f"git -C {w['pushy'][0]} push -u origin main" in ctx and f"git -C {w['blocked'][0]} push" not in ctx
    time.sleep(2.5)
    left = _names(tm) - {"zsh", "sh", "bash"}
    assert {"busy", "blocked", "pushy"} <= left and not ({"ok1", "ok2", "keep", "typer"} & left)
    assert sorted(e["team"] for e in env.events() if e["type"] == "wrapped_up") == ["keep", "ok1", "ok2", "typer"]


def test_tyfp_with_only_a_report_to_give_never_reaches_the_model(env, led, window):
    sock, tm, w = _fleet(env, led, window)
    for name in ("pushy", "blocked", "busy"):
        tm("kill-window", "-t", w[name][1])
        led.add("reaped", team=name)
    r, wid, pane = w["typer"]
    out = _gg(env, _gg_env(env, sock, pane, STELLA_TEAM="typer", STELLA_CLAUDE_PID=str(_claude_pid(tm, pane))), "tyfp", cwd=r, sid="sess-typer")
    assert out["decision"] == "block" and out["reason"].startswith("wrapped up: ")


def test_tyfp_leaves_the_typed_in_session_when_it_is_blocked_and_never_closes_stella(env, led, window):
    sock, tm, w = _fleet(env, led, window)
    r, wid, pane = w["typer"]
    (r / "wip.txt").write_text("x\n")
    out = _gg(env, _gg_env(env, sock, pane, STELLA_TEAM="typer"), "tyfp", cwd=r, sid="sess-typer")
    assert "left open: typer: uncommitted in typer" in out["hookSpecificOutput"]["additionalContext"]
    time.sleep(1.5)
    assert "typer" in _names(tm)
    own = _gg(env, _gg_env(env, sock, w["ok1"][2], STELLA_SELF="1"), "tyfp", cwd=r, sid="stella-s")
    assert "typer" in _names(tm) and "ok1" not in _names(tm)  # her session ran it; she was never a candidate


def test_tyfp_from_a_sandboxed_hook_goes_through_the_scheduler(env, led, window, monkeypatch):
    import threading

    sock, tm, w = _fleet(env, led, window)
    r, wid, pane = w["typer"]
    for name in ("pushy", "blocked", "busy", "keep", "ok2"):
        tm("kill-window", "-t", w[name][1])
        led.add("reaped", team=name)
    monkeypatch.setattr("stella.tyfp.WAIT", 20)

    def scheduler():  # waits for the hook's request, fixes the pane identity it could not know, then processes it
        end = time.time() + 15
        while time.time() < end:
            reqs = list((env.store / "tyfp").glob("*.json"))
            if reqs:
                f = reqs[0]
                f.write_text(json.dumps({**json.loads(f.read_text()), "pane": pane, "claude_pid": _claude_pid(tm, pane)}))
                env.run("wrapup", "--process-requests", env={"TMUX": f"{sock},0,0"})
                return
            time.sleep(0.2)

    th = threading.Thread(target=scheduler)
    th.start()
    out = _gg(env, _gg_env(env, sock, "%999", STELLA_TEAM="typer"), "tyfp", cwd=r, sid="sess-typer")
    th.join()
    assert out["decision"] == "block" and "ok1" in out["reason"] and "typer" in out["reason"]
    assert _wait_gone(tm, "ok1")


def test_tyfp_from_a_sandboxed_hook_closes_other_windows_directly_by_their_session_files(env, led, window):
    """No tmux and no scheduler: each session is found from the file Claude wrote (pid, session id, window, idle or busy)."""
    sock, tm, w = _fleet(env, led, window)
    r, wid, pane = w["typer"]
    e = _gg_env(env, sock, pane, STELLA_TEAM="typer")
    deny = env.tmp / "deny"
    deny.mkdir()
    (deny / "tmux").write_text("#!/bin/sh\nexit 1\n")
    (deny / "tmux").chmod(0o755)
    e["PATH"] = f"{deny}:{env.env['PATH']}"
    for name, (_, wid_, pane_) in w.items():
        (env.tmp / "claude-sessions" / f"{name}.json").write_text(json.dumps(
            {"pid": _pane_claude(sock, pane_), "sessionId": f"sess-{name}", "name": name, "tmux": f"work:{wid_}.{pane_}",
             "status": "busy" if name == "busy" else "idle"}))
    out = _gg(env, e, "tyfp", cwd=r, sid="sess-typer")
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "ok1" in ctx and "ok2" in ctx and "left open: busy: its session is busy" in ctx
    time.sleep(2)
    left = _names(tm) - {"zsh", "sh", "bash"}
    assert {"busy", "blocked", "pushy"} <= left and not ({"ok1", "ok2", "keep", "typer"} & left)
    assert not (env.store / "tyfp").exists()  # no queue


def test_sweep_now_is_the_same_thing_from_the_command_line(env, led, window):
    sock, tm, w = _fleet(env, led, window)
    out = env.run("sweep", "--now", "--dry-run", env={"TMUX": f"{sock},0,0"}).stdout
    assert "ok1" in out.splitlines()[0] and "left open: busy" in out and "left open: pushy" in out
    assert "ok1" in _names(tm)  # a dry run
    env.run("sweep", "--now", env={"TMUX": f"{sock},0,0"})
    assert "ok1" not in _names(tm) and "busy" in _names(tm)


def test_a_window_id_that_now_belongs_to_another_window_is_never_killed(env, led, window):
    sock, tm, w = _fleet(env, led, window)
    # the ledger remembers ok1 in window @N; after a tmux restart that id is a window of another name
    led.add("launch", team="ok1", archetype="builder", order=1, dir=str(w["ok1"][0]), window=w["busy"][1], socket=sock)
    led.add("done", team="ok1", text="x")
    env.run("sweep", "--now", env={"TMUX": f"{sock},0,0"})
    assert "busy" in _names(tm)


def test_gg_and_tyfp_are_documented_side_by_side(env):
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for f in ("README.md", "plugin/skills/wrap-up/SKILL.md", "plugin/skills/stella/SKILL.md"):
        t = (root / f).read_text()
        assert "`gg`" in t and "`tyfp`" in t, f
    h = env.run("--help").stdout
    assert "tyfp" in h and "gg" in h
