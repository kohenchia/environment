"""Requirement 20: a Claude session's push from a guarded repo asks the owner first; the owner's own push is plain git."""

import json
import os
from pathlib import Path

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
    "stella push", "echo hi && git push", "bash -c 'git push'", "/usr/bin/git push -u origin HEAD",
])
def test_a_push_from_a_guarded_repo_asks_the_owner(env, repo, cmd):
    _commit(env, repo)
    assert _pretool(env, cmd, repo) == "ask"


def test_the_prompt_is_short_grouped_and_ends_with_the_choices(env, repo):
    _commit(env, repo)
    reason = _pretool_out(env, "git push origin main", repo)["permissionDecisionReason"]
    assert reason.splitlines() == [
        "▲ PUSH  dotfiles → main", "  1 commit", "", "  · change", "",
        "Yes: push · No: defer"]
    assert "\x1b" not in reason and "FORCE" not in reason 


def test_a_new_branch_and_more_commits_are_counted(env, repo):
    env.git(repo, "switch", "-q", "-c", "feature")
    for i in range(5):
        _commit(env, repo, text=f"{i}\n", msg=f"c{i}")
    lines = _pretool_out(env, "git push", repo)["permissionDecisionReason"].splitlines()
    assert lines[:2] == ["▲ PUSH  dotfiles → feature", "  5 commits · new branch"]
    assert lines[3:7] == ["  · c4", "  · c3", "  · c2", "    … and 2 more"]


def test_stella_push_asks_like_git_push_and_is_never_a_force(env, repo):
    _commit(env, repo)
    for cmd in ("~/.local/bin/stella push", "stella push -C .", f"cd {repo} && stella push"):
        out = _pretool_out(env, cmd, repo)
        assert out["permissionDecision"] == "ask" and "FORCE" not in out["permissionDecisionReason"], cmd
        assert "also runs" not in out["permissionDecisionReason"]
    assert _pretool(env, "stella status", repo) is None
    assert _pretool(env, "echo stella push", repo) is None


def test_a_compound_command_says_so_in_one_line(env, repo):
    _commit(env, repo)
    reason = _pretool_out(env, f"cd {repo} && just style 2>&1 | tail -1; uv run pytest -q; git push -u origin main", repo)["permissionDecisionReason"]
    assert "⚠ This command also runs just style, pytest. Push only?" in reason.splitlines()
    assert reason.splitlines()[-1].startswith("Yes: push")


def test_stella_push_pushes_the_current_branch_and_refuses_a_detached_head(env, repo):
    sha = _commit(env, repo)
    assert env.run("push", cwd=repo, check=False).returncode == 0 and _remote_head(env) == sha
    env.git(repo, "checkout", "-q", "--detach")
    r = env.run("push", cwd=repo, check=False)
    assert r.returncode == 2 and "no branch" in r.stderr


def test_a_force_push_says_so_on_the_first_line(env, repo):
    _commit(env, repo)
    reason = _pretool_out(env, "git push --force origin main", repo)["permissionDecisionReason"]
    assert reason.splitlines()[:2] == ["▲ PUSH  dotfiles → main", "  1 commit · FORCE"]


def test_a_push_by_path_from_elsewhere_asks(env, repo):
    _commit(env, repo)
    assert _pretool(env, f"git -C {repo} push", env.tmp) == "ask"
    assert _pretool(env, f"cd {repo} && git push", env.tmp) == "ask"


def test_a_push_from_a_worktree_asks(env, repo):
    wt = env.tmp / "wt"
    env.git(repo, "worktree", "add", "-q", "-b", "feature", str(wt))
    out = _pretool_out(env, "git push origin feature", wt)
    assert out["permissionDecision"] == "ask" and "dotfiles → feature" in out["permissionDecisionReason"] and "0 commits · new branch" in out["permissionDecisionReason"]


@pytest.mark.parametrize("cmd", [
    "git status", "git commit -m x", "git log", "git fetch", "ls", "git log --grep=push",
    # no longer blocked: only pushes are the owner's call
    "git config core.hooksPath /tmp/x", "git config remote.origin.pushurl git@example.com:o/r",
    "git remote set-url --push origin git@example.com:o/r", "rm .git/hooks/pre-push",
])
def test_everything_else_in_a_guarded_repo_runs_without_a_prompt(env, repo, cmd):
    assert _pretool(env, cmd, repo) is None


def test_a_push_from_an_unguarded_repo_with_a_remote_asks_too(env, repo):
    other = env.tmp / "other"
    env.git(env.tmp, "clone", "-q", str(env.tmp / "remote.git"), str(other))
    _commit(env, other)
    assert _pretool(env, "git push", other) == "ask"
    assert _pretool(env, f"git -C {other} push", env.tmp) == "ask"


def test_a_push_with_nothing_to_push_to_runs_without_a_prompt(env, repo):
    local = env.tmp / "local-only"
    local.mkdir()
    env.git(local, "init", "-q")
    assert _pretool(env, "git push", local) is None
    assert _pretool(env, "git push", env.tmp) is None


def test_an_auto_push_session_is_not_asked(env, repo):
    _commit(env, repo)
    out = env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(repo)},
                   env={"STELLA_AUTO_PUSH": "1"})
    assert not out


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


def test_an_auto_push_session_is_not_asked(env, repo):
    _commit(env, repo)
    out = env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(repo)},
                   env={"STELLA_AUTO_PUSH": "1"})
    assert not out


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


@pytest.mark.parametrize("cmd", ["review-push", "push-question"])
def test_the_approval_commands_are_gone(env, repo, cmd):
    r = env.run(cmd, "dotfiles", check=False)
    assert r.returncode == 2 and "invalid choice" in r.stderr


def test_an_auto_push_session_is_still_asked_before_a_pr(env, repo):
    _commit(env, repo)
    out = env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": "gh pr create --fill"}, "cwd": str(repo)},
                   env={"STELLA_AUTO_PUSH": "1"})
    assert out and out["permissionDecision"] == "ask"


# ---- the prompt is for the real push only, and once per head


@pytest.mark.parametrize("cmd", [
    "git commit -m 'fix push bug'", 'git commit -am "git push it"', "git log --oneline | grep 'git push'",
    "echo git push", "grep -rn 'git push' src", "uv run pytest tests/test_gate.py -k 'git push'",
    "python3 - <<'EOF'\nassert cmd == 'git push'\nEOF", "cat <<EOF > notes.txt\ngit push origin main\nEOF",
    "git commit -F - <<'EOF'\nwill git push later\nEOF", "git status # git push", "bash -c 'echo git push'",
    "gh issue create --title 'gh pr create broke'", "git log --grep push", "git grep push", "git branch push-fix",
    "git checkout -b push", "gh api repos/o/r/pulls", "gh pr view 3",
])
def test_text_that_merely_mentions_a_push_is_not_a_push(env, repo, cmd):
    _commit(env, repo)
    assert _pretool(env, cmd, repo) is None


@pytest.mark.parametrize("cmd", [
    "git commit -m 'x' && git push", "cat <<EOF\nhi\nEOF\ngit push", "FOO=1 git push", "env GIT_X=1 git push",
    "git -C . push", "(git push)", "echo $(git push)", "sh -c \"cd . && git push\"", "time git push",
    "gh api repos/o/r --method POST", "gh api -XDELETE repos/o/r",
])
def test_a_real_push_is_found_wherever_it_sits_in_the_command(env, repo, cmd):
    _commit(env, repo)
    assert _pretool(env, cmd, repo) == "ask"


def _posttool(env, command, cwd):
    return env.hook("posttool", {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)})


def test_an_approved_head_is_not_asked_again(env, repo):
    _commit(env, repo)
    assert _pretool(env, "git push origin main", repo) == "ask"
    _posttool(env, "git push origin main", repo)  # it ran: the owner said yes
    assert _pretool(env, "git push origin main", repo) is None
    assert _pretool(env, "gh pr create --fill", repo) is None  # same head, same approval
    _commit(env, repo, name="g.txt", msg="more")  # a new head is a new question
    assert _pretool(env, "git push origin main", repo) == "ask"


def test_a_declined_push_leaves_nothing_remembered(env, repo):
    _commit(env, repo)
    assert _pretool(env, "git push", repo) == "ask"
    assert _pretool(env, "git push", repo) == "ask"  # no PostToolUse ran: the owner said no


def test_the_approval_is_shared_by_every_session_and_subagent(env, repo):
    _commit(env, repo)
    _posttool(env, "git push", repo)
    other_session = {"CLAUDE_SESSION_ID": "someone-else", "STELLA_TEAM": "a-subagent"}
    out = env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(repo)}, env=other_session)
    assert not out


def test_a_plain_push_with_nothing_ahead_is_not_asked_but_a_delete_is(env, repo):
    assert _pretool(env, "git push origin main", repo) is None
    assert _pretool(env, "git push --delete origin main", repo) == "ask"
    assert _pretool(env, "git push origin :main", repo) == "ask"


def test_a_command_that_only_mentions_a_path_does_not_pull_in_that_repo(env, repo):
    _commit(env, repo)
    plain = env.tmp / "plain"
    plain.mkdir()
    assert _pretool(env, f"cat {repo}/f.txt; git push", plain) is None


def test_a_push_from_a_shell_variable_path_asks_without_naming_the_wrong_repo(env, repo):
    _commit(env, repo)
    out = _pretool_out(env, 'D=/tmp/x && cd $D/w && git push origin main', repo)
    assert out.get("permissionDecision") == "ask"
    assert "cannot resolve" in out.get("permissionDecisionReason", "") and "0 commits" not in out["permissionDecisionReason"]
    assert _pretool(env, f"cd {repo} && git push", repo) == "ask"  # a literal path still resolves


def test_a_push_with_dash_c_only_asks_about_that_repo_not_the_sessions_own(env, repo):
    other = env.tmp / "other"
    env.git(env.tmp, "clone", "-q", str(env.tmp / "remote.git"), str(other))
    _commit(env, other)
    reason = _pretool_out(env, f"stella push -C {other}", repo)["permissionDecisionReason"]
    assert reason.count("▲ PUSH") == 1 and "other → main" in reason and "dotfiles" not in reason


def _plan(env, repo):
    return env.run("push", "--plan", "-C", str(repo), cwd=env.tmp).stdout


def test_plan_prints_the_dropdown_question_with_the_diff_as_its_preview(env, repo):
    sha = _commit(env, repo)
    out = _plan(env, repo)
    assert f"question: Push dotfiles → main (1 commit, {sha[:7]})?" in out and "header: Push" in out
    assert '"Push"' in out and '"Defer"' in out and "--- preview ---" in out
    assert "· change" in out and "f.txt" in out and "+x" in out and "\x1b" not in out


def test_a_long_diff_is_cut_in_the_preview(env, repo):
    _commit(env, repo, text="line\n" * 300)
    out = _plan(env, repo)
    assert "more lines: `stella diff` prints them all" in out and out.count("\n") < 90


def _answer(env, repo, question, response, sid="S1"):
    return env.hook("posttool", {"tool_name": "AskUserQuestion", "session_id": sid, "cwd": str(repo),
                                 "tool_input": {"questions": [{"question": question}]}, "tool_response": response})


def _question(env, repo):
    return next(l for l in _plan(env, repo).splitlines() if l.strip().startswith("question:")).split("question: ", 1)[1]


@pytest.mark.parametrize("response", [
    {"answers": {"Q": "Push"}},
    'User has answered your questions: "Q"="Push" selected preview: x. You can now continue.',
    {"questions": [{"question": "Q", "options": [{"label": "Push"}, {"label": "Defer"}]}], "answers": {"Q": "Push"}},
])
def test_picking_push_approves_that_head_so_stella_push_is_not_asked_again(env, repo, response):
    _commit(env, repo)
    assert _pretool(env, f"stella push -C {repo}", env.tmp) == "ask"
    _answer(env, repo, _question(env, repo), response)
    assert _pretool(env, f"stella push -C {repo}", env.tmp) is None
    assert "Already approved" in _plan(env, repo)
    _commit(env, repo, text="y\n", msg="more")  # a new head is asked again
    assert _pretool(env, f"stella push -C {repo}", env.tmp) == "ask"


@pytest.mark.parametrize("response", [{"answers": {"Q": "Defer"}}, 'User has answered your questions: "Q"="Defer" selected', {"answers": {"Q": "Other text"}},
                                      {"questions": [{"options": [{"label": "Push"}]}], "answers": {}}])
def test_defer_or_anything_else_does_not_approve(env, repo, response):
    _commit(env, repo)
    _answer(env, repo, _question(env, repo), response)
    assert _pretool(env, f"stella push -C {repo}", env.tmp) == "ask"


def test_an_answer_to_some_other_question_approves_nothing(env, repo):
    _commit(env, repo)
    _answer(env, repo, "Push dotfiles → main (1 commit, abc1234)?", {"answers": {"Q": "Push"}})
    assert _pretool(env, f"stella push -C {repo}", env.tmp) == "ask"


def test_defer_is_remembered_as_asked_so_the_stop_hook_records_the_deferral(env, repo):
    _commit(env, repo)
    _answer(env, repo, _question(env, repo), {"answers": {"Q": "Defer"}})
    r = env.run("hook", "stop", input=json.dumps({"session_id": "S1", "cwd": str(repo), "last_assistant_message": "NEXT FOR YOU: x"}))
    assert "not pushed, deferred" in json.loads(r.stdout)["systemMessage"]
    assert len([e for e in env.events() if e["type"] == "push_deferred"]) == 1
