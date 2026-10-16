"""Finishing with unpushed commits: the session pushes, so the push prompt appears. It is the prompt, or nothing."""

import json

import pytest

from test_gate import _alive, _commit as _gc

S = "sess-1"


def _commit(env, repo, by=S, **kw):
    return _gc(env, repo, by=by, **kw)


def _stop(env, cwd, sid=S, active=False, extra_env=None):
    r = env.run("hook", "stop", input=json.dumps({"session_id": sid, "cwd": str(cwd), "stop_hook_active": active,
                                                  "last_assistant_message": "x\n\n" + "━" * 40 + "\n🟧 **NEXT FOR YOU** (1)\n1. x"}),
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
    assert "stella push --plan -C" in first["reason"] and "AskUserQuestion" in first["reason"] and "push -u origin" not in first["reason"] and "1 unpushed commit" in first["reason"]
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
    assert out["permissionDecision"] == "ask" and "PUSH  dotfiles → main" in out["permissionDecisionReason"]
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


def test_the_session_that_made_the_commit_is_asked_wherever_its_cwd_is(env, repo, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _commit(env, repo)
    assert _stop(env, elsewhere)["decision"] == "block"


def test_a_bystander_in_the_same_repo_is_never_asked_about_commits_it_did_not_make(env, repo):
    _commit(env, repo, by="the-other-effort")
    assert _stop(env, repo) == {}  # S works in this repo, but the commit is not its


def test_a_commit_with_no_record_is_nobodys_to_push(env, repo):
    _commit(env, repo, by=None)
    assert _stop(env, repo) == {}


def test_stellas_own_session_is_only_asked_about_commits_she_made(env, repo):
    from stella.run import ENV

    own = {ENV: "1"}
    _commit(env, repo, by="some-team")
    assert _stop(env, repo, extra_env=own) == {}  # a team's commit in a repo she is in
    _commit(env, repo, by=S, text="y\n", msg="hers")
    out = _stop(env, repo, extra_env=own)
    assert out["decision"] == "block" and "1 unpushed commit you made" in out["reason"]
    assert _stop(env, repo, extra_env=own) == {}  # and she is reminded once, not every turn


def test_a_detached_head_is_told_to_get_a_branch(env, repo):
    env.git(repo, "checkout", "-q", "--detach")
    _commit(env, repo)
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
    assert r.returncode == 1 and "stella push --plan -C" in r.stderr
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


@pytest.mark.parametrize("cmd", ["review-push", "push-question"])
def test_the_manual_push_commands_are_gone(env, cmd):
    r = env.run(cmd, "dotfiles", check=False)
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_nothing_in_the_core_tells_anyone_to_run_a_push_command():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    hits = [str(p) for p in list(root.glob("src/**/*.py")) + list(root.glob("plugin/**/*")) + [root / "README.md"]
            if p.is_file() and any(w in p.read_text() for w in ("review-push", "push-question"))]
    assert hits == []


# ---- a deferred push stays on the owner's list until it is pushed or dropped


def _deferred(env, repo):
    _alive(env, S)
    _commit(env, repo)
    _pre(env, "git push", repo)
    _stop(env, repo)


def test_a_deferred_push_is_an_attention_item_in_the_brief(env, repo):
    _deferred(env, repo)
    out = env.run("attention").stdout
    assert "deferred push: dotfiles main (1 commit)" in out and "run " not in out.split("deferred push")[1]
    assert "deferred push: dotfiles main (1 commit)" in env.run("brief").stdout


def test_the_item_clears_itself_once_the_commits_are_pushed(env, repo):
    _deferred(env, repo)
    env.git(repo, "push", "-q", "origin", "main")  # raised again through the prompt, and approved
    assert "Nothing needs you" in env.run("attention").stdout
    assert "deferred push" not in env.run("brief").stdout


def test_the_owner_can_drop_the_item(env, repo):
    _deferred(env, repo)
    key = env.run("attention", "--json").stdout
    key = json.loads(key)[0]["key"]
    env.run("ack", key)
    assert "Nothing needs you" in env.run("attention").stdout


def test_the_morning_digest_prompt_lists_deferred_pushes():
    from stella import daily

    assert "deferred push:" in daily.REFLECT


def test_a_session_cannot_forge_a_deferral(env):
    r = env.run("log", "push_deferred", "--text", "x", check=False)
    assert r.returncode != 0
