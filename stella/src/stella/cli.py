"""stella: the command line Stella and her teams use. `~/.local/bin/stella --help` lists commands."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import subprocess
from pathlib import Path

from stella import brief, ledger, state


def _session() -> str | None:
    return os.environ.get("STELLA_SESSION_ID") or os.environ.get("CLAUDE_SESSION_ID")


def cmd_hook(a):
    from stella import hooks

    return hooks.main(a.event)


def cmd_context(a):
    from stella import context

    mode = "self" if a.self_ else "team" if a.team else "turn"
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


def cmd_shown(a):
    ev = ledger.append("list_shown", by="cli", items=a.item, session=_session())
    print(f"recorded the list shown #{ev['seq']} ({len(a.item)} items)")


def cmd_attention(a):
    from stella import finish

    st = state.fold()
    finish.clear_pushed(st)
    items = st.attention()
    if a.json:
        print(json.dumps([{"n": n, "key": i.key, "seq": i.seq, "text": i.text} for n, i in enumerate(items, 1)], indent=1))
        return
    if not items:
        print("Nothing needs you.")
    for n, i in enumerate(items, 1):
        print(f"{n}. [{i.key}] {i.text}")  # numbered in the order the status block lists them


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
                      args=a.args or "", permission_mode=a.mode, dry_run=a.dry_run, auto_push=a.auto_push)
    if a.dry_run:
        print(r.script.read_text())
        return
    where = f"tmux window {r.window} ('{r.name}')" if r.window else r.via
    print(f"launched {r.name} in {where}, cwd {r.directory}; ledger #{r.event['seq']}")


def cmd_tell(a):
    from stella import tmuxctl

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


def cmd_reopen(a):
    from stella import launch

    print(launch.reopen(a.target, a.dir, a.dry_run))


def cmd_fix_resume(a):
    from stella import resume

    ids: set[str] = set()
    for target in a.target:
        f = resume.lookup(target)
        if f:
            ids.add(f.session_id)
        else:
            print(f"{target}: no transcript with that name or id")
    if a.all or not a.target:
        ids |= {sid for t in state.fold().teams.values() for sid in t.sessions}
    for line in resume.heal_known(ids) or ["nothing to change: every one of these sessions is already listed"]:
        print(line)


def cmd_reap(a):
    from stella import wrapup

    st = state.fold()
    names = a.name or [t.name for t in st.teams.values() if t.status in {"done", "ended"}]
    for name in names:
        t = st.teams.get(name)
        if not t:
            print(f"no team {name}")
            continue
        if t.status not in {"done", "ended"} and not a.force:
            print(f"{name} is {t.status}; not closing (use --force)")
            continue
        print(wrapup.close_team(st, t)[1])


def cmd_wrap(a):
    from stella import wrapup

    print(wrapup.wrap_current(delay=a.delay, dry_run=a.dry_run))


def cmd_wrapup(a):
    from stella import wrapup

    if a.process_requests:  # internal: what the scheduler does for the last-resort queues (tyfp, adoption)
        print("\n".join(f"closed {w}" for w in wrapup.process_requests()))
        return
    if a.close_pids:  # internal: the detached helper of `stella wrap` / `tyfp`
        from stella import direct

        return direct.run_helper(a.close_pids, a.delay)
    if not a.team:
        raise SystemExit("stella wrapup needs the team to wrap up: `stella wrapup <team>` closes that one team. "
                         "To check every finished team (the automatic sweep) run `stella sweep`.")
    for name in a.team:
        print(wrapup.wrap_team(name, dry_run=a.dry_run).message)


def cmd_sweep(a):
    from stella import wrapup

    if a.now:
        from stella import tyfp

        print(tyfp.run(None, None, dry_run=a.dry_run).text())
        return
    wrapped, kept = wrapup.sweep(dry_run=a.dry_run)
    print(wrapup.report(wrapped, kept, a.dry_run))


def cmd_report(a):
    from stella import notify, wake

    ev = ledger.append("report", by="cli", team=a.team, text=a.message, needs_you=a.needs_you or None)
    if a.needs_you:
        notify.notify(f"Stella: {a.team} needs you", a.message)
        wake.kick()
    print(f"recorded #{ev['seq']}")
    if a.needs_you:
        print(
            "The owner reads this window, not the ledger. Your next message must state the request in full:"
            " the question, the options, your recommendation, and what you will do meanwhile."
            " Do not say that you reported or asked."
        )


def cmd_done(a):
    from stella import notify, wake

    from stella import finish

    res = finish.for_done(os.getcwd())
    text = a.message
    if res and res.block:
        print(res.block + "\nThen run `stella done` again.", file=sys.stderr)
        raise SystemExit(1)
    if res and res.deferred:
        text += " [" + "; ".join(res.deferred) + "]"
    if res and res.outstanding:
        text += " [not pushed: " + "; ".join(res.outstanding) + "]"
    ev = ledger.append("done", by="cli", team=a.team, text=text)
    notify.notify(f"Stella: {a.team} finished", a.message)
    wake.kick()
    print(f"recorded #{ev['seq']}; the owner has been notified")


def cmd_followup(a):
    from stella import wake

    st = state.fold()
    if a.action == "add":
        after = [t.strip() for t in a.after.split(",") if t.strip()]
        if not after:
            raise SystemExit("--after needs at least one team name")
        ev = ledger.append("followup", by="cli", text=a.text, after=after, session=_session())
        st = state.fold()
        waiting = st.waiting_on(st.followups[ev["seq"]])
        if waiting:
            print(f"recorded follow-up #{ev['seq']}, waiting on {', '.join(waiting)}. You will be woken when it is READY.")
        else:
            wake.seen(ev["seq"])
            print(f"recorded follow-up #{ev['seq']}; it is READY now (every team named has finished): act on it.")
        return
    if a.action == "list":
        rows = brief.followup_lines(st) if not a.all else [
            f"- #{f.seq} [{f.status}] after {', '.join(f.after)}: {' '.join(f.text.split())[:150]}"
            for f in sorted(st.followups.values(), key=lambda f: f.seq)]
        print("\n".join(rows) or "No open follow-ups.")
        return
    for seq in a.seq:
        f = st.followups.get(seq)
        if not f:
            raise SystemExit(f"no follow-up #{seq}")
        if f.status != "open":
            print(f"follow-up #{seq} is already closed ({f.status})")
            continue
        ledger.append("followup_close", by="cli", followup=seq, status=a.status, note=a.note, session=_session())
        print(f"closed follow-up #{seq} as {a.status}")


def cmd_wake(a):
    from stella import wake

    return wake.main()


def cmd_search(a):
    q = [w.lower() for w in a.query.split()]
    hits = [e for e in ledger.events() if all(w in json.dumps(e, ensure_ascii=False).lower() for w in q)]
    for e in hits[-a.limit:][::-1]:
        print(f"{e['ts'][:16]} {brief.describe(e)}")
    if not hits:
        print("no matches")


def cmd_run(a):
    from stella import run

    r = run.run(fresh=a.fresh, pass_env=a.pass_env)
    if isinstance(r, int):
        return r
    print(r)


def cmd_stop(a):
    from stella import run

    print(run.stop(keep_scheduler=a.keep_scheduler))


def cmd_pass_env(a):
    from stella import config, passenv, run, tmuxctl, tokreport, windows

    prev = passenv.mode()
    if a.action in {"on", "off"}:
        passenv.set_mode(a.action, by="cli")
    if not config.settings().pass_env:
        print(passenv.status())
        return
    mode = passenv.effective()
    srv = tmuxctl.find_server() or tmuxctl.server_for_socket(run._load().get("socket"))
    inv = windows.inventory(srv) if srv else None
    print(tokreport.switch_line(mode))
    print("\n".join(passenv.status().splitlines()[2:]))  # one line per variable: its file
    if inv is None and not a.respawn:
        print(tmuxctl.last_error or "No tmux server found: no windows to list.")
        return
    before = {t.pane_id: tokreport.token_of(t) for t in inv.targets} if inv else {}
    print()
    if not a.respawn:
        print("\n".join(tokreport.table(inv, mode, "Live windows, token read from each process's environment (names only):")))
        if a.action in {"on", "off"}:
            print("Sessions started from now on follow the switch. Running ones keep their token until restarted:"
                  " `tok on` / `tok off` (= `stella pass-env on|off --respawn`).")
        return
    if inv is None:  # no tmux: restart_all says why, and names any --team that does not exist
        for r in windows.restart_all("", only_teams=a.team or None):
            print(tokreport.result_line(r, {}, mode, 14))
        return
    w = tokreport.width(inv)
    print(tokreport.header(mode, (prev or "off") if a.action in {"on", "off"} else None))
    print(f"  (restarting {len(inv.targets)} live window{'s' if len(inv.targets) != 1 else ''}, each resumes its conversation)")
    why = f"Restarted with pass_env {mode}."
    results = windows.restart_all(why, only_teams=a.team or None,
                                  emit=lambda r: print(tokreport.result_line(r, before, mode, w), flush=True))
    if a.team:
        return
    print("\n".join(tokreport.extras(inv, w)))
    pending = {r.target.pane_id for r in results if r.outcome == "later" and r.target}
    reasons = {r.name: r.text for r in results if r.outcome in {"skipped", "failed"}}
    tokreport.settle()
    after = windows.inventory(srv, with_agents=False)
    print()
    print("\n".join(tokreport.table(after, mode, "Now, re-read from each process after the restarts:", pending, reasons, with_extras=False)))


def cmd_respawn_self(a):
    from pathlib import Path

    from stella import windows

    if a.plan:  # the detached helper started by `pass-env --respawn`
        windows.run_plan(Path(a.plan))
        return
    from stella import run, tmuxctl

    srv = tmuxctl.find_server() or tmuxctl.server_for_socket(run._load().get("socket"))
    me = [t for t in windows.discover(srv) if t.kind == "stella"] if srv else []
    if not me:
        print("Stella: not running in any tmux pane; `stella run` will start her on the current setting.")
        return
    if reason := windows.skip_reason(me[0]):
        print(f"Stella: skipped, {reason}")
        return
    windows._later(srv, me, a.why or "Restarted.")
    print(f"Stella: restarting in {me[0].window_name} {me[0].pane_id} in a moment, conversation resumed")


def cmd_scheduler(a):
    from stella import scheduler

    if a.ensure:
        print(scheduler.ensure_daemon())
        return
    if a.stop:
        print(scheduler.stop_daemon())
        return
    if a.once:
        print(scheduler.run_once(in_session=a.in_session) or "nothing due")
        return
    if a.wake_check:
        print(scheduler.wake_backstop() or "nothing pending")
        return
    return scheduler.run_forever()


def _window_arg(a):
    """--date D is that local calendar day; without it, the day that just ended."""
    from stella import daily, scheduler

    d = dt.date.fromisoformat(a.date) if a.date else dt.date.today() - dt.timedelta(days=1)
    return daily.day_window(d, scheduler.zone_name())


def cmd_daily(a):
    from stella import daily

    win = _window_arg(a)
    if a.digest_only:
        print(daily.digest(win))
        return
    return daily.run_daily(win)


def cmd_nightly(a):
    from stella import daily

    print("\n".join(daily.run_nightly(_window_arg(a))))


def cmd_focus(a):
    from stella import daily
    from stella.config import store_dir

    pr = store_dir() / "priorities.md"
    print(pr.read_text() if pr.exists() else "(no priorities recorded: ask the owner)")
    midnight = daily.local_midnight(dt.date.today())
    print(f"\nToday's work digest: {daily.digest(daily.Window(midnight, ledger.now()))}")
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


def cmd_gate(a):
    from stella import gate

    repos = [gate.resolve_alias(a.repo)] if a.repo else gate.guarded_repos()
    for r in repos:
        lines = gate.install(r) if a.action == "install" else gate.status(r)
        print(f"{r}:\n  " + ("\n  ".join(lines) or "nothing to do"))


def cmd_diff(a):
    from stella import gate

    repo = gate.resolve_alias(a.repo) if a.repo else Path.cwd()
    subprocess.run(["sh", "-c", gate._diff_command(repo)])


def cmd_push(a):
    """Push the current branch of one repo: the one short command a session runs to push. The tool hook recognises it
    and raises the owner's yes/no prompt; this only does the push (and the leak scan first)."""
    from stella import gate, leak

    where = Path(a.dir or ".").resolve()
    if a.plan:
        pl = gate.plan(where)
        if pl.get("approved"):
            print(f"Already approved: run `stella push -C {where}` now.")
        elif not pl:
            print(f"{where} is not in a git repository with a remote: nothing to ask.")
        elif pl.get("nothing"):
            print("Nothing to push.")
        else:
            print(f"Ask the owner with AskUserQuestion, exactly:\n  header: Push\n  question: {pl['question']}\n"
                  f"  options: \"{gate.PUSH_LABEL}\" (description: send it; preview: the text below, verbatim) and \"{gate.DEFER_LABEL}\" (description: not now)\n"
                  f"Then, if he picked Push, run `stella push -C {where}`; if Defer, do not push (say \"not pushed, deferred\").\n--- preview ---\n{pl['preview']}")
        return 0
    top = gate._git_out(where, "rev-parse", "--show-toplevel")
    branch = gate._git_out(where, "rev-parse", "--abbrev-ref", "HEAD")
    if not top:
        print(f"{where} is not in a git repository.", file=sys.stderr)
        return 2
    if branch in {"", "HEAD"}:
        print(f"HEAD in {top} is on no branch: put the commits on one (`git switch -c <name>`), then run `stella push` again.", file=sys.stderr)
        return 2
    g = leak.guard()
    if g.configured and leak.protected_root(top, g):
        try:
            rng, _ = gate._remote_range(Path(top))
            hits = leak.scan_range(Path(top), rng.replace("...", ".."), leak.load_rules(g)) if rng else []
        except leak.DenylistMissing as e:
            print(f"STELLA LEAK GUARD: denylist missing ({e}); refusing to push a protected repo.", file=sys.stderr)
            return 1
        if hits:
            print("STELLA LEAK GUARD: not pushed; these look private to an extension:", file=sys.stderr)
            for h in hits[:30]:
                print(f"  {h.where}:{h.line}: {h.term!r}: {h.text}", file=sys.stderr)
            return 1
    return subprocess.run(["git", "-C", top, "push", "-u", "origin", branch]).returncode


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


EPILOG = """\
gg: type exactly `gg` (alone, any case) as a prompt in any Claude session in the Stella tmux server and that session
wraps ONLY itself up, the same as /stella:wrap-up, `stella wrap` and `stella wrapup <team>`. It never runs the all-teams sweep (`stella sweep`). It first checks that nothing is
unpushed, uncommitted, deferred or waiting on the owner; if something is, it does not close, says what in one line and,
for an unpushed commit, raises the push prompt. If clean, it closes the session and its window (verified), closes the
team's orders and writes `wrapped_up`. keep_open teams (review) close too. In a session that is not a team it closes
just that window. In Stella's own session it is refused: she is never wrapped up.

tyfp: type exactly `tyfp` as a prompt in any session in the Stella tmux server and EVERY session that is done is wrapped up
(`gg` wraps up only the session it is typed in). Same checks as gg for each, no grace period, keep_open and adopted sessions
included; busy, running, blocked sessions and Stella's own stay. One report: `wrapped up: <names>` and `left open: <name>:
<reason>`; for a session blocked only by an unpushed commit the push prompt is raised. The session it was typed in goes last.

status block: every turn of every session in the Stella tmux server ends with a block as the last thing of the final
message: a line of 40 U+2501 characters, then `🟧 **NEXT FOR YOU** (N)` and N numbered items (the owner answers "do 2"),
`🟩 **ALL DONE** — ready to wrap up. Type `gg`.`, or `🟦 **WORKING** — <what is still running>`. The Stop hook checks
it and blocks the stop once, with the exact block to write, when it is missing, malformed (count and items differ, no
items) or contradicts the facts (ALL DONE with unpushed commits, a deferred push, an open question or uncommitted
changes). The old one-line forms are accepted for one release, with the same single block.
"""


def build() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stella", description=__doc__, epilog=EPILOG,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def c(name, fn, help_):
        sp = sub.add_parser(name, help=help_, description=help_)
        sp.set_defaults(fn=fn)
        return sp

    sp = c("hook", cmd_hook, "Claude Code hook entry point (reads hook JSON on stdin)")
    sp.add_argument("event", choices=["prompt", "session-start", "session-end", "pretool", "posttool", "stop"])
    sp = c("context", cmd_context, "Persona addenda, knowledge maps, teams and the brief")
    sp.add_argument("--self", dest="self_", action="store_true", help="as Stella's own session")
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
    sp = c("shown", cmd_shown, "Record the numbered list just shown to the owner (a bare number from him refers to it; `brief` shows the last one)")
    sp.add_argument("item", nargs="+")
    sp = c("attention", cmd_attention, "What needs the owner")
    sp.add_argument("--json", action="store_true")
    sp = c("ack", cmd_ack, "Acknowledge attention items (keys from `~/.local/bin/stella attention`, or 'all')")
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
    sp.add_argument("--auto-push", action="store_true",
                    help="the owner said up front to push: the team pushes its branch without the yes/no prompt")
    sp.add_argument("--dry-run", action="store_true")
    sp = c("tell", cmd_tell, "Send a message to a running team lead")
    sp.add_argument("team")
    sp.add_argument("message")
    sp = c("reopen", cmd_reopen, "Reopen a finished session in a tmux window, by team name, session name or id (resumes it where it started)")
    sp.add_argument("target")
    sp.add_argument("--dir", help="start somewhere else than the directory it was started in")
    sp.add_argument("--dry-run", action="store_true")
    sp = c("fix-resume", cmd_fix_resume, "List sessions in the `claude --resume` picker that it hides (headless origin): the named ones, or all of Stella's")
    sp.add_argument("target", nargs="*", help="session names or ids; none means every session Stella launched")
    sp.add_argument("--all", action="store_true", help="the named ones and all of Stella's")
    sp = c("reap", cmd_reap, "Close the windows of finished teams (all finished ones, or those named)")
    sp.add_argument("name", nargs="*")
    sp.add_argument("--force", action="store_true", help="also close a team that has not reported done")
    sp = c("wrap", cmd_wrap, "(in a session) wrap up this session after the `gg` checks: record it closed, then close its tmux window at once, without tmux or the scheduler")
    sp.add_argument("--delay", type=float, default=3, help="seconds before the window closes, so the reply can finish")
    sp.add_argument("--dry-run", action="store_true", help="say what would close; change nothing")
    sp = c("wrapup", cmd_wrapup, "Wrap up the ONE named team now, as `gg` does for the session it is typed in (same checks; nothing else is touched)")
    sp.add_argument("team", nargs="*", help="the team to wrap up (nothing unpushed, uncommitted, deferred or waiting on the owner; keep_open does not matter)")
    sp.add_argument("--dry-run", action="store_true", help="say what would close; change nothing")
    sp.add_argument("--close-pids", help=argparse.SUPPRESS)  # internal: PANE_PID:START,CLAUDE_PID:START, closed after --delay
    sp.add_argument("--delay", type=float, default=3, help=argparse.SUPPRESS)
    sp.add_argument("--process-requests", action="store_true", help=argparse.SUPPRESS)
    sp = c("sweep", cmd_sweep, "The AUTOMATIC sweep over EVERY finished team (not `gg`, which wraps up one session): records gone teams, and closes the clean finished ones only if wrapup_auto is on")
    sp.add_argument("--dry-run", action="store_true", help="list what would be wrapped up and why the rest stays open; change nothing")
    sp.add_argument("--now", action="store_true", help="the owner's explicit sweep, what `tyfp` types: every clean, idle session at once, no grace period, keep_open and adopted ones included; busy, running and blocked ones stay (with the reason)")
    sp = c("report", cmd_report, "(team leads) report progress, or that the owner is needed")
    sp.add_argument("team")
    sp.add_argument("message")
    sp.add_argument("--needs-you", action="store_true")
    sp = c("done", cmd_done, "(team leads) report the order complete")
    sp.add_argument("team")
    sp.add_argument("message")
    sp = c("followup", cmd_followup, "Stella's follow-ups: \"after these teams are done, do this\"")
    fsub = sp.add_subparsers(dest="action", required=True)
    fp = fsub.add_parser("add", help="record a follow-up", description="record a follow-up")
    fp.add_argument("text", help="what to do")
    fp.add_argument("--after", required=True, help="the team(s) that must finish first, comma-separated")
    fp = fsub.add_parser("list", help="open follow-ups, READY or waiting (or all with --all)")
    fp.add_argument("--all", action="store_true")
    fp = fsub.add_parser("close", aliases=["done"], help="close follow-ups")
    fp.add_argument("seq", type=int, nargs="+")
    fp.add_argument("--status", default="done", choices=["done", "cancelled"])
    fp.add_argument("--note")
    sp = sub.add_parser("wake")  # internal: the detached helper that types the wake line
    sp.set_defaults(fn=cmd_wake)
    sp = c("search", cmd_search, "Search the whole ledger")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=10)
    sp = c("run", cmd_run, "Run Stella: her own session, where every message is to her (and the scheduler in the background)")
    sp.add_argument("--fresh", action="store_true", help="start a new conversation (nothing is lost: state is on disk)")
    sp.add_argument("--pass-env", choices=["on", "off"],
                    help="set the pass_env switch (without it, `stella run` reads the switch and leaves it alone)")
    sp = c("stop", cmd_stop, "Stop Stella: her session and the background scheduler (launched teams keep running)")
    sp.add_argument("--keep-scheduler", action="store_true", help="stop only her session")
    sp = c("pass-env", cmd_pass_env, "Show or switch whether sessions Stella starts get the pass_env variables;"
           " --respawn restarts every Claude window in the tmux server (teams, Stella, hand-opened ones) on the current setting")
    sp.add_argument("action", nargs="?", default="status", choices=["status", "on", "off"])
    sp.add_argument("--respawn", action="store_true", help="restart every Claude window in the tmux server (teams, hand-opened ones, then Stella), resuming their conversations")
    sp.add_argument("--team", action="append", default=[], help="with --respawn: only this team (repeatable; Stella and hand-opened windows are left alone)")
    sp = c("respawn-self", cmd_respawn_self, "Restart Stella's own session in her pane, conversation resumed (what `pass-env --respawn` does last)")
    sp.add_argument("why", nargs="?", default="")
    sp.add_argument("--plan", help=argparse.SUPPRESS)  # internal: the detached helper's list of restarts
    sp = c("scheduler", cmd_scheduler, "Run the daily/nightly scheduler")
    sp.add_argument("--ensure", action="store_true", help="start the background scheduler unless it is running")
    sp.add_argument("--stop", action="store_true", help="stop the background scheduler")
    sp.add_argument("--once", action="store_true", help="run whatever is due, then exit")
    sp.add_argument("--wake-check", action="store_true", help="run the wake-line backstop once, then exit")
    sp.add_argument("--in-session", action="store_true", help=argparse.SUPPRESS)
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
    sp = c("gate", cmd_gate, "Guarded repos: install the leak-guard commit hooks and remove the old push gate"
           " (install), or check them (status). A push from a Claude session asks the owner first")
    sp.add_argument("action", choices=["install", "status"])
    sp.add_argument("repo", nargs="?")
    sp = c("diff", cmd_diff, "Show the full diff of what a push of this repo (default: the current one) would send")
    sp.add_argument("repo", nargs="?")
    sp = c("push", cmd_push, "Push the current branch of this repo (-C <dir>) to origin; the push prompt asks the owner first")
    sp.add_argument("-C", dest="dir", help="the repo's directory (default: the current one)")
    sp.add_argument("--plan", action="store_true", help="(sessions) print the owner's question for this push, to ask with AskUserQuestion")
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
    sp = c("install", cmd_install, "Set up the store, the plugin and the guarded repos' commit hooks on this machine")
    sp.add_argument("--no-plugin", action="store_true")
    sp.add_argument("--no-gate", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    a = build().parse_args(argv)
    r = a.fn(a)
    return r if isinstance(r, int) else 0
