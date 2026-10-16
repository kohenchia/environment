"""Only changes a session could have made keep it open (`related.check`, used by gg, the Stop hook, tyfp, the sweep and
`wrapup <team>` through status.blockers / wrapup.repo_problem). Temp repos only; no tmux."""

import datetime as dt
import json
import os
import time

from test_gate import _commit
from test_status_gg import SESS, _stop
from test_wrapup import _repo, _sweep, led  # noqa: F401 - fixtures

DONE = "Done.\nALL DONE: ready to wrap up. Type gg."


def _old(path, hours=5):
    t = time.time() - hours * 3600
    os.utime(path, (t, t), follow_symlinks=False)


def _writes(env, sid, path, ago_s=5):
    """A transcript in which session `sid` wrote `path`."""
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=ago_s)).isoformat().replace("+00:00", "Z")
    d = env.tmp / "transcripts" / "-p"
    d.mkdir(parents=True, exist_ok=True)
    line = {"type": "assistant", "timestamp": ts, "message": {"content": [
        {"type": "tool_use", "name": "Write", "input": {"file_path": str(path), "content": "x"}}]}}
    (d / f"{sid}.jsonl").write_text(json.dumps(line) + "\n")


def test_old_untracked_symlinks_do_not_block(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / ".claude").mkdir()
    for n in ("agents", "mlc", "skills"):
        (r / ".claude" / n).symlink_to(env.tmp)
        _old(r / ".claude" / n)
    (r / "old.txt").write_text("stray\n")
    _old(r / "old.txt")
    assert _stop(env, DONE, r) == {}


def test_a_fresh_untracked_symlink_does_not_block_either(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "link").symlink_to(env.tmp)
    assert _stop(env, DONE, r) == {}


def test_a_tracked_file_the_session_edited_blocks_and_is_named(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("edited\n")
    (r / "b.txt").write_text("new\n")
    reason = _stop(env, DONE, r)["reason"]
    assert "uncommitted in proj: " in reason and "a.txt" in reason and "b.txt" in reason


def test_a_tracked_change_older_than_the_session_does_not_block(env, led):
    r = _repo(env)
    (r / "a.txt").write_text("edited long ago\n")
    _old(r / "a.txt")
    led.team(dir=str(r))
    assert _stop(env, DONE, r) == {}


def test_a_file_another_teams_window_edited_does_not_block(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    led.team(name="beta", dir=str(r), done_ago=None)  # running
    (r / "a.txt").write_text("edited by beta\n")
    _writes(env, "sess-beta", (r / "a.txt").resolve())
    assert _stop(env, DONE, r) == {}
    (r / "mine.txt").write_text("edited by alpha\n")
    assert "mine.txt" in _stop(env, DONE, r)["reason"]


def test_the_sweep_uses_the_same_rule(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "a.txt").write_text("edited\n")
    assert "uncommitted in proj: a.txt" in _sweep(env)


def test_the_sweep_wraps_up_past_an_untracked_symlink(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "x").symlink_to(env.tmp)
    assert "wrapped up alpha" in _sweep(env)


def test_an_unpushed_commit_still_blocks(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    _commit(env, r)
    assert "unpushed commits" in _stop(env, DONE, r)["reason"]


def test_what_was_left_alone_is_one_calm_line():
    from stella import related

    r = related.Result(left={"untracked": 3})
    assert related.left_line([("proj", r)]) == "left alone: 3 untracked files in proj, not from this session"
    assert related.left_line([("proj", related.Result())]) == ""


def _session_lines(env, sid, *tools, ago_s=5):
    ts = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=ago_s)).isoformat().replace("+00:00", "Z")
    d = env.tmp / "transcripts" / "-p"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}.jsonl").write_text("".join(json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": [
        {"type": "tool_use", "name": n, "input": i}]}}) + "\n" for n, i in tools))


def test_an_old_untracked_directory_of_regular_files_does_not_block_a_session_that_worked_from_the_repo(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    for d in (".claude/agents", ".claude/skills/x"):
        (r / d).mkdir(parents=True)
        (r / d / "f.md").write_text("installed\n")
        _old(r / d / "f.md")
    _session_lines(env, SESS, ("Bash", {"command": f"cd {r} && git status"}), ("Bash", {"command": f"git -C {r} log -1"}))
    assert _stop(env, DONE, r) == {}


def test_a_file_the_session_wrote_blocks_even_beside_old_untracked_ones(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / ".claude" / "agents").mkdir(parents=True)
    (r / ".claude" / "agents" / "f.md").write_text("installed\n")
    _old(r / ".claude" / "agents" / "f.md")
    (r / "notes.md").write_text("mine\n")
    _session_lines(env, SESS, ("Write", {"file_path": str(r / "notes.md"), "content": "mine"}))
    reason = _stop(env, DONE, r)["reason"]
    assert "uncommitted in proj: notes.md" in reason and ".claude" not in reason


def test_a_file_written_with_a_redirect_blocks(env, led):
    r = _repo(env)
    led.team(dir=str(r))
    (r / "out.txt").write_text("x\n")
    _old(r / "out.txt", hours=0)
    _session_lines(env, SESS, ("Bash", {"command": f"echo x > {r}/out.txt"}))
    assert "out.txt" in _stop(env, DONE, r)["reason"]
