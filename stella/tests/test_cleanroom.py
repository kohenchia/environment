"""Requirement 18: the core alone, on a machine with no extension, works."""


def test_core_runs_without_extensions(env):
    ctx = env.run("context").stdout
    assert "Knowledge map" not in ctx and "Teams" in ctx
    r = env.run("doctor", check=False)
    assert "extensions: none (core only)" in r.stdout
    env.say("A", "S, hello")
    assert env.run("brief").returncode == 0


def test_extension_unregister_returns_to_core(env):
    d = env.extension()
    assert "acme knowledge map" in env.run("context").stdout
    env.run("ext", "unregister", str(d))
    assert "acme knowledge map" not in env.run("context").stdout


def test_store_init(env):
    env.run("install", "--no-plugin", "--no-gate")
    for f in ("canon.md", "cases.toml", "priorities.md", ".git"):
        assert (env.store / f).exists()


def test_run_does_not_mistake_a_leftover_tab_for_stella(env):
    """A tab keeps its name after Claude exits; only a live process means she is running."""
    import json

    env.store.mkdir(exist_ok=True)
    (env.store / "stella-session.json").write_text(json.dumps({"session_id": "abandoned", "pid": 999999}))
    assert "not running" in env.run("doctor", check=False).stdout.split("Stella's session")[1].splitlines()[0]


def test_abandoned_session_is_not_resumed(env, monkeypatch):
    import os

    monkeypatch.setenv("STELLA_STORE", str(env.store))
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    from stella import run

    env.store.mkdir(exist_ok=True)
    (env.store / "stella-session.json").write_text('{"session_id": "abc"}')
    assert "--resume" not in run._argv(fresh=False)
    t = env.tmp / "transcripts" / "-home"
    t.mkdir(parents=True)
    (t / "abc.jsonl").write_text("{}\n")
    assert run._argv(fresh=False)[-2:] == ["--resume", "abc"]
    assert "--resume" not in run._argv(fresh=True)


def test_stop(env):
    env.run("scheduler", "--ensure")
    out = env.run("stop").stdout
    assert "not running" in out and "Stopped the scheduler" in out
