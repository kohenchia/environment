"""An uncommitted file is a session's business only if that session wrote it last (`related.check`, used by gg, the Stop hook,
tyfp, the sweep and `wrapup <team>` through status.blockers). Temp repos only; no tmux."""

import datetime as dt
import json

from test_gate import _writes
from test_status_gg import SESS, _stop
from test_wrapup import _repo, _sweep, led  # noqa: F401 - fixtures

DONE = "Done.\n\n" + "━" * 40 + "\n🟩 **ALL DONE** — ready to wrap up. Type `gg`."


def _session_lines(env, sid, *tools, ago_s=5, sub=None):
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=ago_s)).isoformat().replace("+00:00", "Z")
    d = env.tmp / "transcripts" / "-p"
    if sub:  # a subagent's transcript sits in the lead's directory
        d = d / sub / "subagents"
    d.mkdir(parents=True, exist_ok=True)
    name = "agent-1" if sub else sid
    (d / f"{name}.jsonl").write_text("".join(json.dumps({"type": "assistant", "timestamp": ts, "cwd": str(env.tmp), "message": {
        "content": [{"type": "tool_use", "name": n, "input": i}]}}) + "\n" for n, i in tools))


def test_untracked_symlinks_and_installed_claude_files_are_nobodys_work(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / ".claude" / "skills").mkdir(parents=True)
    (r / ".claude" / "skills" / "f.md").write_text("installed\n")
    (r / "link").symlink_to(env.tmp)
    assert _stop(env, DONE, r) == {}


def test_a_file_the_session_wrote_blocks_and_is_named(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("edited\n")
    (r / "b.txt").write_text("new\n")
    _writes(env, SESS, r / "a.txt")
    _writes(env, SESS, r / "b.txt")
    reason = _stop(env, DONE, r)["reason"]
    assert "uncommitted in proj: " in reason and "a.txt" in reason and "b.txt" in reason


def test_a_changed_file_nobody_is_known_to_have_written_blocks_no_one(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("changed by hand\n")
    assert _stop(env, DONE, r) == {}  # not its business; Stella lists it as unowned
    assert "unowned: proj 1 uncommitted file (no known writer)" in env.run("attention").stdout


def test_a_file_another_live_team_wrote_does_not_block_a_bystander(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.team(name="beta", dir=str(r), done_ago=None)  # running
    (r / "a.txt").write_text("edited by beta\n")
    _writes(env, "sess-beta", r / "a.txt")
    assert _stop(env, DONE, r) == {}
    assert "unowned" not in env.run("attention").stdout  # a live team has it
    (r / "mine.txt").write_text("edited by alpha\n")
    _writes(env, SESS, r / "mine.txt")
    reason = _stop(env, DONE, r)["reason"]
    assert "mine.txt" in reason and "a.txt" not in reason


def test_the_last_writer_owns_the_file(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.team(name="beta", dir=str(r), done_ago=None)
    (r / "a.txt").write_text("x\n")
    _writes(env, SESS, r / "a.txt", ago_s=60)  # alpha wrote it first
    _writes(env, "sess-beta", r / "a.txt", ago_s=5)  # beta last
    assert _stop(env, DONE, r) == {}
    _writes(env, SESS, r / "a.txt", ago_s=1)  # and alpha once more
    assert "a.txt" in _stop(env, DONE, r)["reason"]


def test_a_files_closed_writer_does_not_block_the_bystander_and_becomes_an_unowned_item(env, led):
    r = _repo(env)
    led.team(name="docs", dir=str(r))
    led.add("reaped", ago=120, team="docs")  # wrapped up two hours ago
    led.team(name="tracker", dir=str(r))
    (r / "a.txt").write_text("docs effort left this\n")
    _writes(env, "sess-docs", r / "a.txt")
    out = env.run("wrapup", "tracker", "--dry-run").stdout
    assert "would wrap up tracker" in out
    att = env.run("attention").stdout
    assert "unowned: proj 1 uncommitted file (from the docs effort, closed 2h ago): a.txt" in att


def test_a_subagents_writes_are_its_leads(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("by a subagent\n")
    _session_lines(env, "ignored", ("Write", {"file_path": str(r / "a.txt"), "content": "x"}), sub=SESS)
    assert "a.txt" in _stop(env, DONE, r)["reason"]


def test_a_redirect_a_sed_in_place_and_an_rm_count_as_writes(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "gone.txt").write_text("y\n")
    env.git(r, "add", ".")
    env.git(r, "commit", "-q", "-m", "more")
    env.git(r, "push", "-q")
    (r / "gone.txt").unlink()
    (r / "out.txt").write_text("x\n")
    (r / "a.txt").write_text("sed\n")
    _session_lines(env, SESS, ("Bash", {"command": f"echo x > {r}/out.txt"}), ("Bash", {"command": f"sed -i 's/a/b/' {r}/a.txt"}),
                   ("Bash", {"command": f"rm {r}/gone.txt"}))
    reason = _stop(env, DONE, r)["reason"]
    assert "out.txt" in reason and "a.txt" in reason and "gone.txt" in reason


def test_a_resumed_session_keeps_the_teams_earlier_writes(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.add("started", ago=1, team="alpha", session="sess-alpha-2")  # resumed under a new id
    (r / "a.txt").write_text("written before the resume\n")
    _writes(env, "sess-alpha", r / "a.txt")
    assert "a.txt" in _stop(env, DONE, r, sid="sess-alpha-2")["reason"]


def test_a_session_that_only_read_the_repo_is_never_blocked(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("someone else\n")
    _session_lines(env, SESS, ("Bash", {"command": f"cd {r} && git status"}), ("Read", {"file_path": str(r / "a.txt")}))
    assert _stop(env, DONE, r) == {}


def test_the_sweep_uses_the_same_rule(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("edited\n")
    _writes(env, SESS, r / "a.txt")
    assert "uncommitted in proj: a.txt" in _sweep(env)


def test_the_sweep_wraps_up_past_an_untracked_symlink(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "x").symlink_to(env.tmp)
    assert "wrapped up alpha" in _sweep(env)


def test_what_was_left_alone_is_one_calm_line():
    from stella import related

    r = related.Result(left={"foreign": 2, "unowned": 1, "untracked": 3})
    assert related.left_line([("proj", r)]) == "left alone: 3 uncommitted files in proj, not from this session"
    assert related.left_line([("proj", related.Result(left={"untracked": 3}))]) == ""
    assert related.left_line([("proj", related.Result())]) == ""
