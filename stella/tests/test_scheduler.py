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
