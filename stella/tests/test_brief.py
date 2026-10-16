"""Requirement Q1: the ledger grows without bound; what enters context does not."""

import json
import datetime as dt


def _bulk(env, n):
    d = env.store / "ledger"
    d.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().astimezone().isoformat(timespec="seconds")
    with (d / f"{dt.date.today():%Y-%m}.jsonl").open("w") as f:
        for i in range(1, n + 1):
            if i % 4 == 0:
                ev = {"seq": i, "ts": ts, "type": "order", "kind": "instruction", "text": f"order {i}", "session": "x", "targets": []}
            elif i % 4 == 1:
                ev = {"seq": i, "ts": ts, "type": "decision", "text": f"decision {i}"}
            elif i % 4 == 2:
                ev = {"seq": i, "ts": ts, "type": "launch", "team": f"t{i}", "order": i + 2}
            else:
                ev = {"seq": i, "ts": ts, "type": "note", "text": f"note {i}"}
            f.write(json.dumps(ev) + "\n")
    (d / "seq").write_text(str(n))


def test_brief_is_capped_at_ten_thousand_events(env):
    _bulk(env, 10_000)
    out = env.run("brief").stdout.strip().splitlines()
    assert len(out) <= 60
    assert out[-1].startswith("+") and "stella orders" in out[-1]
    assert any(l.startswith("Open orders:") for l in out)


def test_delta_is_capped(env):
    _bulk(env, 500)
    out = env.say("fresh", "S, hello")
    delta = out.split("other sessions recorded:\n", 1)[1].split("\n\n")[0].splitlines()
    assert len(delta) <= 15 and "earlier events" in delta[-1]


def test_closed_orders_leave_the_brief(env):
    env.say("A", "S, rename the thing")
    assert "rename the thing" in env.run("brief").stdout
    env.run("close", "1")
    assert "rename the thing" not in env.run("brief").stdout
    assert "rename the thing" in env.run("search", "rename").stdout
