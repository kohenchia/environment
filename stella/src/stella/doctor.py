"""`stella doctor`: prove every piece Stella depends on works, on this machine."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tomllib

from stella import extensions, fleet, gate, leak, registry, run, scheduler, tmuxctl
from stella.config import settings, store_dir

OK, WARN, FAIL = "ok", "warn", "FAIL"


def _run(cmd: str, timeout: int = 30) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "timed out"


def checks() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    add = lambda st, name, detail="": out.append((st, name, detail))  # noqa: E731
    s = settings()

    add(OK if sys.version_info >= (3, 12) else FAIL, "python", sys.version.split()[0])
    try:
        store_dir().mkdir(parents=True, exist_ok=True)
        probe = store_dir() / ".doctor"
        probe.write_text("x")
        probe.unlink()
        add(OK, "store writable", str(store_dir()))
    except OSError as e:
        add(FAIL, "store writable", str(e))
    add(OK if (store_dir() / "canon.md").exists() else WARN, "store initialised", "run `stella install`" if not (store_dir() / "canon.md").exists() else "")

    exts = extensions.load()
    add(OK, "extensions", ", ".join(e.name for e in exts) or "none (core only)")
    for e in exts:
        for err in e.errors:
            add(FAIL, f"extension {e.name}", err)

    rc, txt = _run(f"{shlex.quote(s.query_bin)} plugin list 2>&1")
    add(OK if "stella" in txt else WARN, "stella plugin installed", "" if "stella" in txt else "run `stella install`")

    rows, err = fleet.rows()
    add(FAIL if err else OK, "session list (`agents --json`)", err or f"{len(rows)} sessions")

    srv = tmuxctl.find_server()
    if not srv and tmuxctl.last_error:
        add(FAIL, "tmux reachable from agent shells", tmuxctl.last_error)
    elif not srv:
        add(WARN, "tmux server", "none running; teams fall back to background sessions")
    else:
        app = tmuxctl.server_app(srv)
        exp = s.tmux_expected_app
        st = OK if not exp or app == exp else FAIL
        add(st, "tmux server", f"{srv.via} socket {srv.socket}; started by {app or 'unknown app'}"
            + (f" (expected {exp}: start a new server from it)" if st == FAIL else ""))

    me = run.running()
    add(OK if me else WARN, "Stella's session", f"running (pid {me['pid']})" if me else "not running: `stella run`")
    pid = scheduler.running_pid()
    add(OK if pid else WARN, "scheduler", f"running (pid {pid})" if pid else "not running: `stella run` or `stella scheduler --ensure`")

    teams, errors = registry.load()
    for e in errors:
        add(FAIL, "team registry", e)
    for t in teams.values():
        probs = registry.check(t)
        add(FAIL if probs else OK, f"team {t.name} interface", "; ".join(probs))

    for root in gate.guarded_repos():
        st_lines = gate.status(root)
        bad = [l for l in st_lines if l.startswith("FAIL")]
        add(FAIL if bad else OK, f"guarded repo {root.name}", "; ".join(l[5:] for l in bad)
            or "commit hooks in place; a push from a Claude session asks the owner first")

    g = leak.guard()
    if g.configured:
        try:
            rules = leak.load_rules(g)
            add(OK, "leak guard denylist", f"{len(rules.patterns)} rules, {len(rules.allow)} allow patterns")
        except leak.DenylistMissing as e:
            add(FAIL, "leak guard denylist", str(e))
        for root in g.protect:
            st_lines = gate.status(root) if root.exists() else ["FAIL missing"]
            bad = [l for l in st_lines if l.startswith("FAIL") and any(w in l for w in ("commit", "hooksPath", "missing"))]
            add(FAIL if bad else OK, f"leak guard hooks {root.name}", "; ".join(bad))

    for e in exts:
        f = e.file("checks")
        if not f or not f.exists():
            continue
        for c in tomllib.loads(f.read_text()).get("check", []):
            rc, txt = _run(os.path.expandvars(c["cmd"]), timeout=c.get("timeout", 30))
            want = c.get("expect")
            ok = rc == 0 and (not want or want in txt)
            add(OK if ok else (WARN if c.get("optional") else FAIL), f"{e.name}: {c['name']}",
                "" if ok else (txt.splitlines()[-1][:160] if txt else f"exit {rc}"))
    return out


def render(rows: list[tuple[str, str, str]]) -> str:
    icon = {OK: "✅", WARN: "⚠️ ", FAIL: "❌"}
    return "\n".join(f"{icon[s]} {name}{': ' + d if d else ''}" for s, name, d in rows)
