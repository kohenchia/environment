"""Nightly jobs declared by an extension (`nightly = "nightly.toml"`): run at the nightly, last line to ledger + digest."""

import datetime as dt

from stella import daily


def _setup(env, monkeypatch, jobs: str):
    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_CONFIG", str(env.config))
    d = env.extension(extra='nightly = "nightly.toml"')
    (d / "nightly.toml").write_text(jobs)
    return d


def test_a_job_runs_and_its_last_line_is_the_result(env, monkeypatch):
    _setup(env, monkeypatch, '[[job]]\nname = "sweep"\ncmd = "echo noise; echo archived 2 reviews: a, b"\n')
    assert daily.run_extension_jobs() == [("acme: sweep", "archived 2 reviews: a, b")]
    assert any("nightly job acme: sweep: archived 2 reviews: a, b" in e.get("text", "") for e in env.events())


def test_a_failing_job_alerts_and_does_not_stop_the_next(env, monkeypatch):
    _setup(env, monkeypatch, '[[job]]\nname = "bad"\ncmd = "echo boom; exit 3"\n[[job]]\nname = "ok"\ncmd = "echo fine"\n')
    got = daily.run_extension_jobs()
    assert got == [("acme: bad", "FAILED (exit 3): boom"), ("acme: ok", "fine")]
    assert any(e.get("type") == "alert" and "acme: bad" in e.get("text", "") for e in env.events())


def test_a_timeout_is_a_failure(env, monkeypatch):
    _setup(env, monkeypatch, '[[job]]\nname = "slow"\ncmd = "sleep 5"\ntimeout = 1\n')
    assert daily.run_extension_jobs() == [("acme: slow", "FAILED (timeout)")]


def test_no_nightly_file_means_no_jobs(env, monkeypatch):
    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_CONFIG", str(env.config))
    env.extension()
    assert daily.run_extension_jobs() == []


def test_the_nightly_appends_the_jobs_to_the_morning_digest(env, monkeypatch):
    _setup(env, monkeypatch, '[[job]]\nname = "sweep"\ncmd = "echo archived 0 reviews: none"\n')
    win = daily.Window(dt.datetime(2026, 10, 16, tzinfo=dt.timezone.utc), dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc))
    morning = env.store / "digests" / f"{win.label + dt.timedelta(days=1):%Y-%m-%d}-morning.md"

    def fake_headless(prompt, log, **kw):
        morning.parent.mkdir(parents=True, exist_ok=True)
        morning.write_text("# Morning\n")
        return 0

    monkeypatch.setattr(daily, "headless", fake_headless)
    monkeypatch.setattr(daily, "digest", lambda w: env.store / "digest.md")
    monkeypatch.setattr(daily.leak, "rebuild", lambda: [])
    monkeypatch.setattr(daily.leak, "guard", lambda: type("G", (), {"configured": False})())
    monkeypatch.setattr("stella.resume.heal_known", lambda ids: [])
    report = daily.run_nightly(win)
    assert any(r.startswith("acme: sweep: archived 0 reviews") for r in report)
    assert morning.read_text() == "# Morning\n\n## Nightly jobs\n- acme: sweep: archived 0 reviews: none\n"
