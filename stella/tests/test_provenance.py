"""Provenance of commits: who made them (PostToolUse with a before/after snapshot, the post-commit git hook, the transcripts),
what that decides for gg, the Stop hook, `wrapup <team>`, and what nobody owns (the unowned items). Temp repos; no tmux."""

import json
import subprocess

from conftest import BIN
from test_gate import _alive, _commit
from test_finish import _stop as _fstop
from test_status_gg import DONE, DONE_STELLA, SESS, _stop
from test_wrapup import led  # noqa: F401 - fixtures



def _run_hooked(env, repo, sid, git_args, team=None, tool_id="t1", cmd=None):
    """What the tool hooks do around a Bash `git …`: PreToolUse snapshot, the command, PostToolUse record."""
    cmd = cmd or f"git -C {repo} " + " ".join(git_args)
    e = {"STELLA_TEAM": team} if team else None
    base = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(repo), "session_id": sid, "tool_use_id": tool_id}
    env.hook("pretool", base, env=e)
    env.git(repo, *git_args)
    env.hook("posttool", base, env=e)
    return env.git(repo, "rev-parse", "HEAD").stdout.strip()


def _recs(env):
    p = env.store / "provenance.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def _team(led, name, repo, done_ago=10):
    led.team(name=name, dir=str(repo), done_ago=done_ago)


# ---------------------------------------------------------------- recording


def test_a_commit_is_recorded_for_the_session_that_ran_it(env, repo):
    (repo / "a.txt").write_text("a\n")
    env.git(repo, "add", ".")
    sha = _run_hooked(env, repo, "s-1", ["commit", "-q", "-m", "mine"], team="alpha")
    [rec] = _recs(env)
    assert rec["sha"] == sha and rec["session"] == "s-1" and rec["team"] == "alpha" and rec["src"] == "post-tool" and rec["patch"]


def test_a_fast_forward_pull_makes_no_commits_and_claims_none(env, repo, tmp_path):
    other = tmp_path / "clone"
    env.git(tmp_path, "clone", "-q", str(env.tmp / "remote.git"), str(other))
    _commit(env, other, name="theirs.txt")
    env.git(other, "push", "-q", "origin", "main")
    _run_hooked(env, repo, "s-1", ["pull", "-q", "--ff-only", "origin", "main"])
    assert _recs(env) == []  # it brought someone else's commit; it made none


def test_an_amend_keeps_the_owner_whoever_amends(env, repo):
    sha = _commit(env, repo, by="s-owner", team="alpha")
    (repo / "g.txt").write_text("fixed\n")
    env.git(repo, "add", ".")
    new = _run_hooked(env, repo, "s-other", ["commit", "-q", "--amend", "--no-edit"], team="beta")
    assert new != sha
    r = {x["sha"]: x for x in _recs(env)}[new]
    assert r["session"] == "s-owner" and r["team"] == "alpha" and r["src"] == "inherit"


def test_a_rebase_keeps_each_commits_owner_by_patch_id(env, repo):
    env.git(repo, "switch", "-q", "-c", "feature")
    _commit(env, repo, name="one.txt", by="s-a", team="a")
    _commit(env, repo, name="two.txt", by="s-b", team="b")
    env.git(repo, "switch", "-q", "main")
    _commit(env, repo, name="main.txt", by="s-m")
    env.git(repo, "switch", "-q", "feature")
    _run_hooked(env, repo, "s-rebaser", ["rebase", "-q", "main"], team="rb")
    new = env.git(repo, "rev-list", "--reverse", "main..feature").stdout.split()
    by = {x["sha"]: x["session"] for x in _recs(env)}
    assert [by[s] for s in new] == ["s-a", "s-b"]  # the rebaser made none of them


def test_a_cherry_pick_is_made_by_the_one_who_picked(env, repo):
    env.git(repo, "switch", "-q", "-c", "other")
    src = _commit(env, repo, name="x.txt", by="s-a")
    env.git(repo, "switch", "-q", "main")
    _commit(env, repo, name="y.txt", by="s-main")  # main moves on, so the pick makes a new commit
    new = _run_hooked(env, repo, "s-picker", ["cherry-pick", src])
    assert {x["sha"]: x["session"] for x in _recs(env)}[new] == "s-picker"


def test_a_merge_claims_only_the_merge_commit(env, repo):
    env.git(repo, "switch", "-q", "-c", "side")
    side = _commit(env, repo, name="s.txt")  # legacy: no record
    env.git(repo, "switch", "-q", "main")
    _commit(env, repo, name="m.txt", by="s-main")
    merged = _run_hooked(env, repo, "s-merger", ["merge", "-q", "--no-ff", "-m", "merge", "side"])
    by = {x["sha"]: x["session"] for x in _recs(env)}
    assert by[merged] == "s-merger" and side not in by


def test_a_subagents_commit_is_its_leads_because_the_hook_carries_the_lead_session(env, repo):
    (repo / "a.txt").write_text("a\n")
    env.git(repo, "add", ".")
    _run_hooked(env, repo, "lead-session", ["commit", "-q", "-m", "by a subagent"], team="alpha")
    assert _recs(env)[0]["session"] == "lead-session"


def test_stella_committing_for_a_team_hands_it_the_commit(env, repo):
    (repo / "a.txt").write_text("a\n")
    env.git(repo, "add", ".")
    _run_hooked(env, repo, "stella-s", ["commit", "-q", "-m", "x"], cmd=f"STELLA_COMMIT_FOR=docs git -C {repo} commit -q -m x")
    assert _recs(env)[0]["team"] == "docs" and _recs(env)[0]["session"] == "stella-s"


def test_the_post_commit_git_hook_records_from_the_environment(env, repo):
    from stella import gate

    assert "post-commit" in gate.COMMIT_HOOKS and "post-commit" in (repo / ".git" / "hooks" / "post-commit").read_text() + "post-commit"
    (repo / "a.txt").write_text("a\n")
    env.git(repo, "add", ".")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], check=True,
                   env={**env.env, "STELLA_SESSION_ID": "s-hook", "STELLA_TEAM": "alpha"})
    [rec] = _recs(env)
    assert rec["session"] == "s-hook" and rec["team"] == "alpha" and rec["src"] == "git-hook" and str(BIN)


def test_backfill_reads_the_commit_from_a_transcript(env, repo):
    sha = _commit(env, repo, name="old.txt", msg="made long ago")
    d = env.tmp / "transcripts" / "-p"
    d.mkdir(parents=True)
    events = [
        {"type": "assistant", "timestamp": "2026-10-01T10:00:00Z", "cwd": str(repo), "message": {"content": [
            {"type": "tool_use", "id": "u1", "name": "Bash", "input": {"command": "git commit -m 'made long ago'"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "u1",
                                                   "content": f"[main {sha[:7]}] made long ago\n 1 file changed"}]}},
    ]
    (d / "old-session.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
    assert "recorded the owner of 1 commit" in env.run("provenance", "backfill").stdout
    assert _recs(env)[0]["sha"] == sha and _recs(env)[0]["session"] == "old-session" and _recs(env)[0]["src"] == "transcript"


# ---------------------------------------------------------------- what it decides


def test_a_bystander_is_not_blocked_by_commits_of_another_effort_in_its_repo(env, led, repo):
    """The failure of 2026-10-16: a team was blocked by the four commits of an earlier effort that shared its repo."""
    _team(led, "docs", repo)
    led.add("reaped", ago=120, team="docs")
    _team(led, "tracker", repo)
    _commit(env, repo, by="sess-docs", team="docs")
    assert "would wrap up tracker" in env.run("wrapup", "tracker", "--dry-run").stdout
    assert _stop(env, "Done.\n\n" + DONE, repo) == {}  # the Stop hook of the bystander neither blocks nor asks it to push
    att = env.run("attention").stdout
    assert "unowned: dotfiles main 1 unpushed commit (from the docs effort, closed 2h ago)" in att
    assert f"stella push --plan -C {repo}" in att


def test_the_owner_is_blocked_by_its_own_unpushed_commit_and_it_names_exactly_that(env, led, repo):
    _team(led, "docs", repo)
    _team(led, "tracker", repo)
    _commit(env, repo, by="sess-docs", team="docs")
    out = env.run("wrapup", "docs", "--dry-run").stdout
    assert "not closing, 1 unpushed commit in dotfiles (main)" in out
    assert "would wrap up tracker" in env.run("wrapup", "tracker", "--dry-run").stdout


def test_a_declined_push_belongs_to_the_commits_owner_not_to_who_raised_the_prompt(env, led, repo):
    _team(led, "docs", repo)
    _team(led, "tracker", repo)
    sha = _commit(env, repo, by="sess-docs", team="docs")
    # the prompt was raised from tracker's Stop hook and declined: the deferral names tracker's session as the raiser
    led.add("push_deferred", ago=5, team="tracker", repo="dotfiles", path=str(repo), sha=sha, branch="main", session="sess-tracker")
    led.add("alert", ago=5, key=f"push-deferred:dotfiles@{sha}", path=str(repo), sha=sha, text="deferred push: dotfiles main (1 commit)")
    assert "would wrap up tracker" in env.run("wrapup", "tracker", "--dry-run").stdout
    assert "deferred" in env.run("wrapup", "docs", "--dry-run").stdout  # it is the docs effort's
    led.add("reaped", ago=1, team="docs")  # once docs is gone it is an unowned item, replacing the old alert line
    att = env.run("attention").stdout
    assert "unowned: dotfiles main 1 unpushed commit" in att and "the push was declined once" in att and "deferred push:" not in att


def test_a_deferral_for_legacy_commits_is_an_unowned_item_and_blocks_nobody(env, led, repo):
    _team(led, "tracker", repo)
    sha = _commit(env, repo)  # no record
    led.add("push_deferred", ago=5, team="tracker", repo="dotfiles", path=str(repo), sha=sha, branch="main", session="sess-tracker")
    led.add("alert", ago=5, key=f"push-deferred:dotfiles@{sha}", path=str(repo), sha=sha, text="deferred push: dotfiles main (1 commit)")
    assert "would wrap up tracker" in env.run("wrapup", "tracker", "--dry-run").stdout
    att = env.run("attention").stdout
    assert "unowned: dotfiles main 1 unpushed commit (no record of which session made them; the push was declined once)" in att
    assert "deferred push:" not in att


def test_dropping_an_unowned_item_clears_it(env, led, repo):
    _team(led, "tracker", repo)
    sha = _commit(env, repo)
    led.add("push_deferred", ago=5, team="tracker", repo="dotfiles", path=str(repo), sha=sha, branch="main", session="sess-tracker")
    key = f"unowned-push:dotfiles@{sha}"
    assert key in env.run("attention").stdout
    env.run("ack", key)
    assert key not in env.run("attention").stdout


def test_an_old_backlog_of_unrecorded_commits_is_one_summary_line_not_a_flood(env, repo):
    (repo / "old.txt").write_text("x\n")
    env.git(repo, "add", ".")
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "old"], check=True,
                   env={**env.env, "GIT_COMMITTER_DATE": "2026-08-01T00:00:00", "GIT_AUTHOR_DATE": "2026-08-01T00:00:00"})
    att = env.run("attention").stdout
    assert "unowned, old: 1 unpushed commits on 1 local branches with no ownership record" in att and "unowned: dotfiles" not in att


def test_a_commit_already_on_a_remote_branch_is_never_asked(env, repo):
    _commit(env, repo, by=SESS)
    env.git(repo, "push", "-q", "origin", "HEAD:refs/heads/elsewhere")  # reached a remote branch, just not this one
    assert _fstop(env, repo, sid=SESS) == {}


def test_a_commit_in_a_worktree_belongs_to_whoever_made_it_there(env, repo, tmp_path):
    wt = tmp_path / "wt"
    env.git(repo, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    _commit(env, wt, name="w.txt", by=SESS)
    _commit(env, repo, name="theirs.txt", by="other")
    out = _fstop(env, wt, sid=SESS)
    assert out["decision"] == "block" and f"push --plan -C {wt.resolve()}" in out["reason"] and "1 unpushed commit" in out["reason"]
    assert f"push --plan -C {repo.resolve()}" not in out["reason"]


def test_a_team_commit_made_before_a_resume_still_blocks_the_resumed_session(env, led, repo):
    _team(led, "alpha", repo)
    led.add("started", ago=1, team="alpha", session="sess-alpha-2")
    _commit(env, repo, by="sess-alpha", team="alpha")
    assert "1 unpushed commit" in env.run("wrapup", "alpha", "--dry-run").stdout


def test_an_adopted_hand_opened_session_owns_what_it_committed_before_adoption(env, led, repo):
    led.team(name="hand", archetype="adopted", dir=str(repo), done_ago=None)
    _commit(env, repo, by="sess-hand")  # recorded under the session id, no team
    assert "1 unpushed commit" in env.run("wrapup", "hand", "--dry-run").stdout


def test_a_live_plain_session_that_made_the_commit_keeps_the_deferral_as_its_own(env, led, repo):
    sha = _commit(env, repo, by="plain-s")
    _alive(env, "plain-s")
    led.add("push_deferred", ago=5, repo="dotfiles", path=str(repo), sha=sha, branch="main", session="plain-s")
    led.add("alert", ago=5, key=f"push-deferred:dotfiles@{sha}", path=str(repo), sha=sha, text="deferred push: dotfiles main (1 commit)")
    att = env.run("attention").stdout
    assert "deferred push: dotfiles main" in att and "unowned" not in att


def test_stellas_own_attention_list_carries_the_unowned_items(env, led, repo):
    from stella.run import ENV

    _team(led, "tracker", repo)
    sha = _commit(env, repo)
    led.add("push_deferred", ago=5, team="tracker", repo="dotfiles", path=str(repo), sha=sha, branch="main", session="sess-tracker")
    out = _stop(env, "Nothing.\n\n" + DONE_STELLA, repo, sid="stella-s", extra={ENV: "1"})
    assert out["decision"] == "block" and "unowned: dotfiles main 1 unpushed commit" in out["reason"]
