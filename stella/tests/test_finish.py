"""Finishing with unpushed commits: the session pushes, so the push prompt appears. It is the prompt, or nothing."""

import json

import pytest

from test_gate import _commit

S = "sess-1"


def _stop(env, cwd, sid=S, active=False, extra_env=None):
    r = env.run("hook", "stop", input=json.dumps({"session_id": sid, "cwd": str(cwd), "stop_hook_active": active}),
                env=extra_env)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def _pre(env, cmd, cwd, sid=S):
    return env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd), "session_id": sid}) or {}


def _post(env, cmd, cwd, sid=S):
    return env.hook("posttool", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd), "session_id": sid})


def test_finishing_with_unpushed_commits_is_blocked_once(env, repo):
    _commit(env, repo)
    first = _stop(env, repo)
    assert first["decision"] == "block"
    assert "git -C" in first["reason"] and "push -u origin main" in first["reason"] and "1 unpushed commit" in first["reason"]
    assert "run `stella" not in first["reason"] and "review-push" not in first["reason"]
    assert _stop(env, repo) == {}  # one reminder per head per session: no loop


def test_a_clean_repo_and_a_pushed_head_finish_freely(env, repo):
    assert _stop(env, repo) == {}
    _commit(env, repo)
    _post(env, "git push", repo)  # the owner said yes
    assert _stop(env, repo, sid="sess-2") == {}


def test_stop_hook_active_never_blocks(env, repo):
    _commit(env, repo)
    assert _stop(env, repo, active=True) == {}


def test_a_new_head_is_a_new_reminder(env, repo):
    _commit(env, repo)
    assert _stop(env, repo)["decision"] == "block"
    _commit(env, repo, text="y\n", msg="again")
    assert _stop(env, repo)["decision"] == "block"


def test_the_push_goes_through_the_prompt_and_a_no_is_a_deferral(env, repo):
    _commit(env, repo)
    assert _stop(env, repo)["decision"] == "block"
    out = _pre(env, "git push -u origin main", repo)  # what the session does next
    assert out["permissionDecision"] == "ask" and out["permissionDecisionReason"].startswith("Push dotfiles")
    # the owner answered no: the tool never ran, so no PostToolUse and the remote has nothing new
    assert env.git(env.tmp / "remote.git", "rev-parse", "main").stdout != env.git(repo, "rev-parse", "HEAD").stdout
    done = _stop(env, repo)
    assert "decision" not in done and done["systemMessage"].startswith("not pushed, deferred: dotfiles main")
    assert [e["type"] for e in env.events() if e["type"] == "push_deferred"] == ["push_deferred"]
    assert _stop(env, repo) == {}  # recorded once, no nagging
    assert _stop(env, repo, sid="sess-2") == {}  # nor from another session on the same head
    assert len([e for e in env.events() if e["type"] == "push_deferred"]) == 1


def test_a_yes_is_not_a_deferral(env, repo):
    _commit(env, repo)
    _pre(env, "git push", repo)
    _post(env, "git push", repo)
    assert _stop(env, repo) == {}
    assert not [e for e in env.events() if e["type"] == "push_deferred"]


def test_a_repo_committed_in_this_session_counts_though_the_cwd_is_elsewhere(env, repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _commit(env, repo)
    assert _stop(env, elsewhere) == {}  # not worked in
    _post(env, f"git -C {repo} commit -m x", elsewhere)
    assert _stop(env, elsewhere)["decision"] == "block"


def test_stellas_own_session_is_only_held_to_repos_she_committed_in(env, repo):
    from stella.run import ENV

    own = {ENV: "1"}
    _commit(env, repo)
    assert _stop(env, repo, extra_env=own) == {}  # her cwd is not a repo she worked in
    _post(env, "git commit -am x", repo)
    out = _stop(env, repo, extra_env=own)
    assert out["decision"] == "block"
    assert _stop(env, repo, extra_env=own) == {}  # and she is reminded once, not every turn


def test_a_detached_head_is_told_to_get_a_branch(env, repo):
    _commit(env, repo)
    env.git(repo, "checkout", "-q", "--detach")
    assert "on no branch" in _stop(env, repo)["reason"]


def test_a_repo_without_a_remote_needs_no_push(env, tmp_path):
    r = tmp_path / "plain"
    r.mkdir()
    env.git(r, "init", "-q")
    _commit(env, r)
    assert _stop(env, r) == {}


def test_done_is_refused_once_then_goes_through(env, repo):
    _commit(env, repo)
    sess = {"STELLA_SESSION_ID": S}
    r = env.run("done", "alpha", "built it", env=sess, cwd=repo, check=False)
    assert r.returncode == 1 and "push -u origin main" in r.stderr
    assert not [e for e in env.events() if e["type"] == "done"]
    r = env.run("done", "alpha", "built it", env=sess, cwd=repo, check=False)
    assert r.returncode == 0
    assert "[not pushed: dotfiles main" in [e for e in env.events() if e["type"] == "done"][0]["text"]


def test_done_after_a_declined_push_says_deferred(env, repo):
    _commit(env, repo)
    _pre(env, "git push", repo)
    r = env.run("done", "alpha", "built it", env={"STELLA_SESSION_ID": S}, cwd=repo)
    assert r.returncode == 0
    assert "not pushed, deferred" in [e for e in env.events() if e["type"] == "done"][0]["text"]


def test_done_outside_a_claude_session_is_not_checked(env, repo):
    _commit(env, repo)
    assert env.run("done", "alpha", "x", cwd=repo).returncode == 0


@pytest.mark.parametrize("cmd", ["review-push", "push-question", "push"])
def test_the_manual_push_commands_are_gone(env, cmd):
    r = env.run(cmd, "dotfiles", check=False)
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_nothing_in_the_core_tells_anyone_to_run_a_push_command():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = [str(p) for p in list(root.glob("src/**/*.py")) + list(root.glob("plugin/**/*")) + [root / "README.md"]
            if p.is_file() and any(w in p.read_text() for w in ("review-push", "stella push", "push-question"))]
    assert hits == []
