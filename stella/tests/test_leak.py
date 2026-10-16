"""Requirement 19: an extension's private terms never enter a protected repo."""

import json
import subprocess


def _protected(env, repo):
    env.extension(protect=[repo])
    return repo


def test_scan_rules(env):
    env.extension()
    assert env.run("leakcheck", "--text", "uses Zorblax tooling", check=False).returncode == 1
    assert env.run("leakcheck", "--text", "built for Zorblax Silicon", check=False).returncode == 0  # allow
    assert env.run("leakcheck", "--text", "see TKT-123", check=False).returncode == 1  # regex
    assert env.run("leakcheck", "--text", "acmex is fine lowercase", check=False).returncode == 0  # case-sensitive
    assert env.run("leakcheck", "--text", "ACMEX is not", check=False).returncode == 1
    assert env.run("leakcheck", "--text", "zorblaxian is another word", check=False).returncode == 0  # whole words


def test_write_guard_blocks_canary(env, repo):
    _protected(env, repo)
    data = {"tool_name": "Write", "tool_input": {"file_path": str(repo / "notes.md"), "content": "Zorblax setup"}, "cwd": str(repo)}
    out = env.hook("pretool", data)
    assert out["permissionDecision"] == "deny" and "Zorblax" in out["permissionDecisionReason"]
    data["tool_input"]["content"] = "generic setup"
    assert env.hook("pretool", data) is None
    edit = {"tool_name": "Edit", "tool_input": {"file_path": str(repo / "README.md"), "old_string": "hello", "new_string": "hi tkt-9"}, "cwd": str(repo)}
    assert env.hook("pretool", edit)["permissionDecision"] == "deny"
    bash = {"tool_name": "Bash", "tool_input": {"command": f"echo 'Zorblax' > {repo}/x.md"}, "cwd": "/tmp"}
    assert env.hook("pretool", bash)["permissionDecision"] == "deny"


def test_write_guard_ignores_unprotected_paths(env, repo):
    _protected(env, repo)
    data = {"tool_name": "Write", "tool_input": {"file_path": str(env.tmp / "elsewhere.md"), "content": "Zorblax"}, "cwd": "/tmp"}
    assert env.hook("pretool", data) is None


def test_commit_guard_blocks_canary_in_content_and_message(env, repo):
    _protected(env, repo)
    (repo / "a.md").write_text("talks about Zorblax\n")
    env.git(repo, "add", ".")
    r = env.git(repo, "commit", "-m", "add a", check=False)
    assert r.returncode != 0 and "LEAK GUARD" in r.stderr
    (repo / "a.md").write_text("generic\n")
    env.git(repo, "add", ".")
    r = env.git(repo, "commit", "-m", "fix for TKT-42", check=False)
    assert r.returncode != 0
    assert env.git(repo, "commit", "-q", "-m", "add a").returncode == 0


def test_commit_guard_blocks_when_denylist_missing(env, repo):
    ext = _protected(env, repo) and env.tmp / "ext-acme"
    (ext / "denylist.txt").unlink()
    (repo / "b.md").write_text("generic\n")
    env.git(repo, "add", ".")
    r = env.git(repo, "commit", "-m", "b", check=False)
    assert r.returncode != 0 and "denylist missing" in r.stderr


def test_push_refuses_a_leak_even_with_approval(env, repo):
    _protected(env, repo)
    # get a leak into history by skipping the commit hook, as a careless human might
    (repo / "c.md").write_text("Zorblax\n")
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "--no-verify", "-m", "c")
    env.say("A", "S, push dotfiles")
    r = env.run("push", "dotfiles", check=False)
    assert r.returncode != 0 and "leak" in r.stderr


def test_nightly_sweep_flags_canary(env, repo):
    _protected(env, repo)
    (repo / "d.md").write_text("Zorblax\n")
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "--no-verify", "-m", "d")
    env.run("nightly")
    assert "leak sweep" in env.run("attention").stdout
