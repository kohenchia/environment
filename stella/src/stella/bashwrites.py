"""What a Bash command writes, so the leak guard decides on what is written and where, never on the words.

`writes(command, cwd)` returns one `Write` per file or repo the command writes into whose location is
certain: a redirect (`>`, `>>`), `tee`, `sed -i`/`perl -i`, `cp`/`mv`/`ln`/`install`/`mkdir`/`touch`, a
`git commit`-like command, `patch`, and an interpreter (`python -c`, `node -e`, a heredoc) that writes a file
whose literal path it names. A read (grep, cat, ls, git log, find, ...) yields nothing. Anything the parser
cannot pin down (a variable in the path, an unbalanced quote) yields nothing: it fails open.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

_WRAPPERS = {"env", "command", "sudo", "time", "exec", "nohup", "nice", "builtin"}
_SHELLS = {"bash", "sh", "zsh", "dash"}
_INTERPRETERS = {"python", "python3", "node", "perl", "ruby", "deno", "bun"}
_GIT_VALUE_OPTS = {"-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env"}
_GIT_TEXT_SUBS = {"commit", "tag", "merge", "stash", "notes", "am", "apply"}
_GIT_READ_SUBSUBS = {"list", "show", "--list", "-l"}
_HEREDOC = re.compile(r"<<(-?)[ \t]*(['\"]?)([\w.-]+)\2")
_PUNCT = set("();<>|&")
_CODE_WRITES = re.compile(
    r"\.write\w*\(|\bopen\([^)]*['\"][wax]|writeFile|appendFile|createWriteStream|shutil\.|os\.(rename|replace)"
    r"|File\.write|\bFileUtils\b|\bcp\b|\bmv\b|\btee\b|>"
)
_STRING = re.compile(r"""(['"])(.+?)\1""")
_PATHISH = re.compile(r"/|^~|\.\w{1,6}$")
_MAX_DEPTH = 3


@dataclass
class Write:
    targets: list[Path]  # any one inside a protected repo makes this a write into it
    text: str = ""  # the content being written
    paths: bool = False  # the target's own name is part of what is written


@dataclass
class _Ctx:
    here: Path | None
    out: list[Write] = field(default_factory=list)


def writes(command: str, cwd: str, _depth: int = 0) -> list[Write]:
    try:
        here = Path(cwd).resolve()
    except (OSError, RuntimeError):
        here = None
    ctx = _Ctx(here)
    try:
        _run(command, ctx, _depth)
    except (ValueError, IndexError):  # unparseable: not certain of anything
        return []
    return ctx.out


def _prepare(cmd: str) -> tuple[str, list[str]]:
    """Newlines outside quotes become `;`, and each heredoc body is lifted out (in order of appearance)."""
    out: list[str] = []
    bodies: list[str] = []
    pending: list[tuple[str, bool]] = []
    i, n, q = 0, len(cmd), None
    while i < n:
        c = cmd[i]
        if q:
            out.append(c)
            if c == "\\" and q == '"' and i + 1 < n:
                out.append(cmd[i + 1])
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            if cmd[i + 1] == "\n":
                out.append(" ")
            else:
                out.append(cmd[i:i + 2])
            i += 2
            continue
        if c in "'\"":
            q = c
        elif c == "#" and (i == 0 or cmd[i - 1] in " \t\n;|&("):
            while i < n and cmd[i] != "\n":
                i += 1
            continue
        elif cmd.startswith("<<", i) and not cmd.startswith("<<<", i):
            m = _HEREDOC.match(cmd, i)
            if m:
                pending.append((m.group(3), bool(m.group(1))))
                out.append(" << _ ")
                i = m.end()
                continue
        elif c == "\n":
            i += 1
            for word, dash in pending:
                lines = []
                while i < n:
                    j = cmd.find("\n", i)
                    line = cmd[i:] if j < 0 else cmd[i:j]
                    i = n if j < 0 else j + 1
                    if (line.lstrip("\t") if dash else line).strip() == word:
                        break
                    lines.append(line)
                bodies.append("\n".join(lines))
            pending = []
            out.append(" ; ")
            continue
        out.append(c)
        i += 1
    return "".join(out), bodies


def _tokens(cmd: str) -> list[str]:
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split, lex.commenters = True, ""
    return list(lex)


def _is_punct(tok: str) -> bool:
    return bool(tok) and all(ch in _PUNCT for ch in tok)


def _is_redirect(tok: str) -> bool:
    return _is_punct(tok) and ("<" in tok or ">" in tok)


def _run(command: str, ctx: _Ctx, depth: int) -> None:
    text, bodies = _prepare(command)
    body_iter = iter(bodies)
    lits: list[str] = []  # literal text flowing down the current pipeline
    seg: list[str] = []
    tokens = _tokens(text)
    for tok in tokens + [";"]:
        if _is_punct(tok) and not _is_redirect(tok):
            if seg:
                lit = _segment(seg, body_iter, ctx, lits, depth)
                lits = lits + lit if tok in {"|", "|&"} else []
                seg = []
            continue
        seg.append(tok)


def _expand(tok: str) -> str | None:
    home = os.path.expanduser("~")
    tok = tok.replace("${HOME}", home).replace("$HOME", home)
    if any(ch in tok for ch in "$`*?[{"):
        return None
    return os.path.expanduser(tok)


def _path(tok: str, here: Path | None) -> Path | None:
    tok = _expand(tok)
    if not tok:
        return None
    p = Path(tok)
    if not p.is_absolute():
        if here is None:
            return None
        p = here / p
    try:
        return p.resolve()
    except (OSError, RuntimeError):
        return None


def _paths(toks: list[str], here: Path | None) -> list[Path]:
    return [p for p in (_path(t, here) for t in toks) if p]


def _segment(seg: list[str], bodies, ctx: _Ctx, lits: list[str], depth: int) -> list[str]:
    """Record the writes of one simple command; return the literal text it feeds into a pipe."""
    words: list[str] = []
    redirects: list[str | None] = []
    stdin: list[str] = []
    i = 0
    while i < len(seg):
        t = seg[i]
        nxt = seg[i + 1] if i + 1 < len(seg) else None
        if not _is_redirect(t):
            words.append(t)
            i += 1
        elif t.startswith("<<<"):
            stdin.append(nxt or "")
            i += 2
        elif t.startswith("<<"):
            stdin.append(next(bodies, ""))
            i += 2
        elif ">" in t:
            if nxt is not None and not (t.endswith("&") and (nxt.isdigit() or nxt == "-")) and nxt != "/dev/null":
                redirects.append(nxt)
            i += 2
        else:  # `<` and `<&`
            i += 2
    while words and (re.fullmatch(r"\w+=.*", words[0]) or words[0] in _WRAPPERS):
        wrapped = words.pop(0) in _WRAPPERS
        while wrapped and words and (words[0].startswith("-") or re.fullmatch(r"\w+=.*", words[0])):
            words.pop(0)
    name = os.path.basename(words[0]) if words else ""
    args = words[1:]
    here = ctx.here
    literal = list(stdin)
    if name in {"echo", "printf"}:
        literal.append(" ".join(args))
    flow = lits + literal  # what reaches this command's output or stdin write
    base = "\n".join(flow)

    for r in redirects:
        for t in _paths([r], here):
            ctx.out.append(Write([t], base, paths=True))

    if name in {"cd", "pushd"}:
        dest = _path(args[0], here) if args and not args[0].startswith("-") else (Path.home() if not args else None)
        ctx.here = dest
    elif name == "tee":
        ctx.out.append(Write(_paths([a for a in args if not a.startswith("-")], here), base, paths=True))
    elif name == "sed" or (name == "perl" and any(re.fullmatch(r"-[pnlaw0]*i\S*", a) for a in args)):
        _inplace(name, args, here, ctx)
    elif name in {"cp", "mv", "ln", "install"}:
        dest = None
        pos = []
        j = 0
        while j < len(args):
            a = args[j]
            if a in {"-t", "--target-directory"} and j + 1 < len(args):
                dest = args[j + 1]
                j += 2
                continue
            if a.startswith("--target-directory="):
                dest = a.split("=", 1)[1]
            elif not a.startswith("-"):
                pos.append(a)
            j += 1
        if dest is None and len(pos) >= 2:
            dest = pos[-1]
        if dest:
            ctx.out.append(Write(_paths([dest], here), "", paths=True))
    elif name in {"mkdir", "touch"}:
        ctx.out.append(Write(_paths([a for a in args if not a.startswith("-")], here), "", paths=True))
    elif name == "patch":
        d = [args[j + 1] for j, a in enumerate(args[:-1]) if a == "-d"]
        ctx.out.append(Write(_paths(d, here) or ([here] if here else []), base))
    elif name == "git":
        _git(args, base, here, ctx)
    elif name in _SHELLS and depth < _MAX_DEPTH:
        inner = [args[j + 1] for j, a in enumerate(args[:-1]) if a == "-c"] + stdin
        for code in inner:
            sub = _Ctx(ctx.here)
            _run(code, sub, depth + 1)
            ctx.out.extend(sub.out)
    elif re.fullmatch(r"(python|node|perl|ruby|deno|bun)[\d.]*", name):
        codes = [args[j + 1] for j, a in enumerate(args[:-1]) if a in {"-c", "-e", "-E", "--eval", "-p"}] + stdin
        for code in codes:
            if not _CODE_WRITES.search(code):
                continue
            lits_ = [m.group(2) for m in _STRING.finditer(code) if _PATHISH.search(m.group(2))]
            targets = _paths(lits_, here)
            if targets:
                ctx.out.append(Write(targets, code, paths=False))
    return literal


def _inplace(name: str, args: list[str], here: Path | None, ctx: _Ctx) -> None:
    inplace = False
    scripts: list[str] = []
    pos: list[str] = []
    j = 0
    while j < len(args):
        a = args[j]
        if a in {"-e", "--expression", "-f", "--file"}:
            if j + 1 < len(args):
                scripts.append(args[j + 1])
            j += 2
            continue
        if a.startswith("--expression="):
            scripts.append(a.split("=", 1)[1])
        elif a == "--in-place" or a.startswith("--in-place="):
            inplace = True
        elif re.fullmatch(r"-[pnlaw0]*i\S*" if name == "perl" else r"-[nEsrzu]*i\S*", a):
            inplace = True
        elif a.startswith("-e") and len(a) > 2:
            scripts.append(a[2:])
        elif not a.startswith("-"):
            pos.append(a)
        j += 1
    if not inplace:
        return
    if not scripts and pos:
        scripts.append(pos.pop(0))
    ctx.out.append(Write(_paths(pos, here), "\n".join(scripts), paths=False))


def _git(args: list[str], base: str, here: Path | None, ctx: _Ctx) -> None:
    repo, j, sub = here, 0, None
    while j < len(args):
        a = args[j]
        if a == "-C" and j + 1 < len(args):
            repo = _path(args[j + 1], repo)
            j += 2
        elif a in _GIT_VALUE_OPTS:
            j += 2
        elif a.startswith("-"):
            j += 1
        else:
            sub = a
            break
    if sub not in _GIT_TEXT_SUBS or repo is None:
        return
    rest = args[j + 1:]
    flags = {a for a in rest if a.startswith("-")}
    positional = [a for a in rest if not a.startswith("-")]
    if sub == "tag" and (not positional or flags & {"-l", "--list", "-d", "--delete", "-v", "--verify"}):
        return
    if sub in {"stash", "notes"} and rest and rest[0] in _GIT_READ_SUBSUBS:
        return
    if sub == "notes" and not rest:
        return
    if sub == "apply" and flags & {"--check", "--stat", "--numstat", "--summary"}:
        return
    ctx.out.append(Write([repo], "\n".join([*rest, base])))
