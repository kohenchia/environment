import datetime as dt

from stella import scheduler


def _at(h, m=0, day=15):
    return dt.datetime(2026, 10, day, h, m).astimezone()


def test_due_first_run_before_and_after_time(monkeypatch):
    assert scheduler.due(_at(19, 59), None) == [dt.date(2026, 10, 14)]
    assert scheduler.due(_at(20, 0), None) == [dt.date(2026, 10, 15)]


def test_due_nothing_when_done():
    assert scheduler.due(_at(21), "2026-10-15") == []
    assert scheduler.due(_at(9), "2026-10-14") == []


def test_due_catch_up_is_bounded():
    assert scheduler.due(_at(21), "2026-10-01") == [dt.date(2026, 10, d) for d in (13, 14, 15)]


def test_one_scheduler_at_a_time(env):
    import fcntl

    env.store.mkdir(exist_ok=True)
    lock = (env.store / "scheduler.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (env.store / "scheduler.pid").write_text("4242")
    assert "4242" in env.run("doctor", check=False).stdout
    assert env.run("scheduler", "--once").stdout.strip() == "nothing due"  # lock held: does nothing
    lock.close()


def test_daemon_start_and_stop(env):
    out = env.run("scheduler", "--ensure").stdout
    assert "Started the scheduler" in out
    assert "running" in env.run("scheduler", "--ensure").stdout
    assert "Stopped" in env.run("scheduler", "--stop").stdout


def test_session_start_runs_one_catch_up_when_overdue(env):
    import time

    hook_env = {"STELLA_NO_CATCHUP": "0"}
    env.hook("session-start", {"session_id": "S1", "source": "startup"}, env=hook_env)
    deadline = time.time() + 20
    while time.time() < deadline and not (env.store / "scheduler.json").exists():
        time.sleep(0.2)
    assert (env.store / "scheduler.json").exists()
    assert any("catch-up from a session" in e.get("text", "") for e in env.events())
    # a second session within the throttle window does not start another
    before = len(env.events())
    env.hook("session-start", {"session_id": "S2", "source": "startup"}, env=hook_env)
    time.sleep(1)
    assert len(env.events()) == before
