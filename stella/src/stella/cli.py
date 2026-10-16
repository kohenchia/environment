"""stella: the command line Stella and her teams use. `stella --help` lists commands."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

from stella import brief, ledger, state


def _session() -> str | None:
    return os.environ.get("STELLA_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")


def cmd_hook(a):
    from stella import hooks

    return hooks.main(a.event)


def cmd_context(a):
    from stella import context

    mode = "hq" if a.hq else "team" if a.team else "turn"
    print(context.render(mode, include_brief=not a.no_brief))


def cmd_brief(a):
    print(brief.render(state.fold()))


def cmd_log(a):
    since = a.since or 0
    evs = list(ledger.events(since))
    if a.since_days:
        cutoff = ledger.now() - dt.timedelta(days=a.since_days)
        evs = [e for e in evs if ledger.parse_ts(e) >= cutoff]
    if a.type:
        evs = [e for e in evs if e["type"] in a.type]
    evs = evs[-a.limit:]
    for e in evs:
        print(json.dumps(e, ensure_ascii=False) if a.json else f"{e['ts'][5:16]} {brief.describe(e)}")


def cmd_orders(a):
    st = state.fold()
    now = ledger.now()
    rows = st.orders.values() if a.all else st.open_orders()
    for o in sorted(rows, key=lambda o: o.seq):
        flag = " STALE" if o.stale(now) else ""
        team = f" → {o.team}" if o.team else ""
        print(f"#{o.seq} [{o.status}{flag}] {o.ts:%m-%d %H:%M} {o.session_label}{team}: {' '.join(o.text.split())[:150]}")


def cmd_close(a):
    st = state.fold()
    for seq in a.seq:
        if seq not in st.orders:
            raise SystemExit(f"no order #{seq}")
        ledger.append("close", by="cli", order=seq, status=a.status, note=a.note, session=_session())
        print(f"closed #{seq} as {a.status}")


def cmd_decide(a):
    ev = ledger.append("decision", by="cli", text=a.text, supersedes=a.supersedes or None, session=_session())
    print(f"recorded decision #{ev['seq']}")


def cmd_note(a):
    ev = ledger.append("note", by="cli", text=a.text, session=_session())
    print(f"recorded note #{ev['seq']}")


def cmd_attention(a):
    items = state.fold().attention()
    if a.json:
        print(json.dumps([{"key": i.key, "seq": i.seq, "text": i.text} for i in items], indent=1))
        return
    if not items:
        print("Nothing needs you.")
    for i in items:
        print(f"- [{i.key}] {i.text}")


def cmd_ack(a):
    keys = a.key
    if keys == ["all"]:
        keys = [i.key for i in state.fold().attention()]
    for k in keys:
        ledger.append("ack", by="cli", key=k)
    print(f"acknowledged {len(keys)}")


def cmd_fleet(a):
    from stella import fleet

    rows, err = fleet.rows()
    if a.json:
        print(json.dumps({"sessions": rows, "error": err}, indent=1, default=str))
        return
    print(fleet.table(rows))
    if err:
        print(f"\n(session list unavailable: {err})")


def cmd_teams(a):
    from stella import registry

    teams, errors = registry.load()
    print("\n".join(registry.summary_lines(teams)) or "no teams registered")
    for e in errors:
        print(f"ERROR: {e}")


def cmd_team(a):
    from stella import registry

    teams, _ = registry.load()
    if a.name not in teams:
        raise SystemExit(f"unknown team {a.name!r}")
    print(registry.interface(teams[a.name], run_help=not a.no_help))


def cmd_launch(a):
    from stella import launch

    r = launch.launch(a.archetype, order_seq=a.order, text=a.text, name=a.name, directory=a.dir,
                      args=a.args or "", permission_mode=a.mode, dry_run=a.dry_run)
    if a.dry_run:
        print(r.script.read_text())
        return
    where = f"tmux window {r.window} ('{r.name}')" if r.window else r.via
    print(f"launched {r.name} in {where}, cwd {r.directory}; ledger #{r.event['seq']}")


def cmd_tell(a):
    from stella import tmuxctl

    if a.team.startswith("stella-review"):
        raise SystemExit("refusing: only the owner types into a push review")
    st = state.fold()
    t = st.teams.get(a.team)
    if t and t.window:
        srv = tmuxctl.server_for_socket(st_socket(a.team))
        if srv and tmuxctl.window_exists(srv, t.window) and not tmuxctl.window_dead(srv, t.window):
            tmuxctl.send_text(srv, t.window, f"[Stella] {a.message}")
            ev = ledger.append("tell", by="cli", team=a.team, text=a.message, via="tmux", session=_session())
            print(f"delivered to {a.team} (window {t.window}); ledger #{ev['seq']}")
            return
    ev = ledger.append("tell", by="cli", team=a.team, text=a.message, via="message", session=_session())
    print(
        f"{a.team} has no open Stella window. Deliver it with the SendMessage tool (find the address with ListAgents"
        f" by the name {a.team!r}), prefixed with \"[Stella] \". Recorded as ledger #{ev['seq']}."
    )


def st_socket(team: str) -> str | None:
    sock = None
    for e in ledger.events():
        if e["type"] == "launch" and e.get("team") == team:
            sock = e.get("socket")
    return sock


def cmd_report(a):
    from stella import notify

    ev = ledger.append("report", by="cli", team=a.team, text=a.message, needs_you=a.needs_you or None)
    if a.needs_you:
        notify.notify(f"Stella: {a.team} needs you", a.message)
    print(f"recorded #{ev['seq']}")


def cmd_done(a):
    from stella import notify

    ev = ledger.append("done", by="cli", team=a.team, text=a.message)
    notify.notify(f"Stella: {a.team} finished", a.message)
    print(f"recorded #{ev['seq']}; the owner has been notified")


def cmd_search(a):
    q = [w.lower() for w in a.query.split()]
    hits = [e for e in ledger.events() if all(w in json.dumps(e, ensure_ascii=False).lower() for w in q)]
    for e in hits[-a.limit:][::-1]:
        print(f"{e['ts'][:16]} {brief.describe(e)}")
    if not hits:
        print("no matches")


def cmd_hq(a):
    from stella import hq

    print(hq.open_hq(fresh=a.fresh, here=a.here))


def cmd_scheduler(a):
    from stella import hq, scheduler, tmuxctl

    if a.ensure:
        srv = tmuxctl.find_server()
        if not srv:
            raise SystemExit("no tmux server running")
        print(f"scheduler window {hq.ensure_scheduler(srv)}")
        return
    if a.once:
        print(scheduler.tick() or "nothing due")
        return
    return scheduler.run_forever()


def cmd_daily(a):
    from stella import daily

    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    if a.digest_only:
        print(daily.digest(d))
        return
    return daily.run_daily(d)


def cmd_nightly(a):
    from stella import daily

    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    print("\n".join(daily.run_nightly(d)))


def cmd_focus(a):
    from stella import daily
    from stella.config import store_dir

    pr = store_dir() / "priorities.md"
    print(pr.read_text() if pr.exists() else "(no priorities recorded: ask the owner)")
    print(f"\nToday's work digest: {daily.digest(dt.date.today())}")
    print("\nOpen orders:")
    cmd_orders(argparse.Namespace(all=False))


def cmd_remember(a):
    ev = ledger.append("correction", by="cli", text=a.text, session=_session())
    print(f"recorded correction #{ev['seq']}. Now hand it to the stella-curator agent (subagent type"
          f" `stella:stella-curator`) with the correction text and its ledger number.")


def cmd_propose(a):
    from stella import canon

    print(canon.propose(a.title, a.evidence, a.body))


def cmd_proposals(a):
    from stella import canon

    for pid, st, title in canon.proposals(None if a.all else "open"):
        print(f"{pid} [{st}] {title}")


def cmd_accept(a):
    from stella import canon

    f = canon.resolve(a.id, "accepted", a.note or "")
    print(f"accepted {a.id}. Hand {f} to the stella-curator agent to apply it to the canon and add a case.")


def cmd_reject(a):
    from stella import canon

    canon.resolve(a.id, "rejected", a.why)
    print(f"rejected {a.id}")


def cmd_eval(a):
    from stella import canon

    r = canon.run_eval(a.case or None)
    print(json.dumps(r, indent=1))
    return 1 if r["regressions"] else 0


def cmd_push(a):
    from stella import gate

    repo = gate.resolve_alias(a.repo)
    ev = gate.push(repo, a.branch or gate.current_branch(repo))
    print(f"pushed {ev['sha'][:7]} to {ev['ref']} (approval: {ev['approval']}); ledger #{ev['seq']}")


def cmd_review_push(a):
    from stella import gate

    repo = gate.resolve_alias(a.repo)
    return gate.review_push(repo, a.branch or gate.current_branch(repo))


def cmd_push_question(a):
    from stella import gate

    repo = gate.resolve_alias(a.repo)
    print(gate.push_question(repo, a.branch or gate.current_branch(repo), _session()))
    print("Ask the owner exactly this. A plain yes from them (addressed to you) approves this head only.")


def cmd_gate(a):
    from stella import daily, gate

    repos = [gate.resolve_alias(a.repo)] if a.repo else gate.guarded_repos()
    for r in repos:
        lines = gate.install(r) if a.action == "install" else gate.status(r)
        print(f"{r}:\n  " + "\n  ".join(lines))
    if a.action == "install":
        daily.record_baseline()


def cmd_git_hook(a):
    from stella import gate

    stdin = sys.stdin.read() if a.name == "pre-push" else ""
    return gate.git_hook(a.name, a.args, stdin)


def cmd_leakcheck(a):
    from stella import leak

    g = leak.guard()
    try:
        rules = leak.load_rules(g)
    except leak.DenylistMissing as e:
        print(f"denylist missing: {e}")
        return 2
    if a.text is not None:
        hits = leak.scan_text(a.text if a.text != "-" else sys.stdin.read(), "text", rules)
    else:
        root = Path(a.path or ".").resolve()
        hits = (leak.scan_staged(root, rules) if a.staged else
                leak.scan_range(root, a.range, rules) if a.range else leak.scan_tree(root, rules))
    for h in hits:
        print(f"{h.where}:{h.line}: {h.term!r}: {h.text}")
    print(f"{len(hits)} hit(s)", file=sys.stderr)
    return 1 if hits else 0


def cmd_doctor(a):
    from stella import doctor

    rows = doctor.checks()
    print(json.dumps(rows) if a.json else doctor.render(rows))
    return 1 if any(s == "FAIL" for s, _, _ in rows) else 0


def cmd_ext(a):
    from stella import extensions

    if a.action == "list":
        for e in extensions.load():
            print(f"{e.name}: {e.root}{' ERRORS: ' + '; '.join(e.errors) if e.errors else ''}")
        return
    p = Path(a.path)
    ok = extensions.register(p) if a.action == "register" else extensions.unregister(p)
    print(f"{a.action}ed {p}" if ok else f"nothing to {a.action}")


def cmd_install(a):
    from stella import install

    print("\n".join(install.install(plugin=not a.no_plugin, gate_=not a.no_gate)))


def build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stella", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def c(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    sp = c("hook", cmd_hook, "Claude Code hook entry point (reads hook JSON on stdin)")
    sp.add_argument("event", choices=["prompt", "session-start", "session-end", "pretool"])
    sp = c("context", cmd_context, "Persona addenda, knowledge maps, teams and the brief")
    sp.add_argument("--hq", action="store_true")
    sp.add_argument("--team", action="store_true")
    sp.add_argument("--no-brief", action="store_true")
    c("brief", cmd_brief, "The state brief: open orders, teams, what needs the owner")
    sp = c("log", cmd_log, "Ledger events")
    sp.add_argument("--since", type=int)
    sp.add_argument("--since-days", type=float)
    sp.add_argument("--type", action="append")
    sp.add_argument("--limit", type=int, default=50)
    sp.add_argument("--json", action="store_true")
    sp = c("orders", cmd_orders, "Open orders (or all with --all)")
    sp.add_argument("--all", action="store_true")
    sp = c("close", cmd_close, "Close orders")
    sp.add_argument("seq", type=int, nargs="+")
    sp.add_argument("--status", default="done", choices=["done", "superseded", "cancelled", "expired"])
    sp.add_argument("--note")
    sp = c("decide", cmd_decide, "Record a decision (optionally superseding orders)")
    sp.add_argument("text")
    sp.add_argument("--supersedes", type=int, action="append")
    sp = c("note", cmd_note, "Record a note")
    sp.add_argument("text")
    sp = c("attention", cmd_attention, "What needs the owner")
    sp.add_argument("--json", action="store_true")
    sp = c("ack", cmd_ack, "Acknowledge attention items (keys from `stella attention`, or 'all')")
    sp.add_argument("key", nargs="+")
    sp = c("fleet", cmd_fleet, "Every session on this machine, and what Stella launched")
    sp.add_argument("--json", action="store_true")
    c("teams", cmd_teams, "Registered team archetypes")
    sp = c("team", cmd_team, "A team's full interface")
    sp.add_argument("name")
    sp.add_argument("--no-help", action="store_true", help="don't run the team's --help commands")
    sp = c("launch", cmd_launch, "Launch a team lead in its own tmux window")
    sp.add_argument("archetype", help="a registered team, or 'adhoc'")
    sp.add_argument("--order", type=int, help="ledger number of the order this carries out")
    sp.add_argument("--text", help="the task, if not the order's own words (adhoc teams: the team design + task)")
    sp.add_argument("--name")
    sp.add_argument("--dir")
    sp.add_argument("--args", help="arguments for the team's launch command")
    sp.add_argument("--mode", help="permission mode override")
    sp.add_argument("--dry-run", action="store_true")
    sp = c("tell", cmd_tell, "Send a message to a running team lead")
    sp.add_argument("team")
    sp.add_argument("message")
    sp = c("report", cmd_report, "(team leads) report progress, or that the owner is needed")
    sp.add_argument("team")
    sp.add_argument("message")
    sp.add_argument("--needs-you", action="store_true")
    sp = c("done", cmd_done, "(team leads) report the order complete")
    sp.add_argument("team")
    sp.add_argument("message")
    sp = c("search", cmd_search, "Search the whole ledger")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp = c("hq", cmd_hq, "Open (or switch to) HQ, the persistent Stella session")
    sp.add_argument("--fresh", action="store_true", help="start a new HQ conversation (nothing is lost: state is on disk)")
    sp.add_argument("--here", action="store_true", help="run HQ in this terminal")
    sp = c("scheduler", cmd_scheduler, "Run the daily/nightly scheduler")
    sp.add_argument("--ensure", action="store_true", help="make sure the scheduler window is running")
    sp.add_argument("--once", action="store_true", help="run whatever is due, then exit")
    sp = c("daily", cmd_daily, "Write the daily log now")
    sp.add_argument("--date")
    sp.add_argument("--digest-only", action="store_true")
    sp = c("nightly", cmd_nightly, "Run the nightly jobs now")
    sp.add_argument("--date")
    c("focus", cmd_focus, "Priorities, today's work digest and open orders, for a focus check")
    sp = c("remember", cmd_remember, "Record a correction or something to remember")
    sp.add_argument("text")
    sp = c("propose", cmd_propose, "Record a learning proposal for the owner")
    sp.add_argument("--title", required=True)
    sp.add_argument("--evidence", required=True)
    sp.add_argument("--body", required=True)
    sp = c("proposals", cmd_proposals, "List proposals")
    sp.add_argument("--all", action="store_true")
    sp = c("accept", cmd_accept, "Accept a proposal (owner only)")
    sp.add_argument("id")
    sp.add_argument("--note")
    sp = c("reject", cmd_reject, "Reject a proposal (owner only)")
    sp.add_argument("id")
    sp.add_argument("--why", required=True)
    sp = c("eval", cmd_eval, "Replay past decisions against the canon")
    sp.add_argument("case", nargs="*")
    sp = c("push", cmd_push, "Push a guarded repo (needs an approval for the exact head)")
    sp.add_argument("repo")
    sp.add_argument("--branch")
    sp = c("review-push", cmd_review_push, "(owner, at a terminal) review a guarded repo's diff, approve and push")
    sp.add_argument("repo")
    sp.add_argument("--branch")
    sp = c("push-question", cmd_push_question, "Record the push question Stella must ask the owner")
    sp.add_argument("repo")
    sp.add_argument("--branch")
    sp = c("gate", cmd_gate, "Install or check the push gate")
    sp.add_argument("action", choices=["install", "status"])
    sp.add_argument("repo", nargs="?")
    sp = c("git-hook", cmd_git_hook, "(git) hook entry point")
    sp.add_argument("name")
    sp.add_argument("args", nargs="*")
    sp = c("leakcheck", cmd_leakcheck, "Check text, a tree, staged changes or a range against the denylist")
    sp.add_argument("path", nargs="?")
    sp.add_argument("--staged", action="store_true")
    sp.add_argument("--range")
    sp.add_argument("--text")
    sp = c("doctor", cmd_doctor, "Check everything Stella depends on")
    sp.add_argument("--json", action="store_true")
    sp = c("ext", cmd_ext, "Register, unregister or list extensions")
    sp.add_argument("action", choices=["register", "unregister", "list"])
    sp.add_argument("path", nargs="?", default="")
    sp = c("install", cmd_install, "Set up the store, the plugin and the push gate on this machine")
    sp.add_argument("--no-plugin", action="store_true")
    sp.add_argument("--no-gate", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build().parse_args(argv)
    r = a.fn(a)
    return r if isinstance(r, int) else 0
