"""Requirement 20: a Claude session's push from a guarded repo asks the owner first; the owner's own push is plain git."""

import pytest

from stella.gate import BLOCKED_URL, HOOK_SCRIPT


def _commit(env, repo, name="f.txt", text="x\n", msg="change"):
    (repo / name).write_text(text)
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "-m", msg)
    return env.git(repo, "rev-parse", "HEAD").stdout.strip()


def _pretool_out(env, command, cwd):
    return env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}) or {}


def _pretool(env, command, cwd):
    return _pretool_out(env, command, cwd).get("permissionDecision")


def _remote_head(env):
    return env.git(env.tmp / "remote.git", "rev-parse", "main").stdout.strip()


def _hooks(repo):
    return repo / ".git" / "hooks"


def _old_gate(env, repo):
    """What the old push gate left in a repo: its pre-push hook and a blocked push URL."""
    bin_ = (env.tmp / "old-bin").as_posix()
    (_hooks(repo) / "pre-push").write_text(HOOK_SCRIPT.format(bin=bin_, name="pre-push"))
    (_hooks(repo) / "pre-push").chmod(0o755)
    env.git(repo, "config", "remote.origin.pushurl", BLOCKED_URL)


@pytest.mark.parametrize("cmd", [
    "git push", "git push origin main", "git push --force", "git push --no-verify origin main",
    "git push --delete origin main", "git push --tags", "git -c core.hooksPath=/dev/null push",
    "gh pr create --fill", "gh pr merge 3", "gh api -X POST repos/o/r/git/refs",
    "echo hi && git push", "bash -c 'git push'", "/usr/bin/git push -u origin HEAD",
])
def test_a_push_from_a_guarded_repo_asks_the_owner(env, repo, cmd):
    assert _pretool(env, cmd, repo) == "ask"


def test_the_prompt_names_the_repo_and_branch(env, repo):
    _commit(env, repo)
    reason = _pretool_out(env, "git push origin main", repo)["permissionDecisionReason"]
    assert reason.startswith("Push dotfiles?")
    assert "main is 1 commit(s) ahead of origin/main" in reason and "change" in reason and "1 file changed" in reason
    assert "outstanding list" in reason and "git push origin main" in reason


def test_a_push_by_path_from_elsewhere_asks(env, repo):
    assert _pretool(env, f"git -C {repo} push", env.tmp) == "ask"
    assert _pretool(env, f"cd {repo} && git push", env.tmp) == "ask"


def test_a_push_from_a_worktree_asks(env, repo):
    wt = env.tmp / "wt"
    env.git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    out = _pretool_out(env, "git push origin feature", wt)
    assert out["permissionDecision"] == "ask" and "feature is" in out["permissionDecisionReason"]


@pytest.mark.parametrize("cmd", [
    "git status", "git commit -m x", "git log", "git fetch", "ls", "git log --grep=push",
    # no longer blocked: only pushes are the owner's call
    "git config core.hooksPath /tmp/x", "git config remote.origin.pushurl git@example.com:o/r",
    "git remote set-url --push origin git@example.com:o/r", "rm .git/hooks/pre-push",
])
def test_everything_else_in_a_guarded_repo_runs_without_a_prompt(env, repo, cmd):
    assert _pretool(env, cmd, repo) is None


def test_a_push_from_an_unguarded_repo_runs_without_a_prompt(env, repo):
    other = env.tmp / "other"
    env.git(env.tmp, "clone", "-q", str(env.tmp / "remote.git"), str(other))
    assert _pretool(env, "git push", other) is None
    assert _pretool(env, "git push", env.tmp) is None


def test_writes_into_the_git_dir_are_not_blocked(env, repo):
    path = _hooks(repo) / "pre-push"
    out = env.hook("pretool", {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": "x"}, "cwd": str(repo)})
    assert out is None


def test_the_owners_own_push_is_plain_git(env, repo):
    sha = _commit(env, repo)
    env.git(repo, "push", "-q", "origin", "main")
    assert _remote_head(env) == sha


def test_gate_install_removes_the_old_push_gate(env, repo):
    _old_gate(env, repo)
    status = env.run("gate", "status", "dotfiles").stdout
    assert "FAIL the old push gate's pre-push hook" in status and "remote.origin.pushurl" in status
    out = env.run("gate", "install", "dotfiles").stdout
    assert "removed the old push gate's pre-push hook" in out and "unset remote.origin.pushurl" in out
    assert not (_hooks(repo) / "pre-push").exists()
    assert env.git(repo, "config", "--get", "remote.origin.pushurl", check=False).stdout.strip() == ""
    assert "FAIL" not in env.run("gate", "status", "dotfiles").stdout
    sha = _commit(env, repo)
    r = env.git(repo, "push", "origin", "main", check=False)
    assert r.returncode == 0, r.stderr
    assert _remote_head(env) == sha


def test_gate_install_restores_the_owners_own_pre_push_hook(env, repo):
    _old_gate(env, repo)
    mine = "#!/bin/sh\n# the owner's own hook\nexit 0\n"
    (_hooks(repo) / "pre-push.pre-stella").write_text(mine)
    env.run("gate", "install", "dotfiles")
    assert (_hooks(repo) / "pre-push").read_text() == mine
    assert not (_hooks(repo) / "pre-push.pre-stella").exists()
    assert "FAIL" not in env.run("gate", "status", "dotfiles").stdout


def test_gate_install_leaves_other_push_urls_alone(env, repo):
    env.git(repo, "config", "remote.origin.pushurl", str(env.tmp / "remote.git"))
    env.run("gate", "install", "dotfiles")
    assert env.git(repo, "config", "--get", "remote.origin.pushurl").stdout.strip() == str(env.tmp / "remote.git")


def test_gate_keeps_the_leak_guard_commit_hooks(env, repo):
    out = env.run("gate", "status", "dotfiles").stdout
    assert "FAIL" not in out
    assert "ok   pre-commit hook" in out and "ok   commit-msg hook" in out
    for name in ("pre-commit", "commit-msg"):
        assert "git-hook" in (_hooks(repo) / name).read_text()


def test_a_leftover_pre_push_hook_lets_the_push_through(env, repo):
    r = env.run("git-hook", "pre-push", "origin", "url", input="refs/heads/main a refs/heads/main b\n", cwd=repo, check=False)
    assert r.returncode == 0


def test_asking_stella_to_push_is_just_an_order(env, repo):
    _commit(env, repo)
    out = env.say("A", "S, push dotfiles")
    assert "push approval" not in out
    assert [e["type"] for e in env.events()] == ["order"]


@pytest.mark.parametrize("cmd", ["push", "review-push", "push-question"])
def test_the_approval_commands_are_gone(env, repo, cmd):
    r = env.run(cmd, "dotfiles", check=False)
    assert r.returncode == 2 and "invalid choice" in r.stderr
