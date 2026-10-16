"""Stella's judgment and how it improves.

* `canon.md`: numbered principles (J-NN), each with the evidence behind it. It is
  the owner's written judgment; the Decide procedure applies it.
* `cases.toml`: past decisions the owner made, replayed by `stella eval`.
* proposals: what observation suggests should change. Only the owner accepts one;
  the curator agent then edits the canon and adds a case.
* corrections: the owner teaching Stella directly ("remember…", "that's wrong
  because…"). They skip the proposal queue because the owner is the evidence.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import tomllib
from pathlib import Path

from stella import ledger
from stella.config import HEADLESS_ARGS, settings, store_dir

CANON_TEMPLATE = """# Stella canon

The owner's judgment, written down. Each principle has an ID, a one-line claim, the
reasoning, and the evidence (a quote, a decision, a correction, with its date). The
curator agent edits this file; nothing else does. Never delete or rewrite an
accepted principle without the owner saying so.

## How to decide

1. Find the principles that apply. Quote their IDs.
2. Say what the owner would do, and how sure you are (high / medium / low).
3. If no principle applies or they conflict, say so and ask the owner. Their answer
   becomes a correction, then a principle.

## Principles

<!-- J-01 · <claim>
Why: …
Evidence: <date> <source> -->
"""

CASES_TEMPLATE = """# Decisions the owner actually made, replayed by `stella eval`.
# [[case]]
# id = "C-01"
# situation = "What Stella was asked or faced, with enough context to decide."
# expected = "What the owner decided, and the reason they gave."
# principles = ["J-01"]
"""

PRIORITIES_TEMPLATE = """# Priorities

The 3–5 outcomes that matter most right now, in order. Direction, not tasks: the
task list lives elsewhere. Stella compares each day's work with this list.

Updated: (never; ask the owner)

1.

## Say no to

-
"""


def init_store() -> list[str]:
    d = store_dir()
    d.mkdir(parents=True, exist_ok=True)
    made = []
    for name, body in (("canon.md", CANON_TEMPLATE), ("cases.toml", CASES_TEMPLATE),
                       ("priorities.md", PRIORITIES_TEMPLATE), ("knowledge.md", "# Things the owner told Stella to remember\n")):
        p = d / name
        if not p.exists():
            p.write_text(body)
            made.append(name)
    (d / "proposals").mkdir(exist_ok=True)
    gi = d / ".gitignore"
    if not gi.exists():
        gi.write_text("ledger/\nsessions/\napprovals/\nlaunch/\nruns/\ndigests/\nevals/\njournal/\n*.lock\n*.pid\nscheduler.json\ngate-baseline.json\n")
    if not (d / ".git").exists():
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        made.append("git repo (local only, never pushed)")
    return made


def commit_store(message: str) -> None:
    d = store_dir()
    subprocess.run(["git", "-C", str(d), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(d), "commit", "-q", "-m", message], capture_output=True)


# ---------------------------------------------------------------- proposals


def _proposals() -> Path:
    p = store_dir() / "proposals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def propose(title: str, evidence: str, body: str) -> str:
    existing = sorted(_proposals().glob("P-*.md"))
    n = max((int(re.findall(r"\d+", f.stem)[0]) for f in existing), default=0) + 1
    pid = f"P-{n:03d}"
    (_proposals() / f"{pid}.md").write_text(
        f"---\nid: {pid}\nstatus: open\ncreated: {dt.date.today()}\n---\n# {title}\n\n{body}\n\n## Evidence\n\n{evidence}\n"
    )
    ledger.append("alert", by="cli", key=f"proposal:{pid}", text=f"proposal {pid}: {title} (`stella accept {pid}` / `stella reject {pid}`)")
    return pid


def proposals(status: str | None = "open") -> list[tuple[str, str, str]]:
    out = []
    for f in sorted(_proposals().glob("P-*.md")):
        text = f.read_text()
        st = re.search(r"^status: (\w+)", text, re.M)
        title = re.search(r"^# (.+)$", text, re.M)
        s = st.group(1) if st else "?"
        if status is None or s == status:
            out.append((f.stem, s, title.group(1) if title else ""))
    return out


def resolve(pid: str, status: str, note: str = "") -> Path:
    f = _proposals() / f"{pid}.md"
    if not f.exists():
        raise SystemExit(f"no proposal {pid}")
    text = re.sub(r"^status: \w+", f"status: {status}", f.read_text(), count=1, flags=re.M)
    if note:
        text += f"\n## {status.capitalize()} {dt.date.today()}\n\n{note}\n"
    f.write_text(text)
    ledger.append("clear_alert", by="cli", key=f"proposal:{pid}")
    ledger.append("decision", by="cli", text=f"proposal {pid} {status}" + (f": {note}" if note else ""))
    commit_store(f"proposal {pid} {status}")
    return f


# ---------------------------------------------------------------- eval


def cases() -> list[dict]:
    p = store_dir() / "cases.toml"
    if not p.exists():
        return []
    return tomllib.loads(p.read_text()).get("case", [])


def run_eval(only: list[str] | None = None, model: str = "sonnet") -> dict:
    canon = store_dir() / "canon.md"
    results = {}
    for c in cases():
        if only and c["id"] not in only:
            continue
        decide = subprocess.run(
            [settings().query_bin, "-p",
             f"[stella-job] You are Stella. Read the canon at {canon} and apply its 'How to decide' procedure to this "
             f"situation. Do not ask questions.\n\nSituation: {c['situation']}\n\nAnswer with: Decision, Confidence, Principles.",
             "--model", model, *HEADLESS_ARGS],
            capture_output=True, text=True, timeout=600, env=_env())
        answer = decide.stdout.strip()
        grade = subprocess.run(
            [settings().query_bin, "-p",
             "[stella-job] Grade whether the ANSWER reaches the same decision as EXPECTED, for the same essential reason. "
             "Reply with PASS or FAIL on the first line, then one sentence.\n\n"
             f"EXPECTED: {c['expected']}\n\nANSWER: {answer}", "--model", model, *HEADLESS_ARGS],
            capture_output=True, text=True, timeout=300, env=_env())
        verdict = grade.stdout.strip()
        results[c["id"]] = {"pass": verdict.upper().startswith("PASS"), "answer": answer[:2000], "grade": verdict[:500]}
    d = store_dir() / "evals"
    d.mkdir(parents=True, exist_ok=True)
    prev = sorted(d.glob("*.json"))
    previous = json.loads(prev[-1].read_text()) if prev else {}
    out = d / f"{dt.datetime.now():%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(results, indent=1))
    regressions = [k for k, v in results.items() if not v["pass"] and previous.get(k, {}).get("pass")]
    return {"file": str(out), "passed": sum(v["pass"] for v in results.values()), "total": len(results),
            "regressions": regressions}


def _env() -> dict:
    from stella import passenv
    from stella.config import headless_env

    return passenv.apply(headless_env())
