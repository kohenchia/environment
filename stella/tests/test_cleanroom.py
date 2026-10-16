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
