"""The status line every turn ends with (Stop hook), and `gg` (UserPromptSubmit hook) with `wrapup <team>`.
Windows are throwaway tmux servers on temp sockets, never the owner's."""

import json
import time

import pytest
from test_gate import _commit
from test_wrapup import _repo, _types, led, window  # noqa: F401 - fixtures

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
    assert "uncommitted changes in proj" in out["reason"] and "NEXT FOR YOU: commit or discard the changes in proj" in out["reason"]
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


def _gg_env(env, sock, pane, **extra):
    return {"TMUX": f"{sock},0,0", "TMUX_PANE": pane, "STELLA_GG_DELAY": "0.2", **extra}


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


def _setup(env, led, window, archetype="builder", status="done", **kw):
    r = _repo(env)
    wid, sock, tm = window("#!/bin/sh\nsleep 600\n")
    led.team(dir=str(r), window=wid, socket=sock, archetype=archetype, done_ago=10 if status == "done" else None, **kw)
    pane = tm("list-panes", "-t", wid, "-F", "#{pane_id}").stdout.split()[0]
    return r, wid, sock, tm, pane


def test_gg_closes_a_clean_team_and_its_window_and_orders(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    out = _gg(env, _gg_env(env, sock, pane, **TEAM), " GG\n", cwd=r)
    assert out["decision"] == "block" and "wrapped up" in out["reason"]  # the prompt never goes to the model
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
    assert out["decision"] == "block" and out["reason"].startswith("gg: not closing, uncommitted changes in proj")
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
    assert out["decision"] == "block" and "wrapped up" in out["reason"]
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
    assert "not inside tmux" in _gg(env, {})["reason"]


def test_wrapup_by_team_name_is_the_same_checks_and_closing(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    (r / "wip.txt").write_text("x\n")
    e = {"TMUX": f"{sock},0,0"}
    assert "not closing, uncommitted changes in proj" in env.run("wrapup", "alpha", env=e).stdout
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


def test_gg_from_a_sandbox_that_cannot_reach_tmux_is_queued_for_the_scheduler(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    out = _gg(env, _gg_env(env, sock, "%999", **TEAM), cwd=r)  # tmux answers nothing for this pane, as in a sandbox
    assert out["decision"] == "block" and "scheduler" in out["reason"] and "could not find" not in out["reason"]
    [req] = list((env.store / "gg").glob("*.json"))
    assert "wrapped_up" not in _types(env)  # nothing recorded until the window can really be closed
    req.write_text(json.dumps({**json.loads(req.read_text()), "pane": pane}))  # the scheduler reaches the real pane
    env.run("wrapup", "--process-requests", env={"TMUX": f"{sock},0,0"})
    assert _wait_gone(tm) and "wrapped_up" in _types(env) and not list((env.store / "gg").glob("*.json"))


def test_a_queued_gg_is_rechecked_when_the_scheduler_gets_to_it(env, led, window):
    r, wid, sock, tm, pane = _setup(env, led, window)
    _gg(env, _gg_env(env, sock, "%999", **TEAM), cwd=r)
    [req] = list((env.store / "gg").glob("*.json"))
    req.write_text(json.dumps({**json.loads(req.read_text()), "pane": pane}))
    (r / "wip.txt").write_text("x\n")
    env.run("wrapup", "--process-requests", env={"TMUX": f"{sock},0,0"})
    assert "alpha" in tm("list-windows", "-a", "-F", "#{window_name}").stdout
    assert "uncommitted changes in proj" in env.run("attention").stdout
