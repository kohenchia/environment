#!/usr/bin/env python3
"""A fake Claude daemon and a fake herdr, one script, for tests. Tests put `claude` and `herdr` wrappers on PATH that
exec `python3 fake_daemon.py claude|herdr ...`, with HOME pointing at a temp directory and FAKE_WORLD at a JSON file.

What it models (each rule comes from the logs of the real daemon, see the tok investigation, 2026-10-20):
  - `claude respawn ID` keeps the job id, session id, flags and transcript; it kills the worker, so every
    `claude attach ID` in a pane ends (the pane falls back to its shell), and starts a new worker
  - `claude respawn ID` on a job without a worker revives it
  - `claude --bg --resume SID [flags] -- prompt` continues the job in place only when it has no worker and no
    flags are given; otherwise it FORKS: a new job id and session id, the old record stays under the same name
  - `claude stop ID` kills the worker and marks the job stopped; `claude rm ID` deletes the job record
  - typing `claude attach ID` into a pane that is at a shell starts the attach, and revives a job without a worker
  - the daemon starts every worker through FAKE_WRAPPER (a command line, like the process wrapper the real daemon is
    given) when it is set; the wrapper receives `/x/claude --resume TRANSCRIPT FLAGS...` (or `--session-id ID ...`) and
    FAKE_WORKER_PID, FAKE_REPL_PID, FAKE_SESSION_ID in its environment
  - files the real tools read: ~/.claude/jobs/ID/state.json and ~/.claude/daemon/roster.json
Test controls: `fake_daemon.py ctl ...` (see CTL below). Everything it is asked is appended to FAKE_DIR/calls.log.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

WORLD = Path(os.environ["FAKE_WORLD"])
HOME = Path(os.environ["HOME"])
SHELL_PROMPT = "kohen@mac ~ %"


def load() -> dict:
    return json.loads(WORLD.read_text())


def save(w: dict) -> None:
    WORLD.write_text(json.dumps(w, indent=1))
    render(w)


def log(line: str) -> None:
    with open(WORLD.with_name("calls.log"), "a") as f:
        f.write(line + "\n")


def lstart() -> str:
    return time.strftime("%a %b %e %H:%M:%S %Y")


def render(w: dict) -> None:
    """Write the files the real tools read."""
    jobs = HOME / ".claude/jobs"
    for jid, j in w["jobs"].items():
        d = jobs / jid
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(json.dumps({
            "state": j["state"], "tempo": j.get("tempo", "idle"), "name": j["name"], "sessionId": j["sessionId"],
            "resumeSessionId": j["sessionId"], "daemonShort": jid, "template": j.get("template", "bg"),
            "respawnFlags": json.dumps(j["flags"]), "cwd": j["cwd"], "createdAt": j["createdAt"],
            "inFlight": j.get("inFlight", {"tasks": 0, "queued": 0, "kinds": []}),
            "linkScanPath": j["transcript"], "backend": "daemon"}))
    for d in jobs.iterdir() if jobs.exists() else []:
        if d.is_dir() and d.name not in w["jobs"] and (d / "state.json").exists():
            (d / "state.json").unlink()
            d.rmdir()
    (HOME / ".claude/daemon").mkdir(parents=True, exist_ok=True)
    (HOME / ".claude/daemon/roster.json").write_text(json.dumps({"proto": 1, "workers": {
        jid: {**wk, "sessionId": w["jobs"][jid]["sessionId"], "cwd": w["jobs"][jid]["cwd"]}
        for jid, wk in w["workers"].items() if jid in w["jobs"]}}))


def tick(w: dict) -> None:
    """An attach client whose worker was killed keeps running for `late_exit` seconds (the real one exits 0.3-0.5 s late)."""
    for p in w["panes"].values():
        if p.get("exit_at") and time.time() >= p["exit_at"]:
            p.pop("exit_at")
            end_attach(p, p.pop("exit_job", ""))


def end_attach(p: dict, job: str) -> None:
    p["fg"] = "shell"
    p.pop("attach_pid", None)
    p["screen"] = [f"Session {job} has exited.", SHELL_PROMPT]


def kill_worker(w: dict, jid: str) -> None:
    w["workers"].pop(jid, None)
    for p in w["panes"].values():
        if p["fg"] == f"attach:{jid}":
            late = w.get("late_exit", 0)
            if late:
                p["exit_at"] = time.time() + late
                p["exit_job"] = jid
            else:
                end_attach(p, jid)


def spawn(w: dict, jid: str, launch: list[str]) -> None:
    w["pid"] += 2
    pid, repl = w["pid"], w["pid"] + 1
    w["workers"][jid] = {"pid": pid, "replPid": repl, "procStart": lstart()}
    j = w["jobs"][jid]
    j["state"] = j["state"] if j["state"] in ("working", "blocked") else "done"
    save(w)
    wrapper = os.environ.get("FAKE_WRAPPER")
    if wrapper:
        env = dict(os.environ, FAKE_WORKER_PID=str(pid), FAKE_REPL_PID=str(repl), FAKE_SESSION_ID=j["sessionId"])
        stale = w.get("stale_state", {})
        if jid in stale:  # a spawn that read the state directory before it was changed (a race)
            env["CLAUDE_TOKEN_STATE"] = stale.pop(jid)
            save(w)
        subprocess.run(shlex.split(wrapper) + ["/x/claude", *launch], env=env, capture_output=True, text=True)


def rows(w: dict, all_: bool) -> list[dict]:
    out = []
    for jid, j in w["jobs"].items():
        alive = jid in w["workers"]
        if all_ or alive or j["state"] in ("working", "blocked"):
            out.append({"kind": "background", "id": jid, "sessionId": j["sessionId"], "name": j["name"],
                        "state": j["state"], "cwd": j["cwd"], **({"pid": w["workers"][jid]["pid"]} if alive else {})})
    return out


def new_job(w: dict, name: str, flags: list[str], cwd: str, session_from: str | None = None) -> str:
    w["next"] += 1
    jid = f"{w['next']:08x}"
    sid = f"{jid}-0000-4000-8000-000000000000"
    transcript = HOME / ".claude/projects/p" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    if session_from:
        old = w["jobs"][session_from]
        transcript.write_text(Path(old["transcript"]).read_text() if Path(old["transcript"]).exists() else "")
    else:
        transcript.write_text("")
    w["jobs"][jid] = {"sessionId": sid, "name": name, "state": "blocked", "tempo": "idle", "cwd": cwd, "flags": flags,
                      "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + w["next"])),
                      "transcript": str(transcript), "template": "bg"}
    return jid


def claude(argv: list[str]) -> int:
    w = load()
    log("claude " + " ".join(argv))
    if argv[:1] == ["attach"]:  # a foreground attach: the tests do not need it to show anything
        return 0
    if argv[:1] == ["agents"]:
        print(json.dumps(rows(w, "--all" in argv)))
        return 0
    if argv[:1] == ["respawn"] and len(argv) == 2:
        jid = argv[1]
        if jid not in w["jobs"]:
            print(f"no such session {jid}", file=sys.stderr)
            return 1
        if w.get("respawn_fails") == jid:
            print("respawn failed", file=sys.stderr)
            return 1
        kill_worker(w, jid)
        if w.get("respawn_forks"):  # the daemon gives the session a new id (the binary's "old -> new" path)
            old = w["jobs"][jid]
            new = new_job(w, old["name"], old["flags"], old["cwd"], session_from=jid)
            save(w)
            spawn(w, new, ["--resume", w["jobs"][new]["transcript"], *w["jobs"][new]["flags"]])
            print(f"respawned {jid} \u2192 {new}")
            return 0
        save(w)
        spawn(w, jid, ["--resume", w["jobs"][jid]["transcript"], *w["jobs"][jid]["flags"]])
        w = load()
        print(f"respawned {jid}")
        return 0
    if argv[:1] in (["stop"], ["kill"]) and len(argv) == 2:
        jid = argv[1]
        if jid not in w["jobs"]:
            return 1
        kill_worker(w, jid)
        w["jobs"][jid]["state"] = "stopped"
        save(w)
        return 0
    if argv[:1] == ["rm"] and len(argv) == 2:
        if argv[1] in w["workers"]:
            print("session is running; stop it first", file=sys.stderr)
            return 1
        w["jobs"].pop(argv[1], None)
        save(w)
        return 0
    if argv[:1] == ["--bg"]:
        rest = argv[1:]
        flags = rest[: rest.index("--")] if "--" in rest else rest
        name, sid, fresh, i = "", None, [], 0
        while i < len(flags):
            if flags[i] == "-n":
                name, i = flags[i + 1], i + 2
            elif flags[i] == "--resume":
                sid, i = flags[i + 1], i + 2
            else:
                fresh.append(flags[i])
                i += 1
        orig = next((k for k, j in w["jobs"].items() if j["sessionId"] == sid), None) if sid else None
        if orig and orig not in w["workers"] and not fresh and not name and not w.get("always_fork"):  # continues in place, flags saved
            w["jobs"][orig]["state"] = "blocked"
            save(w)
            spawn(w, orig, ["--resume", w["jobs"][orig]["transcript"], *w["jobs"][orig]["flags"]])
            return 0
        jid = new_job(w, name or (w["jobs"][orig]["name"] if orig else "session"), fresh, os.getcwd(), session_from=orig)
        save(w)
        launch = ["--session-id", w["jobs"][jid]["sessionId"], *fresh]
        if orig:
            launch = ["--session-id", w["jobs"][jid]["sessionId"], "--fork-session", "--resume", w["jobs"][orig]["transcript"], *fresh]
        spawn(w, jid, launch)
        return 0
    print(f"fake claude: unsupported {argv}", file=sys.stderr)
    return 2


def reply(result: dict) -> int:
    print(json.dumps({"id": "cli", "result": result}))
    return 0


def herdr(argv: list[str]) -> int:
    w = load()
    tick(w)
    save(w)
    log("herdr " + " ".join(argv))
    if w.get("herdr_down"):
        print("Error: Os { code: 1, kind: PermissionDenied, message: \"Operation not permitted\" }", file=sys.stderr)
        return 1
    a = argv[0:2]
    if a == ["workspace", "list"]:
        return reply({"type": "workspace_list", "workspaces": [{"workspace_id": k, "label": v["label"]} for k, v in w["workspaces"].items()]})
    if a == ["tab", "list"]:
        ws = argv[argv.index("--workspace") + 1]
        return reply({"type": "tab_list", "tabs": [{"tab_id": k, "workspace_id": ws, "label": v["label"]} for k, v in w["tabs"].items() if v["ws"] == ws]})
    if a == ["pane", "list"]:
        return reply({"type": "pane_list", "panes": [{"pane_id": k, "tab_id": p["tab"], "workspace_id": w["tabs"][p["tab"]]["ws"], "cwd": p["cwd"],
                                                     "focused": p.get("focused", False)} for k, p in w["panes"].items()]})
    if a == ["pane", "process-info"]:
        p = w["panes"][argv[argv.index("--pane") + 1]]
        procs = [{"pid": 1, "argv": ["-zsh"]}]
        if p["fg"].startswith("attach:"):
            procs.append({"pid": p.get("attach_pid", 2), "argv": ["claude", "attach", p["fg"].split(":")[1]]})
        elif p["fg"].startswith("other:"):
            procs.append({"pid": 3, "argv": p["fg"].split(":", 1)[1].split()})
        return reply({"type": "pane_process_info", "foreground_processes": procs})
    if a == ["pane", "read"]:
        p = w["panes"][argv[2]]
        print("\n".join(p["screen"][-4:]))
        if w.get("user_typing") == argv[2]:  # somebody is typing in this pane: every look finds one more letter
            p["screen"][-1] += "x"
            save(w)
        return 0
    if a == ["pane", "run"]:
        pid, text = argv[2], " ".join(argv[3:])
        p = w["panes"][pid]
        if p["fg"] != "shell":
            log(f"TYPED-INTO-PROGRAM {pid} {p['fg']} {text}")
            return 0
        log(f"TYPED {pid} {text}")
        if text.startswith("claude attach "):
            jid = text.split()[2]
            if jid in w["jobs"]:
                if jid not in w["workers"]:
                    save(w)
                    spawn(w, jid, ["--resume", w["jobs"][jid]["transcript"], *w["jobs"][jid]["flags"]])
                    w = load()
                p = w["panes"][pid]
                w["pid"] += 1
                p["attach_pid"] = w["pid"]
                p["fg"] = f"attach:{jid}"
                p["screen"] = ["claude attach " + jid]
            else:
                p["screen"].append(f"no such session {jid}")
        else:
            p["screen"].append(text)
        save(w)
        return 0
    if a == ["agent", "list"]:
        agents = []
        for k, p in w["panes"].items():
            if p["fg"].startswith("attach:"):
                agents.append({"pane_id": k, "agent": "claude", "agent_status": w.get("dots", {}).get(k, "idle")})
        return reply({"type": "agent_list", "agents": agents})
    print(f"fake herdr: unsupported {argv}", file=sys.stderr)
    return 2


def ctl(argv: list[str]) -> int:
    """Test controls."""
    w = load()
    cmd = argv[0]
    if cmd == "noop":
        pass
    elif cmd == "set":  # set JOB key value(json)
        w["jobs"][argv[1]][argv[2]] = json.loads(argv[3])
    elif cmd == "retire":  # the daemon retires an idle worker
        kill_worker(w, argv[1])
        w["jobs"][argv[1]]["state"] = "done"
    elif cmd == "dot":
        w.setdefault("dots", {})[argv[1]] = argv[2]
    elif cmd == "type":  # the user types into a shell pane without pressing Enter
        w["panes"][argv[1]]["screen"].append(argv[2])
    elif cmd == "opt":
        w[argv[1]] = json.loads(argv[2])
    else:
        raise SystemExit(f"unknown ctl {cmd}")
    save(w)
    return 0


if __name__ == "__main__":
    which, rest = sys.argv[1], sys.argv[2:]
    sys.exit({"claude": claude, "herdr": herdr, "ctl": ctl}[which](rest))
