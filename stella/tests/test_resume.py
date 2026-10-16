"""The `claude --resume` picker hides a transcript that began as a headless run; Stella makes it listable."""

import json
import os
import time

from stella import resume

SID = "11111111-2222-4333-8444-555555555555"
CWD = "/work/monorepo"


def _transcript(env, origin="sdk-cli", title="pr-1-sam", sid=SID, age=3600):
    d = env.tmp / "transcripts" / "-proj"
    d.mkdir(parents=True, exist_ok=True)
    rows = [
        {"type": "user", "entrypoint": origin, "cwd": CWD, "sessionId": sid},
        {"type": "user", "entrypoint": "cli", "cwd": CWD, "sessionId": sid},
        {"type": "custom-title", "customTitle": title, "sessionId": sid},
    ]
    p = d / f"{sid}.jsonl"
    p.write_text("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows))
    old = time.time() - age
    os.utime(p, (old, old))
    return p


def test_a_headless_origin_is_rewritten_so_the_picker_lists_the_session(env, monkeypatch):
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    p = _transcript(env)
    assert resume.hidden(p)
    assert "now listed" in resume.make_listable(p)
    assert not resume.hidden(p)
    assert resume.make_listable(p) is None  # nothing left to change
    assert [json.loads(line)["type"] for line in p.read_text().splitlines()] == ["user", "user", "custom-title"]


def test_a_transcript_in_use_is_left_alone(env, monkeypatch):
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    p = _transcript(env, age=1)
    assert "in use" in resume.make_listable(p) and resume.hidden(p)


def test_an_interactive_session_is_not_touched(env, monkeypatch):
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    p = _transcript(env, origin="cli")
    before = p.read_bytes()
    assert resume.make_listable(p) is None and p.read_bytes() == before


def test_a_session_is_found_by_name_with_the_directory_it_started_in(env, monkeypatch):
    monkeypatch.setenv("STELLA_TRANSCRIPTS", str(env.tmp / "transcripts"))
    _transcript(env)
    f = resume.lookup("pr-1-sam")
    assert f and f.session_id == SID and f.cwd == CWD and f.title == "pr-1-sam"
    assert resume.lookup(SID).session_id == SID and resume.lookup("nope") is None


def test_fix_resume_by_name_from_the_cli(env):
    p = _transcript(env)
    out = env.run("fix-resume", "pr-1-sam").stdout
    assert "now listed" in out and not resume.hidden(p)
