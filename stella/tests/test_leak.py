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


def test_commit_guard_survives_reinstalling_the_gate(env, repo):
    _protected(env, repo)
    env.run("gate", "install", "dotfiles")  # the migration off the old push gate keeps the commit hooks
    (repo / "c.md").write_text("Zorblax\n")
    env.git(repo, "add", ".")
    r = env.git(repo, "commit", "-m", "c", check=False)
    assert r.returncode != 0 and "LEAK GUARD" in r.stderr
    assert env.git(repo, "log", "-1", "--format=%s").stdout.strip() == "init"


def test_nightly_sweep_flags_canary(env, repo):
    _protected(env, repo)
    (repo / "d.md").write_text("Zorblax\n")
    env.git(repo, "add", ".")
    env.git(repo, "commit", "-q", "--no-verify", "-m", "d")
    env.run("nightly")
    assert "leak sweep" in env.run("attention").stdout


def _bash(env, cmd, cwd="/tmp"):
    return env.hook("pretool", {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": cwd})


def _denied(out):
    return bool(out) and out["permissionDecision"] == "deny"


def test_reads_with_denylisted_words_are_never_blocked(env, repo):
    _protected(env, repo)
    (repo / "Zorblax-notes.md").write_text("x\n")
    for cmd in [
        f"grep -rn Zorblax {repo}",
        f"cat {repo}/Zorblax-notes.md",
        f"ls {repo}/Zorblax-notes.md",
        f"git -C {repo} log --grep=Zorblax",
        f"git -C {repo} show HEAD:Zorblax-notes.md",
        f"find {repo} -name 'Zorblax*' | head -3 | wc -l",
        f"sed -n 1,5p {repo}/Zorblax-notes.md",
        f"git -C {repo} tag -l 'Zorblax*'",
        "cd ~ && grep -rn Zorblax . | head",
        f"cd {repo} && grep Zorblax a.md && head -3 Zorblax.md && tail -2 x",
        f"echo Zorblax | grep Zorblax",
        "stella fleet Zorblax",
    ]:
        assert not _denied(_bash(env, cmd)), cmd
        assert not _denied(_bash(env, cmd, cwd=str(repo))), cmd
    read = {"tool_name": "Read", "tool_input": {"file_path": str(repo / "Zorblax-notes.md")}, "cwd": str(repo)}
    assert env.hook("pretool", read) is None


def test_writes_into_the_protected_repo_are_scanned(env, repo):
    _protected(env, repo)
    for cmd in [
        f"echo 'Zorblax' > {repo}/x.md",
        f"echo Zorblax >> {repo}/x.md",
        f"printf 'Zorblax' | tee {repo}/x.md",
        f"cat > {repo}/x.md <<'EOF'\nsome Zorblax\nEOF",
        f"cat <<EOF | tee {repo}/x.md\nZorblax\nEOF",
        f"sed -i 's/a/Zorblax/' {repo}/README.md",
        f"cp a.md {repo}/Zorblax.md",
        f"git -C {repo} commit -m 'Zorblax'",
        f"python3 -c \"open('{repo}/x.md','w').write('Zorblax')\"",
        f"bash -c \"echo Zorblax > {repo}/x.md\"",
        f"grep -r a . | tee {repo}/Zorblax.txt",  # a pipeline mixing a read and a write is a write
        f"cd {repo} && echo Zorblax > x.md",
    ]:
        out = _bash(env, cmd)
        assert _denied(out), cmd
        assert str(repo) in out["permissionDecisionReason"] or "x.md" in out["permissionDecisionReason"], cmd
    assert not _denied(_bash(env, f"echo generic > {repo}/x.md"))
    assert not _denied(_bash(env, f"cat > {repo}/x.md <<EOF\ngeneric\nEOF"))
    assert not _denied(_bash(env, f"git -C {repo} commit -m 'generic'"))


def test_writes_elsewhere_may_mention_denylisted_words(env, repo):
    _protected(env, repo)
    other = env.tmp / "vault"
    other.mkdir()
    for cmd in [
        f"echo Zorblax > {other}/n.md",
        f"cat > /tmp/zorb.md <<EOF\nZorblax\nEOF",
        f"grep Zorblax {repo}/a.md | tee {other}/hits.txt",
        f"cp {repo}/Zorblax.md {other}/Zorblax.md",
        f"sed -i s/a/Zorblax/ {other}/f",
        f"git -C {other} commit -m Zorblax",
        f"echo Zorblax > ~/.local/share/zz-never-written.txt",
        f"cd {other} && echo Zorblax > n.md",
        f"mkdir -p {other}/Zorblax",
    ]:
        assert not _denied(_bash(env, cmd, cwd=str(repo))), cmd


def test_write_tool_resolves_relative_paths(env, repo):
    _protected(env, repo)
    data = {"tool_name": "Write", "tool_input": {"file_path": "n.md", "content": "Zorblax"}, "cwd": str(repo)}
    out = env.hook("pretool", data)
    assert _denied(out) and "n.md" in out["permissionDecisionReason"]
