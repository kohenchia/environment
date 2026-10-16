"""`pass-env --respawn` restarts every Claude window in the tmux server it can identify, in a private tmux
server: teams (whatever their window is called), hand-opened ones, then Stella herself, last."""

import json
import subprocess
import time

import pytest
from test_launch import fake_claude, tmux  # noqa: F401 - fixtures
from test_passenv import _launch, _lines, env_claude, needs_tmux  # noqa: F401 - fixtures

pytestmark = needs_tmux

OLD = """#!/bin/sh
sleep 60
"""
AGENTS = """#!/bin/sh
[ "$1" = agents ] && cat "{path}"
"""
SIDS = {"team": "aaaaaaaa-0000-4000-8000-000000000001", "hand": "aaaaaaaa-0000-4000-8000-000000000002",
        "stella": "aaaaaaaa-0000-4000-8000-000000000003", "ghost": "aaaaaaaa-0000-4000-8000-000000000004"}


class Server:
    def __init__(self, env, tmux):
        self.env, self.sock = env, tmux["TMUX"].split(",")[0]
        self.old = env.tmp / "claude-old"
        self.old.write_text(OLD)
        self.old.chmod(0o755)
        self.agents_json = env.tmp / "agents.json"
        self.agents_json.write_text("[]")
        q = env.tmp / "agents-fake"
        q.write_text(AGENTS.format(path=self.agents_json))
        q.chmod(0o755)
        env.write_config(claude_query_bin=str(q))
        (env.tmp / "transcripts" / "proj").mkdir(parents=True, exist_ok=True)

    def tmux(self, *a):
        return subprocess.run(["tmux", "-S", self.sock, *a], capture_output=True, text=True, check=True).stdout.strip()

    def window(self, name, *claude_args):
        """A window whose process is the stand-in Claude (`claude-old`); returns its pane's pid."""
        w = self.tmux("new-window", "-d", "-P", "-F", "#{window_id}", "-t", "work:", "-n", name,
                      f"exec {self.old} {' '.join(claude_args)}")
        return w, int(self.tmux("display-message", "-p", "-t", w, "#{pane_pid}"))

    def agents(self, entries):
        self.agents_json.write_text(json.dumps(entries))

    def transcript(self, sid):
        (self.env.tmp / "transcripts" / "proj" / f"{sid}.jsonl").write_text("{}\n")

    def names(self):
        return self.tmux("list-windows", "-t", "work", "-F", "#{window_name}").split()


@pytest.fixture
def srv(env, tmux, env_claude):  # noqa: F811
    return Server(env, tmux)


def test_every_identifiable_claude_window_is_restarted_and_stella_last(env, tmux, srv, env_claude):  # noqa: F811
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile")
    # a team, started by Stella; its window is then renamed, so the name no longer matches
    _launch(env, tmux, "t-ren")
    _lines(out / "passed.txt", 1)
    srv.tmux("rename-window", "-t", "work:t-ren", "something-else")
    env.hook("session-start", {"session_id": SIDS["team"], "source": "startup"}, env={"STELLA_TEAM": "t-ren"})
    srv.transcript(SIDS["team"])
    # a window the owner resumed by hand: no team in the ledger
    _, hand_pid = srv.window("pr-hand", "--name", "pr-hand", "--resume", SIDS["hand"])
    srv.transcript(SIDS["hand"])
    # Stella's own session, in a window that is not called `stella`
    _, stella_pid = srv.window("not-called-stella", "--name", "stella", "--agent", "stella:stella")
    srv.transcript(SIDS["stella"])
    # a plain shell window is no Claude window; one whose session cannot be read is skipped, with a reason
    srv.tmux("new-window", "-d", "-t", "work:", "-n", "just-a-shell", "sleep 60")
    srv.window("mystery", "--name", "mystery")
    # the team's pane pid, to describe it to `claude agents`
    team_pane = srv.tmux("list-panes", "-a", "-F", "#{window_name} #{pane_pid}")
    team_pid = int(next(line.split()[1] for line in team_pane.splitlines() if line.startswith("something-else")))
    srv.agents([
        {"pid": team_pid, "cwd": str(env.tmp), "name": "t-ren", "sessionId": SIDS["team"], "kind": "interactive"},
        {"pid": hand_pid, "cwd": str(env.tmp), "name": "pr-hand", "sessionId": SIDS["hand"], "kind": "interactive"},
        {"pid": stella_pid, "cwd": str(env.tmp), "name": "stella", "sessionId": SIDS["stella"], "kind": "interactive"},
    ])

    env.run("pass-env", "on")
    r = env.run("pass-env", "--respawn", env=tmux)
    assert "t-ren: restarted" in r.stdout
    assert "pr-hand: restarted" in r.stdout
    assert "mystery (mystery): skipped, no session id" in r.stdout
    assert "just-a-shell" not in r.stdout
    assert "Stella: restarting" in r.stdout and "in a moment" in r.stdout
    assert r.stdout.index("pr-hand: restarted") < r.stdout.index("Stella: restarting")

    # all three came back on the new token, each resuming its own conversation, Stella's last
    args = _lines(out / "args.txt", 4)  # [0] is the team's first launch
    resumed = [ln for ln in args[1:] if "--resume" in ln]
    sids = [ln.split("--resume ")[1].split()[0] for ln in resumed]
    assert len(sids) == 3 and set(sids[:2]) == {SIDS["team"], SIDS["hand"]}
    assert sids[-1] == SIDS["stella"]
    assert "--agent stella:stella" in resumed[-1]
    assert "--name pr-hand" in next(ln for ln in resumed if SIDS["hand"] in ln)
    assert _lines(out / "passed.txt", 4)[1:] == ["fromfile"] * 3


def test_a_named_team_alone_leaves_stella_and_hand_opened_windows(env, tmux, srv, env_claude):  # noqa: F811
    out, secrets = env_claude
    (secrets / "DEMO_TOKEN").write_text("fromfile")
    _launch(env, tmux, "t-one")
    _lines(out / "passed.txt", 1)
    env.hook("session-start", {"session_id": SIDS["team"], "source": "startup"}, env={"STELLA_TEAM": "t-one"})
    srv.transcript(SIDS["team"])
    srv.window("pr-hand", "--name", "pr-hand", "--resume", SIDS["hand"])
    env.run("pass-env", "on")
    r = env.run("pass-env", "--respawn", "--team", "t-one", "--team", "nope", env=tmux)
    assert "t-one: restarted" in r.stdout and "nope: no such team" in r.stdout and "pr-hand" not in r.stdout
    time.sleep(3)  # nothing is left for a helper to do
    assert len((out / "args.txt").read_text().splitlines()) == 2


def test_a_running_team_with_no_window_or_process_is_reported_gone(env, tmux, srv, env_claude):  # noqa: F811
    out, _ = env_claude
    _launch(env, tmux, "t-gone")
    _lines(out / "passed.txt", 1)
    srv.tmux("kill-window", "-t", "work:t-gone")
    r = env.run("pass-env", "--respawn", env=tmux)
    assert "t-gone: no window or process any more (gone)" in r.stdout
    assert "Stella: no session of hers found" in r.stdout


def test_respawn_self_command_restarts_only_her(env, tmux, srv, env_claude):  # noqa: F811
    out, _ = env_claude
    _, stella_pid = srv.window("elsewhere", "--agent", "stella:stella")
    srv.transcript(SIDS["stella"])
    srv.agents([{"pid": stella_pid, "cwd": str(env.tmp), "name": "stella", "sessionId": SIDS["stella"], "kind": "interactive"}])
    r = env.run("respawn-self", "Restarted.", env=tmux)
    assert "Stella: restarting in elsewhere" in r.stdout
    assert f"--resume {SIDS['stella']}" in _lines(out / "args.txt", 1)[0]
