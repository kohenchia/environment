"""Requirement 12: what one session is told, every session sees. Driven through the hook, no model."""


def test_three_sessions_conflict_and_recall(env):
    a = env.say("A", "S, include the deploy step in the widgets#2400 review")
    assert "Recorded as ledger #1" in a
    b = env.say("B", "S, skip the deploy step for 2400")
    assert "#1 order in" in b  # B's delta shows A's order
    assert "POSSIBLE CONFLICT" in b and "#2400" in b
    env.run("decide", "Skip the deploy step for 2400", "--supersedes", "1")
    c = env.say("C", "S, what did I ask for 2400?")
    assert "#1 order" in c and "#2 order" in c and "decision" in c
    assert "POSSIBLE CONFLICT" not in c  # a question is not an order
    orders = env.run("orders").stdout
    assert "#1" not in orders and "#2" in orders  # #1 superseded


def test_delta_only_shows_what_is_new(env):
    env.say("A", "S, do the first thing")
    first = env.say("B", "S, hello")
    assert "do the first thing" in first
    again = env.say("B", "S, hello again")
    assert "do the first thing" not in again


def test_handback_after_addressed_turn(env):
    env.say("A", "S, what's running?")
    out = env.hook("prompt", {"prompt": "now fix the test", "session_id": "A", "cwd": "/tmp"})
    assert "not addressed to Stella" in out["additionalContext"]
    assert env.hook("prompt", {"prompt": "and lint it", "session_id": "A", "cwd": "/tmp"}) is None
    assert [e["type"] for e in env.events()] == ["order"]  # plain turns are not orders


def test_never_addressed_session_gets_nothing(env):
    assert env.hook("prompt", {"prompt": "fix the build", "session_id": "Z", "cwd": "/tmp"}) is None
    assert env.events() == []


def test_stellas_own_session_treats_every_message_as_addressed(env):
    own = {"STELLA_SELF": "1"}
    start = env.hook("session-start", {"session_id": "H", "source": "startup"}, env=own)
    assert "This is your own session, Stella" in start["additionalContext"]
    out = env.say("H", "review the deploy script", env=own)
    assert "Recorded as ledger #1" in out
    assert env.events()[0]["session_label"] == "stella"


def test_first_turn_gets_context_then_short_reminder(env):
    first = env.say("A", "S, hi")
    assert "Stella context" in first
    second = env.say("A", "S, hi again")
    assert "Stella context" not in second and "addressed to you, Stella" in second


def test_team_window_direct_messages_are_recorded(env):
    team = {"STELLA_TEAM": "build-x"}
    env.hook("prompt", {"prompt": "/stella:build x", "session_id": "T", "cwd": "/tmp"}, env=team)  # launch prompt
    env.hook("prompt", {"prompt": "use sqlite instead", "session_id": "T", "cwd": "/tmp"}, env=team)
    env.hook("prompt", {"prompt": "[Stella] relayed", "session_id": "T", "cwd": "/tmp"}, env=team)
    direct = [e for e in env.events() if e["type"] == "direct"]
    assert [d["text"] for d in direct] == ["use sqlite instead"]


def test_ledger_failure_is_loud(env):
    (env.store / "ledger").mkdir(parents=True)
    (env.store / "ledger" / ".lock").mkdir()  # makes the lock unopenable
    out = env.say("A", "S, do it")
    assert "LEDGER UNAVAILABLE" in out
