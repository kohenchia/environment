#!/usr/bin/env python3
"""kc-review's companion use-case page: capture each case, pull its excerpts verbatim, check the page.

  usecases.py capture <case-dir> --side base=<dir> --side head=<dir> [--shown "<command>"] -- <argv...>
      Runs argv in each side's directory and writes <case-dir>/<side>.log: stdout and stderr, ANSI codes
      stripped, and `EXIT <n>` as the last line. --shown writes cmd.txt (the command as the user types it).
  usecases.py check <page.md> <evidence-dir>
      Every line of every fenced block in the page must appear verbatim in one captured line under
      evidence-dir (in the files named by a `<!-- from: path, path -->` line just above the fence, when
      there is one; scripts and notes, *.py *.sh *.md, count only when named). `…` marks cut text: each piece must appear, in order. A line starting with `# ` or `// `
      is an annotation and is skipped. A `<!-- not captured: reason -->` line above a fence skips that
      block and lists it. Exits 1 when any line is not found.

A page's generator imports this file and builds every excerpt with pull(), block(), exit_code() and fence(),
so nothing in the page is retyped. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FROM = re.compile(r"^<!--\s*from:\s*(.+?)\s*-->$")
NOT_CAPTURED = re.compile(r"^<!--\s*not captured:\s*(.+?)\s*-->$")
FENCE = re.compile(r"^(`{3,}|~{3,})")
NOT_EVIDENCE = {".py", ".sh", ".md"}  # scripts and agents' notes, unless a from: line names the file


def lines(path) -> list[str]:
    """A captured file's lines, ANSI codes stripped, trailing whitespace dropped."""
    return [ANSI.sub("", s).rstrip() for s in Path(path).read_text(errors="replace").splitlines()]


def pull(path, pattern: str, nth: int = 0, prefix: str | None = None) -> str:
    """The nth line matching pattern (and starting with prefix), verbatim; stops the generator when none does."""
    hits = [s for s in lines(path) if (prefix is None or s.startswith(prefix)) and re.search(pattern, s)]
    if len(hits) <= nth:
        raise SystemExit(f"no line {nth + 1} matching {pattern!r} in {path}")
    return hits[nth]


def _indent(s: str) -> int:
    return len(s) - len(s.lstrip(" "))


def block(path, header: str, keep=None) -> str:
    """The block from the first line matching header to the next blank or unindented line.

    keep: the row keys to take (a row is `  key   value`, its key ends at two spaces); a row's more
    indented continuation lines come with it. None takes the whole block."""
    ls = lines(path)
    start = next((i for i, s in enumerate(ls) if re.search(header, s)), None)
    if start is None:
        raise SystemExit(f"no block {header!r} in {path}")
    out, row_indent, taking = [ls[start]], None, keep is None
    for s in ls[start + 1:]:
        if not s.strip() or _indent(s) == 0:
            break
        if keep is None:
            out.append(s)
            continue
        if row_indent is None:
            row_indent = _indent(s)
        if _indent(s) <= row_indent:
            key = re.split(r"\s{2,}", s.strip(), maxsplit=1)[0]
            taking = key in keep
        if taking:
            out.append(s)
    return "\n".join(out)


def exit_code(path) -> int:
    """The exit code capture wrote as the log's last line."""
    ls = lines(path)
    last = ls[-1] if ls else ""
    m = re.fullmatch(r"EXIT (\d+)", last)
    if not m:
        raise SystemExit(f"{path} does not end with capture's EXIT line")
    return int(m.group(1))


def clip(s: str, width: int = 175) -> str:
    """s cut to width, the cut marked with ` …` (check accepts the marked line)."""
    return s if len(s) <= width else s[: width - 2] + " …"


def fence(text: str, lang: str = "text", source: str | None = None) -> str:
    """A fenced block; source (relative to the evidence folder) tells check where its lines come from."""
    head = f"<!-- from: {source} -->\n" if source else ""
    return f"{head}```{lang}\n{text}\n```"


def capture(case: Path, sides: list[tuple[str, Path]], argv: list[str], shown: str | None) -> int:
    case.mkdir(parents=True, exist_ok=True)
    if shown:
        (case / "cmd.txt").write_text(shown + "\n")
    elif not (case / "cmd.txt").exists():
        (case / "cmd.txt").write_text(" ".join(argv) + "\n")
    summary = []
    for name, cwd in sides:
        p = subprocess.run(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        text = ANSI.sub("", p.stdout.decode(errors="replace"))
        if text and not text.endswith("\n"):
            text += "\n"
        (case / f"{name}.log").write_text(f"{text}EXIT {p.returncode}\n")
        summary.append(f"{name} EXIT {p.returncode}")
    print(f"{case.name}: " + " · ".join(summary))
    return 0


def _pieces_in_order(line: str, candidate: str) -> bool:
    pos = 0
    for piece in (p.strip() for p in line.split("…")):
        if not piece:
            continue
        i = candidate.find(piece, pos)
        if i < 0:
            return False
        pos = i + len(piece)
    return True


def _evidence(root: Path, sources: list[str] | None) -> tuple[list[str], list[str]]:
    files, missing = [], []
    for src in sources or ["."]:
        p = root / src
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(f for f in sorted(p.rglob("*")) if f.is_file() and f.suffix not in NOT_EVIDENCE)
        else:
            missing.append(src)
    out = []
    for f in files:
        try:
            out.extend(lines(f))
        except (OSError, UnicodeError):
            continue
    return out, missing


def check(page: Path, root: Path) -> int:
    text = page.read_text().splitlines()
    cache: dict[tuple, tuple] = {}
    checked, bad, skipped = 0, [], []
    i = 0
    while i < len(text):
        m = FENCE.match(text[i])
        if not m:
            i += 1
            continue
        marker, start = m.group(1), i
        prev = text[i - 1].strip() if i else ""
        j = i + 1
        while j < len(text) and not text[j].startswith(marker):
            j += 1
        body = text[i + 1:j]
        i = j + 1
        if NOT_CAPTURED.match(prev):
            skipped.append(f"{page.name}:{start + 1} ({NOT_CAPTURED.match(prev).group(1)})")
            continue
        fm = FROM.match(prev)
        key = tuple(s.strip() for s in fm.group(1).split(",")) if fm else None
        if key not in cache:
            cache[key] = _evidence(root, list(key) if key else None)
        evidence, missing = cache[key]
        for src in missing:
            bad.append(f"{page.name}:{start} names a source that does not exist: {src}")
        for k, line in enumerate(body, start=start + 2):
            s = line.strip()
            if not s or s.startswith(("# ", "// ")):
                continue
            checked += 1
            if not any(_pieces_in_order(line, c) for c in evidence):
                bad.append(f"{page.name}:{k} not found in the captured files: {s[:120]}")
    for b in bad:
        print(b)
    for s in skipped:
        print(f"labelled not captured: {s}")
    print(f"{checked} lines checked, {len(bad)} not found, "
          f"{len(skipped)} block{'' if len(skipped) == 1 else 's'} labelled not captured")
    return 1 if bad else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture", help="run one case at each side and record the logs")
    c.add_argument("case", type=Path)
    c.add_argument("--side", action="append", required=True, metavar="NAME=DIR")
    c.add_argument("--shown", help="the command as the user types it, for cmd.txt")
    k = sub.add_parser("check", help="check every fenced excerpt of a page against the captured files")
    k.add_argument("page", type=Path)
    k.add_argument("evidence", type=Path)
    argv = sys.argv[1:] if argv is None else argv
    cut = argv.index("--") if "--" in argv else len(argv)
    a, argv_ = ap.parse_args(argv[:cut]), argv[cut + 1:]
    if a.cmd == "check":
        return check(a.page, a.evidence)
    if not argv_:
        ap.error("capture needs the command after --")
    sides = []
    for spec in a.side:
        name, sep, d = spec.partition("=")
        cwd = Path(d).expanduser()
        if not sep or not re.fullmatch(r"[\w.-]+", name):
            ap.error(f"--side wants NAME=DIR, got {spec!r}")
        if not cwd.is_dir():
            ap.error(f"--side {name}: {cwd} is not a directory (missing)")
        sides.append((name, cwd))
    return capture(a.case, sides, argv_, a.shown)


if __name__ == "__main__":
    sys.exit(main())
