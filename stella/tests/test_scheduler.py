import datetime as dt

from stella import scheduler


import json
import time

import pytest

from stella import daily


def _tz(monkeypatch, name):
    monkeypatch.setenv("TZ", name)
    time.tzset()


@pytest.fixture(autouse=True)
def _restore_tz():
    yield
    time.tzset()


@pytest.fixture(autouse=True)
def daily_time(monkeypatch):
    """Not the owner's real config: the schedule under test is the core default unless a test changes it."""
    from stella.config import Settings

    monkeypatch.setattr(scheduler, "settings", lambda: Settings())
    monkeypatch.setattr(daily.extensions, "load", lambda: [])


LA, TOKYO = "America/Los_Angeles", "Asia/Tokyo"


def _at(h, m=0, day=15):
    return dt.datetime(2026, 10, day, h, m).astimezone()


def _local(day, h=0, m=0):
    return dt.datetime(2026, 10, day, h, m).astimezone()


def _cut(at, tz):
    return {"at": at.isoformat(), "tz": tz}


def _tiles(wins, start, end):
    assert wins[0].start == start and wins[-1].end == end
    assert all(a.end == b.start for a, b in zip(wins, wins[1:]))  # nothing doubled, no hour dropped
    assert all(w.start < w.end for w in wins)


def test_midnight_trigger_and_nothing_before(monkeypatch):
    _tz(monkeypatch, LA)
    last = _cut(_local(14), LA)  # the window ending Oct 14 00:00 was already run
    assert scheduler.due(_at(23, 59, 14), _cut(_local(14), LA)) == []  # nothing before midnight
    assert scheduler.due(_at(9, 0, 14), last) == []
    (w,) = scheduler.due(_at(0, 0, 15), _cut(_local(14), LA))  # at midnight: the day that just ended
    assert (w.start, w.end) == (_local(14), _local(15))
    assert w.label == dt.date(2026, 10, 14)


def test_daily_time_delays_the_run_not_the_cutoff(monkeypatch):
    from stella.config import Settings

    _tz(monkeypatch, LA)
    monkeypatch.setattr(scheduler, "settings", lambda: Settings(daily_time="02:00"))
    last = _cut(_local(14), LA)
    assert scheduler.due(_at(1, 30, 15), last) == []
    (w,) = scheduler.due(_at(2, 0, 15), last)
    assert w.end == _local(15)


def test_first_run_is_the_previous_local_day(monkeypatch):
    _tz(monkeypatch, LA)
    (w,) = scheduler.due(_at(8, 0, 15), None)
    assert (w.start, w.end) == (_local(14), _local(15))
    assert w.label == dt.date(2026, 10, 14)


def test_catch_up_after_sleep_one_run_per_missed_day(monkeypatch):
    _tz(monkeypatch, LA)
    wins = scheduler.due(_at(9, 0, 17), _cut(_local(14), LA))  # asleep over two midnights
    assert [w.label for w in wins] == [dt.date(2026, 10, d) for d in (14, 15, 16)]
    _tiles(wins, _local(14), _local(17))


def test_catch_up_is_bounded_to_three_days(monkeypatch):
    _tz(monkeypatch, LA)
    wins = scheduler.due(_at(9, 0, 17), _cut(_local(1), LA))
    assert [w.label for w in wins] == [dt.date(2026, 10, d) for d in (14, 15, 16)]


def test_legacy_last_done_counts_as_that_days_end(monkeypatch):
    _tz(monkeypatch, LA)
    lc = scheduler.last_cutoff({"last_done": "2026-10-14"})
    (w,) = scheduler.due(_at(9, 0, 16), lc)
    assert (w.start, w.end) == (_local(15), _local(16))


def test_tz_change_eastward_windows_tile_and_split(monkeypatch):
    # last cutoff: Oct 15 00:00 in Los Angeles. Now: Oct 18 08:00 in Tokyo, two days later.
    _tz(monkeypatch, LA)
    start = _local(15)
    _tz(monkeypatch, TOKYO)
    now = _local(18, 8)
    wins = scheduler.due(now, _cut(start, LA))
    end = _local(18)
    _tiles(wins, start, end)
    assert [w.label for w in wins] == [dt.date(2026, 10, d) for d in (15, 16, 17)]
    assert wins[0].end == _local(16) and wins[0].end - wins[0].start == dt.timedelta(hours=8)
    assert sum((w.end - w.start for w in wins), dt.timedelta()) == end - start
    assert all(w.zone == TOKYO for w in wins)


def test_tz_change_westward_single_window_ends_on_new_midnight(monkeypatch):
    # last cutoff: Oct 15 00:00 in Tokyo. Now: Oct 15 10:00 in Los Angeles.
    _tz(monkeypatch, TOKYO)
    start = _local(15)
    _tz(monkeypatch, LA)
    wins = scheduler.due(_local(15, 10), _cut(start, TOKYO))
    (w,) = wins
    assert (w.start, w.end) == (start, _local(15))
    assert w.end - w.start == dt.timedelta(hours=16)
    assert w.label == dt.date(2026, 10, 14)
    # the next midnight continues exactly where this one stopped
    (nxt,) = scheduler.due(_local(16, 1), _cut(w.end, LA))
    assert nxt.start == w.end and nxt.end == _local(16)


def test_tz_change_that_leaves_a_tiny_or_negative_window_is_skipped(monkeypatch):
    _tz(monkeypatch, "Asia/Kathmandu")  # UTC+5:45
    start = _local(15)
    _tz(monkeypatch, "Asia/Kolkata")  # UTC+5:30: its midnight is only 15 minutes after the stored one
    assert scheduler.due(_local(15, 9), _cut(start, "Asia/Kathmandu")) == []
    # ... and the next midnight picks it up, still starting at the stored cutoff
    (w,) = scheduler.due(_local(16, 1), _cut(start, "Asia/Kathmandu"))
    assert w.start == start and w.end == _local(16)
    _tz(monkeypatch, "America/Denver")  # moving west: today's midnight is before the stored cutoff
    _tz(monkeypatch, LA)
    lat = _local(15)
    _tz(monkeypatch, "America/Denver")
    assert scheduler.due(dt.datetime(2026, 10, 15, 0, 30).astimezone(), _cut(lat, LA)) == []


def test_label_is_the_date_of_end_minus_one_second(monkeypatch):
    _tz(monkeypatch, TOKYO)
    w = daily.Window(_local(15), _local(16))
    assert w.label == dt.date(2026, 10, 15)
    _tz(monkeypatch, LA)
    w = daily.Window(_local(15), _local(16))
    assert w.label == dt.date(2026, 10, 15)


def _tick_env(env, monkeypatch, claude_log):
    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_CONFIG", str(env.config))
    monkeypatch.setattr(daily, "run_daily", lambda w, claude=None: claude_log.append(("daily", w)) or 0)
    monkeypatch.setattr(daily, "run_nightly", lambda w, claude=None: claude_log.append(("nightly", w)) or [])


def test_tick_stores_the_cutoff_and_runs_nothing_twice(env, monkeypatch):
    _tz(monkeypatch, LA)
    ran = []
    _tick_env(env, monkeypatch, ran)
    assert scheduler.tick(_at(0, 5, 15)) != []
    saved = json.loads((env.store / "scheduler.json").read_text())["last_cutoff"]
    assert dt.datetime.fromisoformat(saved["at"]) == _local(15) and saved["tz"] == LA
    assert [k for k, _ in ran] == ["daily", "nightly"]
    assert scheduler.tick(_at(23, 0, 15)) == []  # nothing before the next midnight
    assert len(ran) == 2


def test_tick_catch_up_runs_each_missed_day_and_advances_the_cutoff(env, monkeypatch):
    _tz(monkeypatch, LA)
    ran = []
    _tick_env(env, monkeypatch, ran)
    env.store.mkdir(exist_ok=True)
    (env.store / "scheduler.json").write_text(json.dumps({"last_cutoff": _cut(_local(13), LA)}))
    assert len(scheduler.tick(_at(7, 0, 16))) == 3
    saved = json.loads((env.store / "scheduler.json").read_text())["last_cutoff"]
    assert dt.datetime.fromisoformat(saved["at"]) == _local(16)


def test_window_filter_excludes_events_past_the_cutoff(env, monkeypatch):
    _tz(monkeypatch, LA)
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    proj = env.tmp / "transcripts" / "p"
    proj.mkdir(parents=True)

    def ev(when, text):
        return json.dumps({"type": "user", "timestamp": when.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
                           "cwd": "/x", "message": {"content": text}})

    (proj / "a.jsonl").write_text("\n".join([
        ev(_local(14, 23, 59), "before the cutoff"),
        ev(_local(15, 0, 0), "exactly at the cutoff"),
        ev(_local(15, 0, 1), "after the cutoff"),
    ]) + "\n")
    (proj / "b.jsonl").write_text(ev(_local(15, 3), "only after") + "\n")
    ss = daily.sessions_on(_local(14), _local(15))
    assert len(ss) == 1  # b is entirely the next run's
    assert [t for _, t in ss[0]["prompts"]] == ["before the cutoff"]
    nxt = daily.sessions_on(_local(15), _local(16))
    assert sorted(t for s in nxt for _, t in s["prompts"]) == ["after the cutoff", "exactly at the cutoff", "only after"]


def test_prompt_states_window_zone_and_completed_only(env, monkeypatch):
    _tz(monkeypatch, LA)
    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_CONFIG", str(env.config))
    w = daily.Window(_local(14), _local(15), LA)
    text = daily._daily_prompt(w, env.tmp / "d.md")
    assert "2026-10-14 00:00 PDT" in text and "2026-10-15 00:00 PDT" in text and LA in text
    assert "COMPLETED" in text and "in progress" in text


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
