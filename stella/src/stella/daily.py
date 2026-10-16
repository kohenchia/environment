"""The day's work, read from every Claude Code transcript, and the jobs that use it.

* `digest(date)`: a bounded summary of every session active that day (what the
  owner asked, how each session ended), written to the store.
* `run_daily(date)`: a headless session turns the digest into the daily log. An
  extension supplies the prompt (where the log lives and which skill writes it);
  without one, it writes a journal entry into the store.
* `run_nightly(date)`: denylist rebuild, leak sweep, push audit, and a reflection
  that writes the morning digest and learning proposals.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

from stella import extensions, gate, leak, ledger, notify
from stella.config import CALL, settings, store_dir

MARK = "[stella-job]"
_COMMAND = re.compile(r"<command-name>(.*?)</command-name>.*?(?:<command-args>(.*?)</command-args>)?", re.S)


def transcripts_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("STELLA_TRANSCRIPTS", "~/.claude/projects")))


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _clip(s: str, n: int) -> str:
    s = s.strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def sessions_on(date: dt.date) -> list[dict]:
    start = dt.datetime.combine(date, dt.time()).astimezone()
    end = start + dt.timedelta(days=1)
    out = []
    root = transcripts_dir()
    if not root.exists():
        return out
    for f in root.glob("*/*.jsonl"):
        try:
            if dt.datetime.fromtimestamp(f.stat().st_mtime).astimezone() < start:
                continue
        except OSError:
            continue
        title, cwd, prompts, replies = None, None, [], []
        try:
            lines = f.open(errors="replace")
        except OSError:
            continue
        for line in lines:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = d.get("type")
            if t in {"custom-title", "agent-name"}:
                title = d.get("customTitle") or d.get("agentName") or title
                continue
            ts = d.get("timestamp")
            if not ts:
                continue
            try:
                when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
            except ValueError:
                continue
            if not (start <= when < end):
                continue
            cwd = d.get("cwd") or cwd
            msg = d.get("message") or {}
            if t == "user" and not d.get("isMeta") and not d.get("toolUseResult"):
                text = _text_of(msg.get("content"))
                if text and not text.startswith(("<local-command-stdout", "<local-command-caveat", "<system-reminder", "[Request interrupted")):
                    cmd = _COMMAND.search(text)
                    if cmd:
                        text = (cmd.group(1) + " " + (cmd.group(2) or "")).strip()
                        if prompts and prompts[-1][1] == text:
                            continue
                    prompts.append((when, text))
            elif t == "assistant":
                text = _text_of(msg.get("content"))
                if text:
                    replies.append((when, text))
        if not prompts:
            continue
        if prompts[0][1].startswith(MARK):
            continue
        out.append({"file": str(f), "session": f.stem, "title": title, "cwd": cwd,
                    "first": prompts[0][0], "last": max(prompts[-1][0], replies[-1][0] if replies else prompts[-1][0]),
                    "prompts": prompts, "replies": replies})
    return sorted(out, key=lambda s: s["first"])


def digest(date: dt.date, budget: int = 80_000) -> Path:
    ss = sessions_on(date)
    per = max(budget // max(len(ss), 1), 1500)
    lines = [f"# Work digest for {date:%A %Y-%m-%d}", "",
             f"{len(ss)} sessions. For each: what {settings().owner} asked (verbatim, clipped), and how the session ended.", ""]
    for s in ss:
        head = f"## {s['title'] or s['session'][:8]}  ({s['cwd'] or '?'}, {s['first']:%H:%M}–{s['last']:%H:%M})"
        body = [head, f"transcript: {s['file']}", "", "Asked:"]
        used = 0
        for when, text in s["prompts"]:
            item = f"- {when:%H:%M} {_clip(' '.join(text.split()), 500)}"
            if used + len(item) > per * 0.6:
                body.append(f"- … {len(s['prompts'])} prompts in total")
                break
            body.append(item)
            used += len(item)
        if s["replies"]:
            body += ["", "Last reply:", _clip(s["replies"][-1][1], int(per * 0.35))]
        lines += body + [""]
    d = store_dir() / "digests"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{date:%Y-%m-%d}.md"
    p.write_text("\n".join(lines))
    return p


DEFAULT_DAILY = """{mark} daily log for {date}.
Read the work digest at {digest}. Write a concise journal entry of what {owner} did on {date}: one line
per piece of work, with any links or identifiers that appear in the digest (never invent one), then a
short "Learned" list of anything that took real effort to figure out. Write it to {journal}. Do not ask
questions; this run is unattended."""


def _daily_prompt(date: dt.date, digest_path: Path) -> str:
    template = DEFAULT_DAILY
    for ext in extensions.load():
        f = ext.file("daily")
        if f and f.exists():
            template = f.read_text()
    journal = store_dir() / "journal" / f"{date:%Y-%m-%d}.md"
    journal.parent.mkdir(parents=True, exist_ok=True)
    return template.format(mark=MARK, date=f"{date:%Y-%m-%d}", digest=digest_path, owner=settings().owner,
                           journal=journal, stella=CALL)


def headless(prompt: str, log: Path, timeout: int = 1800, model: str | None = None) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [settings().claude_bin, "-p", prompt, "--permission-mode", "bypassPermissions"]
    if model:
        cmd += ["--model", model]
    with log.open("w") as out:
        try:
            r = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, timeout=timeout,
                               env={**os.environ, "STELLA_HEADLESS": "1"}, cwd=str(Path.home()))
            return r.returncode
        except subprocess.TimeoutExpired:
            out.write("\nTIMEOUT\n")
            return 124


def run_daily(date: dt.date) -> int:
    if not sessions_on(date):
        ledger.append("note", by="scheduler", text=f"daily log for {date:%Y-%m-%d}: no sessions, nothing to log")
        return 0
    p = digest(date)
    rc = headless(_daily_prompt(date, p), store_dir() / "runs" / f"daily-{date:%Y-%m-%d}.log")
    ledger.append("note", by="scheduler", text=f"daily log for {date:%Y-%m-%d}: {'written' if rc == 0 else f'FAILED (exit {rc})'}")
    if rc != 0:
        ledger.append("alert", by="scheduler", key=f"daily:{date}", text=f"daily log for {date} failed; see runs/daily-{date}.log")
    notify.notify("Stella", f"Daily log for {date:%Y-%m-%d} {'written' if rc == 0 else 'FAILED'}")
    return rc


REFLECT = """{mark} nightly reflection for {date}.
You are Stella's reflection pass. Read: the work digest {digest}; the priorities {priorities}; the canon
{canon}; and `{stella} log --since-days 1`. Then:
1. Write the morning digest to {morning} (under 40 lines): what {owner} worked on, how it compares with
   the priorities (name any drift plainly, with the evidence), what finished, what is waiting on {owner}.
2. For each place where {owner}'s decisions or corrections today reveal a judgment the canon lacks or
   gets wrong, record a proposal: `{stella} propose --title "..." --evidence "..." --body "..."`.
   At most 5. Each must cite evidence from the digest. Never edit the canon yourself.
Do not ask questions; this run is unattended."""


def run_nightly(date: dt.date) -> list[str]:
    report: list[str] = []
    report += leak.rebuild()
    g = leak.guard()
    if g.configured:
        try:
            rules = leak.load_rules(g)
            for root in g.protect:
                if not root.exists():
                    continue
                hits = leak.scan_tree(root, rules)
                key = f"leak:{root.name}"
                if hits:
                    sample = "; ".join(f"{h.where}:{h.line} {h.term!r}" for h in hits[:5])
                    ledger.append("alert", by="scheduler", key=key,
                                  text=f"leak sweep: {len(hits)} hit(s) in {root.name}: {sample}")
                    notify.notify("Stella leak sweep", f"{len(hits)} hit(s) in {root.name}")
                report.append(f"leak sweep {root.name}: {len(hits)} hit(s)")
        except leak.DenylistMissing as e:
            ledger.append("alert", by="scheduler", key="leak:denylist", text=f"denylist missing: {e}")
            report.append(f"denylist missing: {e}")
    report += gate_audit()
    p = digest(date)
    morning = store_dir() / "digests" / f"{date + dt.timedelta(days=1):%Y-%m-%d}-morning.md"
    prompt = REFLECT.format(mark=MARK, date=date, digest=p, priorities=store_dir() / "priorities.md",
                            canon=store_dir() / "canon.md", stella=CALL, owner=settings().owner, morning=morning)
    rc = headless(prompt, store_dir() / "runs" / f"reflect-{date:%Y-%m-%d}.log")
    report.append(f"reflection: exit {rc}")
    if rc == 0 and morning.exists():
        ledger.append("alert", by="scheduler", key=f"morning:{morning.stem}", text=f"morning digest ready: {morning}")
    ledger.append("note", by="scheduler", text=f"nightly for {date}: " + "; ".join(report))
    return report


def gate_audit() -> list[str]:
    """Any remote branch head of a guarded repo that no approved push produced is an alert."""
    out = []
    pushed = {e.get("sha") for e in ledger.events() if e["type"] == "push"}
    base_file = store_dir() / "gate-baseline.json"
    baseline = json.loads(base_file.read_text()) if base_file.exists() else {}
    for root in gate.guarded_repos():
        subprocess.run(["git", "-C", str(root), "fetch", "--quiet", "--all"], capture_output=True, timeout=120)
        refs = subprocess.run(["git", "-C", str(root), "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes"],
                              capture_output=True, text=True).stdout.splitlines()
        for line in refs:
            ref, sha = line.split()
            if ref.endswith("/HEAD"):
                continue
            ok = sha in pushed or baseline.get(str(root), {}).get(ref) == sha
            if not ok and baseline.get(str(root), {}).get(ref):
                ok = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha,
                                     baseline[str(root)][ref]]).returncode == 0
            if not ok:
                ledger.append("alert", by="scheduler", key=f"gate:{root.name}:{ref}",
                              text=f"{root.name} {ref} is at {sha[:7]}, which no approved push produced")
                out.append(f"gate audit {root.name} {ref}: UNAPPROVED {sha[:7]}")
        out.append(f"gate audit {root.name}: {len(refs)} refs checked")
    return out


def record_baseline() -> None:
    data = {}
    for root in gate.guarded_repos():
        refs = subprocess.run(["git", "-C", str(root), "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes"],
                              capture_output=True, text=True).stdout.splitlines()
        data[str(root)] = dict(line.split() for line in refs)
    p = store_dir() / "gate-baseline.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=1))
