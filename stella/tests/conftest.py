"""Every test runs the real CLI in a subprocess against a throwaway home, store and config."""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "stella"


os.environ.setdefault("STELLA_NO_NOTIFY", "1")  # in-process calls too


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.home = tmp / "home"
        self.store = tmp / "store"
        self.config = tmp / "config"
        for p in (self.home, self.store, self.config, tmp / "tmux"):
            p.mkdir(parents=True, exist_ok=True)
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": str(self.home),
            "STELLA_STORE": str(self.store),
            "STELLA_CONFIG": str(self.config),
            "STELLA_TRANSCRIPTS": str(tmp / "transcripts"),
            "STELLA_NO_CATCHUP": "1",
            "STELLA_NO_NOTIFY": "1",
            # tmux's default socket lives here, so nothing a test runs can reach the owner's own server
            "TMUX_TMPDIR": str(tmp / "tmux"),
            "GIT_CONFIG_GLOBAL": str(tmp / "gitconfig"),
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
        }
        (tmp / "gitconfig").write_text("[init]\n\tdefaultBranch = main\n")
        self.write_config()

    def write_config(self, **extra):
        self._config = {**getattr(self, "_config", {"claude_bin": "false", "repos_dir": str(self.tmp / "repos")}), **extra}
        lines = [f"{k} = {json.dumps(v)}" for k, v in self._config.items()]
        (self.config / "config.toml").write_text("\n".join(lines) + "\n")

    def run(self, *args, input=None, env=None, check=True, cwd=None):
        r = subprocess.run([str(BIN), *args], input=input, capture_output=True, text=True,
                           env={**self.env, **(env or {})}, cwd=cwd or self.tmp)
        if check and r.returncode != 0:
            raise AssertionError(f"stella {' '.join(args)} failed ({r.returncode}):\n{r.stdout}\n{r.stderr}")
        return r

    def hook(self, event, data, env=None):
        r = self.run("hook", event, input=json.dumps(data), env=env)
        out = r.stdout.strip()
        return json.loads(out)["hookSpecificOutput"] if out else None

    def say(self, session, prompt, env=None, cwd="/tmp"):
        out = self.hook("prompt", {"prompt": prompt, "session_id": session, "cwd": cwd}, env=env)
        return (out or {}).get("additionalContext")

    def events(self):
        out = []
        for f in sorted((self.store / "ledger").glob("*.jsonl")):
            for line in f.read_text().splitlines():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return out

    def git(self, repo, *args, check=True):
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, env=self.env, check=check)

    def extension(self, name="acme", denylist="word:Zorblax\ncs:ACMEX\nre:tkt-\\d+\nallow:Zorblax Silicon\n",
                  protect=(), teams="", required=True, model_review=False, extra=""):
        d = self.tmp / f"ext-{name}"
        d.mkdir(exist_ok=True)
        (d / "denylist.txt").write_text(denylist)
        prot = ", ".join(json.dumps(str(p)) for p in protect)
        (d / "stella-extension.toml").write_text(textwrap.dedent(f"""\
            name = "{name}"
            contract = 1
            teams = "teams.toml"
            knowledge = "knowledge.md"
            {extra}
            [leak_guard]
            protect = [{prot}]
            denylist = "denylist.txt"
            required = {str(required).lower()}
            model_review = {str(model_review).lower()}
            """))
        (d / "teams.toml").write_text(teams)
        (d / "knowledge.md").write_text(f"{name} knowledge map\n")
        self.run("ext", "register", str(d))
        return d


@pytest.fixture
def env(tmp_path):
    return Env(tmp_path)


@pytest.fixture
def repo(env):
    """A guarded repo with a bare remote, one pushed commit, and `stella gate install` run on it."""
    remote = env.tmp / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=env.env)
    r = env.tmp / "repos" / "dotfiles"
    r.mkdir(parents=True)
    env.git(r, "init", "-q")
    (r / "README.md").write_text("hello\n")
    env.git(r, "add", ".")
    env.git(r, "commit", "-q", "-m", "init")
    env.git(r, "remote", "add", "origin", str(remote))
    env.git(r, "push", "-q", "origin", "main")
    env.write_config(guarded_repos=[str(r)])
    env.run("gate", "install", "dotfiles")
    return r
