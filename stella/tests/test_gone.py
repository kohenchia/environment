"""A team whose window and process are gone is treated as ended: the sweep records it when it is clean,
lists it with the reason when it is not, and `fleet` / `pass-env status` hide wrapped-up teams and say "gone"."""

import subprocess
import sys

import pytest
from test_launch import fake_claude, tmux  # noqa: F401 - fixtures
from test_passenv import _launch, _lines, env_claude, needs_tmux  # noqa: F401 - fixtures
from test_wrapup import _repo, _types, led  # noqa: F401 - fixtures

from conftest import ROOT

pytestmark = needs_tmux


def _gone_team(led, name, dir, status="running"):
    """A team the ledger says is `status`, opened in a tmux window that no longer exists."""
    led.team(name=name, dir=str(dir), done_ago=None, window="@77")
    if status == "needs-you":
        led.add("report", ago=5, team=name, text="which database?", needs_you=True)
    elif status == "ended":
        led.add("ended", ago=5, team=name, reason="other")


def _fleet(env, tmux):  # noqa: F811
    return env.run("fleet", env=tmux).stdout


@pytest.mark.parametrize("status", ["running", "needs-you", "ended"])
def test_clean_gone_team_is_wrapped_up_unless_it_needs_you(env, led, tmux, status):  # noqa: F811
    r = _repo(env)
    _gone_team(led, "vanished", r, status)
    out = env.run("sweep", env=tmux).stdout
    if status == "needs-you":
        assert "kept open vanished (gone): needs-you: which database?" in out
        assert "wrapped_up" not in _types(env)
    else:
        assert "wrapped up vanished" in out and "window and process gone" in out
        ev = [e for e in env.events() if e["type"] == "wrapped_up"][0]
        assert f"(the ledger still says {status})" in " ".join(ev["checked"])
        assert "vanished" not in _fleet(env, tmux)
        assert "vanished" not in env.run("pass-env", env=tmux).stdout


def test_gone_team_with_uncommitted_work_is_listed_with_the_reason_and_not_discarded(env, led, tmux, env_claude):  # noqa: F811
    r = _repo(env)
    (r / "skill.md").write_text("unsaved idea\n")
    _gone_team(led, "model-routing-2", r, "needs-you")
    out = env.run("sweep", env=tmux).stdout
    assert "kept open model-routing-2 (gone)" in out
    assert (r / "skill.md").read_text() == "unsaved idea\n"
    brief = env.run("brief", env=tmux).stdout
    assert "Finished, not wrapped up" in brief and "model-routing-2 (gone" in brief
    row = next(line for line in _fleet(env, tmux).splitlines() if line.startswith("model-routing-2"))
    assert "needs-you, gone" in row and row.split()[-3:-1] != ["?"]
    pe = next(line for line in env.run("pass-env", env=tmux).stdout.splitlines() if "model-routing-2" in line)
    assert pe.split()[-1] == "gone"


def test_gone_team_with_unpushed_commits_is_kept(env, led, tmux):  # noqa: F811
    r = _repo(env)
    (r / "b.txt").write_text("b\n")
    env.git(r, "add", ".")
    env.git(r, "commit", "-q", "-m", "local only")
    _gone_team(led, "unpushed", r)
    assert "1 unpushed commit" in env.run("sweep", env=tmux).stdout


def test_a_live_team_is_not_gone_even_when_its_window_was_renamed(env, led, tmux, env_claude):  # noqa: F811
    out, _ = env_claude
    _launch(env, tmux, "alive")
    _lines(out / "passed.txt", 1)
    sock = tmux["TMUX"].split(",")[0]
    subprocess.run(["tmux", "-S", sock, "rename-window", "-t", "work:alive", "other-name"], check=True)
    swept = env.run("sweep", env=tmux).stdout
    assert "alive" not in swept
    row = next(line for line in _fleet(env, tmux).splitlines() if line.startswith("alive"))
    assert "gone" not in row


def test_nothing_is_gone_when_tmux_cannot_be_reached(env, led):
    r = _repo(env)
    _gone_team(led, "vanished", r)
    out = env.run("sweep").stdout  # no tmux server in this environment: it cannot be told
    assert "vanished" not in out and "wrapped_up" not in _types(env)


def test_the_scheduler_records_gone_teams_even_with_auto_wrapup_off(env, led, tmux):  # noqa: F811
    r = _repo(env)
    _gone_team(led, "vanished", r)
    subprocess.run([sys.executable, "-c", "from stella import scheduler; scheduler.sweep_wrapup()"], check=True,
                   env={**env.env, **tmux, "PYTHONPATH": str(ROOT / "src")}, capture_output=True)
    assert "wrapped_up" in _types(env)


def test_a_window_left_holding_the_owners_shell_is_not_gone(env, led, tmux):  # noqa: F811
    r = _repo(env)
    _gone_team(led, "shelled", r)
    sock = tmux["TMUX"].split(",")[0]
    subprocess.run(["tmux", "-S", sock, "new-window", "-d", "-t", "work:", "-n", "shelled", "sleep 60"], check=True)
    assert "shelled" not in env.run("sweep", env=tmux).stdout
    assert "wrapped_up" not in _types(env)
