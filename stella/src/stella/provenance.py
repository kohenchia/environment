"""Provenance: a thing is a session's unresolved business only if that session CAUSED it.

Every earlier attempt asked "is this repo dirty / does it have unpushed commits / a deferred push" per repo or per prompt-raiser,
then patched exceptions. A repo is shared by many efforts, so that question has no right answer. This module answers the right
one: WHO made it.

  kind                        owner                                                 evidence
  ------------------------------------------------------------------------------------------------------------------
  a commit                    the session that made it                              a record written when it was made
                                                                                    (PostToolUse of `git commit` & co,
                                                                                    the post-commit git hook, or the
                                                                                    transcript, `backfill`)
  an uncommitted file         the session whose write touched it last              related.py (every transcript)
  a deferred push             the session that made the commits it defers           the commit's record, never the raiser
  an open question            the team that raised it                               state.Team.asking

`gg`, the Stop hook, `stella done`, `tyfp`, the sweep and `stella wrapup <team>` block ONLY on what the session owns
(`business`). What nobody alive owns is UNOWNED (`unowned`): one line each in Stella's attention list, the brief and the digest,
so nothing falls through the cracks, and nothing ever blocks a bystander. A commit with no record (legacy) is unowned.

A record is {sha, repo (git common dir), path, branch, session, team, patch (patch-id), ts, src}. The first record of a sha wins.
Rebase, amend and pull --rebase keep the original owner: the new commit inherits the record of a commit with the same patch-id.
A subagent's tool calls run in the lead's session, so its commits are the lead's. Stella committing on a team's behalf marks the
command `STELLA_COMMIT_FOR=<team>`.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from stella import ledger, state, wrapup
from stella.config import settings, store_dir

HISTORY = {"commit", "cherry-pick", "merge", "rebase", "am", "revert", "pull"}
FRESH_SESSION = 2 * 3600  # a session that is not a team is alive if its transcript moved this recently
RECENT_LEGACY = 24 * 3600  # an unrecorded unpushed tip this young is listed by itself (a session that just closed)
_FOR = re.compile(r"\bSTELLA_COMMIT_FOR=([\w.-]+)")


# ---------------------------------------------------------------- the store


@dataclass
class Rec:
    sha: str
    repo: str  # the git common dir, absolute
    path: str  # the checkout the commit was made in
    branch: str
    session: str
    team: str
    patch: str
    ts: float
    src: str  # post-tool | git-hook | transcript | inherit | reflog


def _file() -> Path:
    return store_dir() / "provenance.jsonl"


_mem: dict = {}


def recs() -> dict[str, Rec]:
    f = _file()
    try:
        st = f.stat()
    except OSError:
        return {}
    key = (str(f), st.st_mtime_ns, st.st_size)
    if _mem.get("key") == key:
        return _mem["recs"]
    out: dict[str, Rec] = {}
    for line in f.read_text().splitlines():
        try:
            d = json.loads(line)
            out.setdefault(d["sha"], Rec(**{k: d.get(k, "") for k in Rec.__dataclass_fields__} | {"ts": float(d.get("ts") or 0)}))
        except (ValueError, KeyError, TypeError):
            continue
    _mem.update(key=key, recs=out)
    return out


def _append(rs: list[Rec]) -> None:
    if not rs:
        return
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "a") as fh:
        for r in rs:
            fh.write(json.dumps(r.__dict__) + "\n")


def _git(repo: Path | str, *args: str, inp: str | None = None) -> str | None:
    try:
        r = subprocess.run(["git", "--no-optional-locks", "-C", str(repo), *args], capture_output=True, text=True, timeout=15,
                           input=inp)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def common(path: Path | str) -> str | None:
    d = Path(os.path.expanduser(str(path)))
    while not d.is_dir():
        if d.parent == d:
            return None
        d = d.parent
    out = _git(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return str(Path(out).resolve()) if out else None


def _main(common_dir: str | Path) -> Path:
    return Path(common_dir).parent


def patch_id(repo: Path | str, sha: str) -> str:
    shown = _git(repo, "show", "--format=", "--no-color", sha)
    if not shown:
        return ""
    out = _git(repo, "patch-id", "--stable", inp=shown + "\n")
    return out.split()[0] if out else ""


def make(repo: str, path: str, sha: str, branch: str, session: str, team: str, src: str, patch: str | None = None) -> Rec:
    return Rec(sha, repo, path, branch, session, team, patch if patch is not None else patch_id(path or repo, sha), time.time(), src)


def record(shas: list[str], path: Path, session: str, team: str, src: str, branch: str = "") -> list[Rec]:
    """Write the ownership of `shas` (made in `path`) unless a record exists already."""
    c = common(path)
    if not c or not (session or team):
        return []
    have = recs()
    new = [make(c, str(path), s, branch, session, team, src) for s in shas if s and s not in have]
    _append(new)
    return new


def record_head(path: Path) -> None:
    """The post-commit git hook: the commit just made belongs to the session whose environment runs git."""
    session, team = os.environ.get("STELLA_SESSION_ID", ""), os.environ.get("STELLA_TEAM", "")
    if not (session or team):
        return
    top = _git(path, "rev-parse", "HEAD")
    br = _git(path, "rev-parse", "--abbrev-ref", "HEAD") or ""
    if top:
        record([top], path, session, team, "git-hook", br)


# ---------------------------------------------------------------- making a record: the tool hooks


def history_dirs(cmd: str, cwd: str) -> list[tuple[Path, str, bool]]:
    """(directory, git subcommand, --amend) for each history-writing git command, following `cd` and `-C`."""
    from stella import gate

    here = Path(os.path.expanduser(cwd or os.getcwd()))
    out = []
    try:
        segs = gate._segments(cmd)
    except Exception:  # noqa: BLE001
        return out
    for seg in segs:
        if seg[0] == "cd" and len(seg) > 1:
            t = Path(os.path.expandvars(os.path.expanduser(seg[1])))
            here = t if t.is_absolute() else here / t
            continue
        sub = gate._git_sub(seg)
        if sub in HISTORY:
            where = here
            for i, tok in enumerate(seg[:-1]):
                if tok == "-C":
                    p = Path(os.path.expanduser(seg[i + 1]))
                    where = p if p.is_absolute() else here / p
                    break
            out.append((where, sub, "--amend" in seg or "--rebase" in seg))
    return out


def _refs(path: Path) -> dict[str, str]:
    out = _git(path, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads") or ""
    refs = dict(line.split(" ", 1) for line in out.splitlines() if " " in line)
    head = _git(path, "rev-parse", "HEAD")
    if head:
        refs["HEAD"] = head
    return refs


def _pre_dir() -> Path:
    return store_dir() / "provenance-pre"


def pre(tool_use_id: str, cmd: str, cwd: str) -> None:
    """PreToolUse: remember where each branch stood before a history-writing command, so the new commits are exactly the difference."""
    if not tool_use_id or "git" not in cmd:
        return
    snap = {}
    for d, _, _ in history_dirs(cmd, cwd):
        c = common(d)
        if c and d.exists():
            snap[c] = _refs(d)
    if snap:
        _pre_dir().mkdir(parents=True, exist_ok=True)
        (_pre_dir() / f"{re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id)}.json").write_text(json.dumps(snap))
        for old in _pre_dir().glob("*.json"):
            if time.time() - old.stat().st_mtime > 86400:
                old.unlink(missing_ok=True)


def post(session: str, team: str, tool_use_id: str, cmd: str, cwd: str) -> list[Rec]:
    """PostToolUse: record the commits a history-writing command made, for the session that ran it."""
    dirs = history_dirs(cmd, cwd)
    if not (dirs and (session or team)):
        return []
    m = _FOR.search(cmd)
    if m:
        team = m.group(1)
    snap_f = _pre_dir() / f"{re.sub(r'[^A-Za-z0-9_-]', '_', tool_use_id or '-')}.json"
    try:
        snap = json.loads(snap_f.read_text())
        snap_f.unlink(missing_ok=True)
    except (OSError, ValueError):
        snap = {}
    made: list[Rec] = []
    for d, sub, amend in dirs:
        c = common(d)
        if not (c and d.exists()):
            continue
        before = snap.get(c)
        made += _claim(d, c, sub, amend, session, team, before)
    return made


def _claim(d: Path, c: str, sub: str, amend: bool, session: str, team: str, before: dict | None) -> list[Rec]:
    have = recs()
    if before is None:  # no snapshot: the reflog says what the last minute of this checkout made
        out = _git(d, "reflog", "-n", "20", "--format=%H %ct %gs") or ""
        news = []
        for ln in out.splitlines():  # the newest entries only, while they are commits made in the last minute and a half
            p = ln.split(" ", 2)
            if len(p) != 3 or time.time() - float(p[1]) > 90 or not re.match(r"(commit|cherry-pick|merge|revert|am)\b", p[2]):
                break
            news.append(p[0])
        news = news[::-1]
        old_of: dict[str, str] = {}
    else:
        now = _refs(d)
        moved = [r for r, s in now.items() if before.get(r) != s]
        if not moved:
            return []
        excl = list(before.values())
        tips = [now[r] for r in moved if r != "HEAD"] or [now["HEAD"]]
        out = _git(d, "rev-list", "--reverse", *tips, "--not", "--remotes", *excl) or ""
        news = out.split()
        old_of = {}
        if amend:
            for r in moved:
                if before.get(r):
                    old_of[now[r]] = before[r]
    branch = _git(d, "rev-parse", "--abbrev-ref", "HEAD") or ""
    by_patch = {r.patch: r for r in have.values() if r.patch and r.repo == c}
    made: list[Rec] = []
    for s in news:
        if s in have:
            continue
        parents = (_git(d, "rev-list", "--parents", "-n", "1", s) or "").split()[1:]
        merge = len(parents) > 1
        if sub in {"merge", "pull"} and not merge:
            continue  # a fast-forward brings other people's commits; it makes none
        pid = "" if merge else patch_id(d, s)
        prior = have.get(old_of.get(s, "")) or (by_patch.get(pid) if pid and sub in {"rebase", "pull", "commit", "am"} else None)
        if prior and prior.sha != s:
            made.append(Rec(s, c, str(d), branch, prior.session, prior.team, pid, time.time(), "inherit"))
        elif sub in {"rebase", "pull"}:
            continue  # re-made, not made: an unrecorded commit stays unrecorded (unowned), never the rebaser's
        else:
            made.append(Rec(s, c, str(d), branch, session, team, pid, time.time(), "reflog" if before is None else "post-tool"))
    _append(made)
    return made


# ---------------------------------------------------------------- who

@dataclass
class Who:
    sessions: set[str]
    team: str | None

    def owns(self, rec: Rec | None) -> bool:
        return bool(rec) and (rec.session in self.sessions or bool(self.team and rec.team == self.team))


def own_sessions() -> set[str]:
    """Every Stella session id there has been (her sessions are marked `own` by the SessionStart hook)."""
    out = set()
    for f in (store_dir() / "sessions").glob("*.json"):
        try:
            if json.loads(f.read_text()).get("own"):
                out.add(f.stem)
        except (OSError, ValueError):
            pass
    return out


def who(st: state.State, sid: str, t: state.Team | None) -> Who:
    ids = {sid} if sid else set()
    if t:
        ids |= t.sessions | ({t.session_id} if t.session_id else set())
    if sid and sid in own_sessions():
        return Who(own_sessions(), None)
    return Who({i for i in ids if i}, t.name if t else None)


@dataclass
class Owner:
    kind: str  # team | stella | session | none
    name: str
    live: bool
    closed: dt.datetime | None = None

    def phrase(self, now: dt.datetime | None = None) -> str:
        if self.kind == "none":
            return "no record of which session made them"
        if self.live:
            return f"{self.name}'s" if self.kind == "team" else self.name
        ago = f", closed {_ago((now or ledger.now()) - self.closed)} ago" if self.closed else ", closed"
        return f"from {'the ' + self.name + ' effort' if self.kind == 'team' else 'session ' + self.name}{ago}"


def _ago(d: dt.timedelta) -> str:
    m = max(int(d.total_seconds() // 60), 0)
    return f"{m}m" if m < 60 else f"{m // 60}h" if m < 2880 else f"{m // 1440}d"


def session_live(sid: str) -> bool:
    """A session that is not a team's (a hand-opened one) is alive when its transcript moved recently."""
    from stella import resume

    p = resume.transcript(sid) if sid else None
    try:
        return bool(p) and time.time() - p.stat().st_mtime < FRESH_SESSION
    except OSError:
        return False


def owner_of(st: state.State, rec: Rec | None) -> Owner:
    if rec is None:
        return Owner("none", "", False)
    t = st.teams.get(rec.team) if rec.team else None
    if not t:
        cands = [x for x in st.teams.values() if rec.session and (rec.session in x.sessions or rec.session == x.session_id)]
        t = max(cands, key=lambda x: x.seq) if cands else None
    if t:
        return Owner("team", t.name, not t.acked, t.closed_at)
    if rec.session in own_sessions():
        return Owner("stella", "Stella", True)
    return Owner("session", (rec.session or "?")[:8], session_live(rec.session))


# ---------------------------------------------------------------- unpushed commits and who made them


@dataclass
class Branch:
    repo: Path  # the main checkout
    name: str
    tip: str
    shas: list[str]  # oldest first
    where: Path | None  # a worktree with the branch checked out

    @property
    def label(self) -> str:
        return f"{self.repo.name} {self.name}"


def _worktrees(repo: Path) -> dict[str, Path]:
    """branch -> the worktree it is checked out in; a detached worktree is listed as `HEAD@<path>`."""
    out = _git(repo, "worktree", "list", "--porcelain") or ""
    res, cur = {}, None
    for line in out.splitlines():
        if line.startswith("worktree "):
            cur = Path(line[9:])
        elif line.startswith("branch ") and cur:
            res[line[7:].removeprefix("refs/heads/")] = cur
        elif line == "detached" and cur:
            res[f"HEAD@{cur}"] = cur
    return res


def unpushed_branches(repo: Path) -> list[Branch]:
    """Local branches with commits no remote branch has. A repo without a remote has nothing to push."""
    if not _git(repo, "remote"):
        return []
    refs = _git(repo, "for-each-ref", "--format=%(refname:short)\t%(objectname)", "refs/heads") or ""
    wts = _worktrees(repo)
    out = []
    heads = [line.partition("\t")[::2] for line in refs.splitlines()]

    def ahead(h):
        return (_git(repo, "rev-list", "--reverse", "-n", "300", h[1], "--not", "--remotes") or "").split()

    with ThreadPoolExecutor(6) as pool:
        for (name, tip), shas in zip(heads, pool.map(ahead, heads)):
            if shas:
                out.append(Branch(repo, name, tip, shas, wts.get(name)))
    for name, wt in wts.items():  # commits made on a detached HEAD belong to no branch yet
        if name.startswith("HEAD@"):
            tip = _git(wt, "rev-parse", "HEAD") or ""
            shas = (_git(wt, "rev-list", "--reverse", "-n", "300", "HEAD", "--not", "--remotes") or "").split() if tip else []
            if shas and tip not in {b.tip for b in out}:  # on a branch already: that branch is the one to push
                out.append(Branch(repo, "HEAD", tip, shas, wt))
    return out


def rec_for(repo: Path, sha: str, by_patch: dict[str, Rec] | None = None) -> Rec | None:
    """The record of a commit: its own, else the record of the commit with the same patch-id (a rebase done without the hook)."""
    r = recs().get(sha)
    if r:
        return r
    if by_patch:
        pid = patch_id(repo, sha)
        if pid and pid in by_patch:
            return by_patch[pid]
    return None


def _patch_index(c: str) -> dict[str, Rec]:
    return {r.patch: r for r in recs().values() if r.patch and r.repo == c}


@dataclass
class Push:
    branch: Branch
    shas: list[str]  # the unpushed commits on it this session made

    @property
    def n(self) -> int:
        return len(self.shas)

    @property
    def command(self) -> str:
        return f"~/.local/bin/stella push --plan -C {self.branch.where}" if self.branch.where else ""


def _approved_shas() -> set[str]:
    from stella import gate

    return {e.rsplit("@", 1)[-1] for e in gate._approved()}


def _deferred_shas(st: state.State) -> set[str]:
    from stella import finish

    out = {str(ev.get("sha")) for ev in st.push_deferred if f"push-deferred:{ev.get('repo')}@{ev.get('sha')}" not in st.acked}
    return out | {k.rsplit("@", 1)[-1] for k in finish._deferred()}


def my_repos(w: Who) -> set[Path]:
    return {_main(r.repo) for r in recs().values() if w.owns(r) and Path(r.repo).exists()}


def owned_pushes(st: state.State, w: Who, skip_known: bool = True) -> list[Push]:
    """The unpushed commits THIS session made, branch by branch. Never another session's, never ones a remote branch has
    already, never ones the owner approved or deferred (those are handled where they were answered)."""
    approved = _approved_shas() if skip_known else set()
    deferred = _deferred_shas(st) if skip_known else set()
    out = []
    for repo in sorted(my_repos(w)):
        for br in unpushed_branches(repo):
            mine = [s for s in br.shas if w.owns(recs().get(s))]
            if not mine or br.tip in approved or br.tip in deferred:
                continue
            out.append(Push(br, mine))
    return out


# ---------------------------------------------------------------- deferred pushes


@dataclass
class Deferral:
    ev: dict
    key: str
    rec: Rec | None
    owner: Owner

    @property
    def what(self) -> str:
        return f"{self.ev.get('repo')} {self.ev.get('branch') or str(self.ev.get('sha'))[:7]} {str(self.ev.get('sha'))[:7]}"


def deferrals(st: state.State) -> list[Deferral]:
    """Every deferral still outstanding: its tip commit exists, is on a local branch and on no remote branch, and the owner has
    not dropped it. Its owner is whoever made the tip commit, never whoever was running when the prompt was declined."""
    out = []
    for ev in st.push_deferred:
        key = f"push-deferred:{ev.get('repo')}@{ev.get('sha')}"
        path, sha = ev.get("path"), ev.get("sha")
        if key in st.acked or not (path and sha) or not Path(path).exists():
            continue
        if wrapup._git(path, "cat-file", "-e", f"{sha}^{{commit}}") is None:
            continue  # amended, squashed or gone: the deferral is moot
        if wrapup._git(path, "branch", "-r", "--contains", sha) or not wrapup._git(path, "branch", "--contains", sha):
            continue
        c = common(path)
        rec = rec_for(Path(path), sha, _patch_index(c) if c else None)
        out.append(Deferral(ev, key, rec, owner_of(st, rec)))
    return out


def deferred_for(st: state.State, w: Who) -> list[Deferral]:
    return [d for d in deferrals(st) if w.owns(d.rec)]


# ---------------------------------------------------------------- what a session owns

@dataclass
class Business:
    pushes: list[Push] = field(default_factory=list)
    deferred: list[Deferral] = field(default_factory=list)
    dirty: list[tuple[Path, list[str]]] = field(default_factory=list)  # (repo, files this session wrote last)
    left: list[tuple[str, object]] = field(default_factory=list)  # (repo name, related.Result): dirty, not its business

    def __bool__(self) -> bool:
        return bool(self.pushes or self.deferred or self.dirty)


def business(st: state.State, sid: str, t: state.Team | None) -> Business:
    from stella import related

    w = who(st, sid, t)
    b = Business(pushes=owned_pushes(st, w), deferred=deferred_for(st, w))
    ctx = related.context(st, sid, t)
    for root in sorted(related.footprint(ctx)):
        res = related.check(root, None, ctx)
        if res.blocking:
            b.dirty.append((root, res.blocking))
        b.left.append((root.name, res))
    return b


# ---------------------------------------------------------------- history: reading the transcripts

_COMMITTED = re.compile(r"^\[(?P<br>[^\]\s]+)(?: \(root-commit\))? (?P<sha>[0-9a-f]{7,40})\]", re.M)
_MAKES = re.compile(r"\bgit\b[^\n]*\b(commit|cherry-pick|am|revert)\b")


def backfill(days: int = 45) -> list[Rec]:
    """Attribute commits made before records existed, from the transcripts: a Bash `git commit` whose result prints `[branch sha]`.
    The repo is the checkout the command ran in. Anything it cannot place stays unrecorded (unowned)."""
    from stella import related

    have = dict(recs())
    made: list[Rec] = []
    for f, sid in related.transcript_files(time.time() - days * 86400):
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        if "git" not in text or "[" not in text:
            continue
        cmds: dict[str, tuple[str, str, str]] = {}
        for line in text.splitlines():
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            content = (ev.get("message") or {}).get("content")
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("name") == "Bash":
                    c = (b.get("input") or {}).get("command") or ""
                    if _MAKES.search(c):
                        cmds[b.get("id", "")] = (c, ev.get("cwd") or "", ev.get("timestamp") or "")
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in cmds:
                    c, cwd, ts = cmds[b["tool_use_id"]]
                    res = b.get("content")
                    res = res if isinstance(res, str) else " ".join(x.get("text", "") for x in res or [] if isinstance(x, dict))
                    for m in _COMMITTED.finditer(res):
                        made += _place(m.group("sha"), m.group("br"), c, cwd, sid, have, ts)
    _append(made)
    return made


def _place(prefix: str, branch: str, cmd: str, cwd: str, sid: str, have: dict, ts: str) -> list[Rec]:
    from stella import related

    places = [d for d, _, _ in history_dirs(cmd, cwd)] or [Path(cwd)]
    for d in places:
        if not d.exists():
            continue
        full = _git(d, "rev-parse", "--verify", f"{prefix}^{{commit}}")
        c = common(d)
        if full and c:
            if full in have:
                return []
            r = Rec(full, c, str(d), branch, sid, "", patch_id(d, full), related._ts(ts) or 0.0, "transcript")
            have[full] = r
            return [r]
    return []


# ---------------------------------------------------------------- unowned: business nobody alive owns


@dataclass
class Item:
    key: str
    text: str


def _universe(st: state.State) -> list[Path]:
    seen: dict[str, Path] = {}
    base = settings().repos_dir
    cands = []
    if base.is_dir():
        cands += [p for p in sorted(base.iterdir()) if p.is_dir() and not p.name.endswith("-wt") and (p / ".git").exists()]
    cands += [_main(r.repo) for r in recs().values()]
    cands += [Path(ev["path"]) for ev in st.push_deferred if ev.get("path")]
    cands += [Path(t.directory) for t in st.teams.values() if t.directory]
    for p in cands:
        c = common(p) if p.exists() else None
        if c:
            seen.setdefault(c, _main(c))
    return list(seen.values())


def _push_items(st: state.State, now: dt.datetime) -> tuple[list[Item], int, dict[str, int]]:
    """Unowned unpushed commits. Listed by themselves when there is evidence they are live business: a record whose owner is gone,
    a deferral, or a tip made in the last day. The rest of the old backlog (branches nobody has touched for weeks, no record)
    is one summary line."""
    items: list[Item] = []
    legacy, repos_legacy = 0, {}
    deferred = {d.ev.get("sha"): d for d in deferrals(st)}
    for repo in _universe(st):
        c = common(repo) or ""
        bp = _patch_index(c)
        for br in unpushed_branches(repo):
            loose: dict[str, list[str]] = {}  # owner phrase -> shas nobody alive owns
            recorded = False
            for s in br.shas:
                rec = rec_for(repo, s, bp) if s not in recs() and len(br.shas) <= 12 else recs().get(s)
                o = owner_of(st, rec)
                if o.live:
                    continue
                recorded = recorded or o.kind != "none"
                loose.setdefault(o.phrase(now), []).append(s)
            if not loose:
                continue
            n = sum(len(v) for v in loose.values())
            dfr = deferred.get(br.tip)
            young = False
            try:
                young = time.time() - float(_git(repo, "log", "-1", "--format=%ct", br.tip) or 0) < RECENT_LEGACY
            except ValueError:
                pass
            if not (recorded or dfr or young):
                legacy += n
                repos_legacy[repo.name] = repos_legacy.get(repo.name, 0) + 1
                continue
            who_ = "; ".join(loose) if not dfr else "; ".join(loose) + f"; the push was declined once"
            cmd = f"`stella push --plan -C {br.where}`" if br.where else f"branch not checked out: `wta` it first"
            items.append(Item(f"unowned-push:{repo.name}@{br.tip}",
                              f"unowned: {br.label} {n} unpushed commit{'s' if n != 1 else ''} ({who_}): push ({cmd}) / drop (`stella ack unowned-push:{repo.name}@{br.tip}`)?"))
    return items, legacy, repos_legacy


def _dirty_items(st: state.State, now: dt.datetime) -> list[Item]:
    """Uncommitted files whose last writer is gone: closed sessions' files; files nobody is known to have written and that are young."""
    from stella import related

    idx = related.index()
    wts = [wt for repo in _universe(st) for wt in dict.fromkeys([repo, *_worktrees(repo).values()]) if wt.is_dir()]
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda wt: related.classify(wt, None, idx), wts))
    items: list[Item] = []
    for wt, entries in zip(wts, found):
        gone: dict[str, list[str]] = {}
        for rel, kind, w in entries:
            if kind == "never":
                continue
            if w:
                t = next((x for x in st.teams.values() if w[0] in x.sessions or w[0] == x.session_id), None)
                if (t and not t.acked) or w[0] in own_sessions() or (not t and session_live(w[0])):
                    continue  # a live owner has it
                who_ = f"from the {t.name} effort, closed {_ago(now - t.closed_at)} ago" if t and t.closed_at else (
                    f"from the {t.name} effort, closed" if t else f"from session {w[0][:8]}, gone")
            else:
                if time.time() - related.newest(wt / rel) > 7 * 86400:
                    continue  # an old stray: not worth a line
                who_ = "no known writer"
            gone.setdefault(who_, []).append(rel)
        for who_, files in gone.items():
            shown = ", ".join(files[:3]) + (f" and {len(files) - 3} more" if len(files) > 3 else "")
            items.append(Item(f"unowned-dirty:{wt.name}:{who_}:{len(files)}",
                              f"unowned: {wt.name} {len(files)} uncommitted file{'s' if len(files) != 1 else ''} ({who_}): {shown}: commit? / discard?"))
    return items


def _cache_ttl(max_age: float | None) -> float:
    env = os.environ.get("STELLA_UNOWNED_TTL")
    return float(env) if env is not None else (max_age if max_age is not None else 1800.0)


def unowned(st: state.State, now: dt.datetime | None = None, max_age: float | None = None) -> list[state.Attention]:
    """The one-line-each list of business no live session owns, from the same ownership the blockers use. Computing it walks every
    repo and worktree, so the scheduler refreshes it each minute (`refresh`) and readers take the cache while it is young."""
    now = now or ledger.now()
    cache = store_dir() / "unowned.json"
    try:
        c = json.loads(cache.read_text())
        if time.time() - c["at"] < _cache_ttl(max_age):
            return [state.Attention(i["key"], i["seq"], now, i["text"]) for i in c["items"] if i["key"] not in st.acked]
    except (OSError, ValueError, KeyError):
        pass
    return [a for a in _compute(st, now) if a.key not in st.acked]


def _compute(st: state.State, now: dt.datetime) -> list[state.Attention]:
    pushes, legacy, repos = _push_items(st, now)
    items = pushes + _dirty_items(st, now)
    if legacy:
        where = ", ".join(f"{n} in {r}" for r, n in sorted(repos.items(), key=lambda x: -x[1])[:4])
        items.append(Item("unowned-legacy",
                          f"unowned, old: {legacy} unpushed commits on {sum(repos.values())} local branches with no ownership record ({where}): `stella provenance unowned` lists them"))
    out = [state.Attention(i.key, st.last_seq, now, i.text) for i in items]
    try:
        (store_dir() / "unowned.json").write_text(json.dumps({"at": time.time(), "seq": st.last_seq,
                                                              "items": [{"key": a.key, "seq": a.seq, "text": a.text} for a in out]}))
    except OSError:
        pass
    return out


def refresh(st: state.State | None = None) -> None:
    """Scheduler, each minute: record the owners of recent commits the hooks missed, and refresh the unowned list."""
    st = st or state.fold()
    marker = store_dir() / "provenance.backfill"
    try:
        stale = time.time() - marker.stat().st_mtime > 600
    except OSError:
        stale = True
    if stale:
        backfill(3)
        marker.write_text(str(time.time()))
    try:
        fresh = time.time() - json.loads((store_dir() / "unowned.json").read_text())["at"] < 300
    except (OSError, ValueError, KeyError):
        fresh = False
    if not fresh:  # walking every repo and worktree is not cheap: every five minutes is often enough
        _compute(st, ledger.now())


def attention(st: state.State, now: dt.datetime | None = None, max_age: float | None = None) -> list[state.Attention]:
    """The owner's list: the ledger's items, with a deferred push shown as UNOWNED when nobody alive made its commits, plus the
    other unowned business."""
    now = now or ledger.now()
    items = st.attention(now)
    keep = []
    gone = {d.key for d in deferrals(st) if not d.owner.live}
    for a in items:
        if a.key in gone:
            continue  # shown below as an unowned item
        keep.append(a)
    return sorted(keep + unowned(st, now, max_age), key=lambda a: a.seq, reverse=True)
