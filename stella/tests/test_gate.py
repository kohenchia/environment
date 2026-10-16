"""Requirement 20: nothing is pushed from a guarded repo without the owner."""

import json

import pytest


def _commit(env, repo, name="f.txt", text="x\n", msg="change"):
    (repo / name).write_text(text)
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "-m", msg)
    return env.git(repo, "rev-parse", "HEAD").stdout.strip()


def _pretool(env, command, cwd):
    out = env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})
    return (out or {}).get("permissionDecision")


def _remote_head(env, repo):
    return env.git(env.tmp / "remote.git", "rev-parse", "main").stdout.strip()


@pytest.mark.parametrize("cmd", [
    "git push", "git push origin main", "git push --force", "git push --no-verify origin main",
    "git push --delete origin main", "git push --tags", "git -c core.hooksPath=/dev/null push",
    "gh pr create --fill", "gh pr merge 3", "gh api -X POST repos/o/r/git/refs",
    "git config core.hooksPath /tmp/x", "git config remote.origin.pushurl git@example.com:o/r",
    "git remote set-url --push origin git@example.com:o/r", "rm .git/hooks/pre-push",
    "echo hi && git push", "bash -c 'git push'", "tmux send-keys -t stella-review-dotfiles abc1234 Enter",
])
def test_bash_guard_blocks_from_repo(env, repo, cmd):
    assert _pretool(env, cmd, repo) == "deny"


def test_bash_guard_blocks_by_path_from_elsewhere(env, repo):
    assert _pretool(env, f"git -C {repo} push", env.tmp) == "deny"
    assert _pretool(env, f"cd {repo} && git push", env.tmp) == "deny"


def test_bash_guard_blocks_worktrees(env, repo):
    wt = env.tmp / "wt"
    env.git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    assert _pretool(env, "git push origin feature", wt) == "deny"


def test_bash_guard_allows_normal_work(env, repo):
    for cmd in ("git status", "git commit -m x", "git log", "git fetch", "ls", f"stella push dotfiles"):
        assert _pretool(env, cmd, repo) is None, cmd
    assert _pretool(env, "git push", env.tmp) is None  # not a guarded repo


def test_writes_into_git_dir_and_approvals_are_blocked(env, repo):
    for path in (repo / ".git" / "hooks" / "pre-push", env.store / "approvals" / "x.json"):
        out = env.hook("pretool", {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}, "cwd": str(repo)})
        assert out["permissionDecision"] == "deny"


def test_plain_git_push_fails_even_without_the_bash_guard(env, repo):
    _commit(env, repo)
    r = env.git(repo, "push", "origin", "main", check=False)
    assert r.returncode != 0
    r = env.git(repo, "push", "--no-verify", "origin", "main", check=False)
    assert r.returncode != 0  # blocked push URL
    url = env.git(repo, "remote", "get-url", "origin").stdout.strip()
    r = env.git(repo, "push", url, "HEAD:refs/heads/main", check=False)
    assert r.returncode != 0 and "PUSH GATE" in r.stderr  # pre-push hook, no approval


def test_push_without_approval_is_refused(env, repo):
    _commit(env, repo)
    r = env.run("push", "dotfiles", check=False)
    assert r.returncode != 0 and "no approval" in r.stderr


def test_explicit_instruction_approves_exactly_that_head(env, repo):
    sha = _commit(env, repo)
    out = env.say("A", "S, push dotfiles")
    assert "explicit push approval" in out
    env.run("push", "dotfiles")
    assert _remote_head(env, repo) == sha
    # single use: a second commit is not covered
    _commit(env, repo, "g.txt")
    assert env.run("push", "dotfiles", check=False).returncode != 0


def test_approval_is_void_after_a_new_commit(env, repo):
    _commit(env, repo)
    env.say("A", "S, push dotfiles")
    _commit(env, repo, "late.txt")
    r = env.run("push", "dotfiles", check=False)
    assert r.returncode != 0 and "no approval" in r.stderr


@pytest.mark.parametrize("words", ["S, looks good", "S, ship it", "S, don't push dotfiles yet", "S, go ahead",
                                   "push dotfiles"])
def test_vague_or_unaddressed_assent_is_not_approval(env, repo, words):
    _commit(env, repo)
    env.say("A", words)
    assert env.run("push", "dotfiles", check=False).returncode != 0


def test_push_question_then_yes(env, repo):
    sha = _commit(env, repo)
    q = env.run("push-question", "dotfiles", env={"STELLA_SESSION_ID": "A"}).stdout
    assert sha[:7] in q
    env.say("A", "S, yes")
    env.run("push", "dotfiles")
    assert _remote_head(env, repo) == sha


def test_cli_cannot_forge_an_intent(env, repo):
    _commit(env, repo)
    env.run("note", "push_intent dotfiles")
    env.run("decide", "S, push dotfiles")
    assert env.run("push", "dotfiles", check=False).returncode != 0


def test_expired_instruction(env, repo):
    _commit(env, repo)
    env.say("A", "S, push dotfiles")
    env.write_config(guarded_repos=[str(repo)], push_intent_minutes=0)
    assert env.run("push", "dotfiles", check=False).returncode != 0


def test_review_push_needs_a_terminal(env, repo):
    _commit(env, repo)
    r = env.run("review-push", "dotfiles", check=False)
    assert r.returncode == 2 and "real terminal" in r.stderr


def test_never_force_pushes(env, repo):
    env.git(repo, "commit", "-q", "--amend", "-m", "rewritten")
    env.say("A", "S, push dotfiles")
    r = env.run("push", "dotfiles", check=False)
    assert r.returncode != 0 and "fast-forward" in r.stderr


def test_gate_status(env, repo):
    out = env.run("gate", "status", "dotfiles").stdout
    assert "FAIL" not in out


def test_nightly_audit_flags_an_unapproved_remote_head(env, repo):
    # someone pushed around the gate, straight to the bare remote
    other = env.tmp / "other"
    env.git(env.tmp, "clone", "-q", str(env.tmp / "remote.git"), str(other))
    _commit(env, other, "sneaky.txt")
    env.git(other, "push", "-q", "origin", "main")
    from_cli = env.run("nightly").stdout
    assert "UNAPPROVED" in from_cli
    assert "no approved push produced" in env.run("attention").stdout


def test_a_branch_new_to_the_remote_is_measured_against_its_default_branch(env, repo):
    from stella import gate

    env.git(repo, "remote", "set-head", "origin", "main")
    env.git(repo, "checkout", "-q", "-b", "feature")
    sha = _commit(env, repo)
    assert gate.preflight(repo, "feature")[:2] == (sha, env.git(repo, "rev-parse", "origin/main").stdout.strip())
