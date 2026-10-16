import json
import multiprocessing as mp
import os


def _worker(store, n):
    os.environ["STELLA_STORE"] = store
    from stella import ledger

    for i in range(n):
        ledger.append("note", text=f"{os.getpid()}-{i}")


def test_concurrent_appends_are_totally_ordered(tmp_path):
    store = str(tmp_path / "store")
    ps = [mp.Process(target=_worker, args=(store, 100)) for _ in range(4)]
    for p in ps:
        p.start()
    for p in ps:
        p.join()
    lines = [json.loads(l) for f in (tmp_path / "store" / "ledger").glob("*.jsonl") for l in f.read_text().splitlines()]
    assert sorted(e["seq"] for e in lines) == list(range(1, 401))


def test_malformed_line_is_skipped(env):
    env.run("note", "one")
    f = next((env.store / "ledger").glob("*.jsonl"))
    with f.open("a") as fh:
        fh.write("{not json\n")
    env.run("note", "two")
    assert [e["text"] for e in env.events() if e.get("text")] == ["one", "two"]
    assert "Nothing open" in env.run("brief").stdout


def test_hook_only_events_cannot_be_logged_by_cli(env):
    r = env.run("log", "--type", "order")
    assert r.returncode == 0  # reading is fine; there is no CLI that writes orders
    assert "order" not in env.run("--help").stdout.split("{")[1].split("}")[0].split(",")
