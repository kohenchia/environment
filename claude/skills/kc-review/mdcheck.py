#!/usr/bin/env python3
"""Check vault markdown for text Obsidian misreads. Run before saving any note or report.

  mdcheck.py [--fix] [--allow name,name] <file.md>...

Exit 1 and print `file:line: message` for each of:
  - a bare `<name>` / `</name>` / `<name ...>` outside a code span or fence. Obsidian reads it as an HTML tag: the
    text `<name>` disappears, and a tag alone on its line starts an HTML block that stops markdown (tables, bold,
    lists) rendering until the next blank line. Write it as `<name>` in backticks, or as &lt;name&gt;.
  - a table row whose unescaped `|` count differs from its header (a `|` in a cell, even inside backticks or in
    [[note|alias]], must be written `\\|`).
  - anything below `</dataPolicy:slack>`: Obsidian does not render the markdown after the Slack tags, so the Slack
    section must be the last thing in the file.
Allowed bare: <br>, <kbd>, <sub>, <sup>, <mark>, <u>, <wbr>, <!-- comments -->, <https://...> autolinks and the
Slack data tags <dataSource:slack>, <dataPolicy:slack>. --allow adds tag names (an old page with inline <svg>).
--fix wraps each complete bare tag in backticks (the only change it makes) and still reports what it cannot fix.
"""

import re
import sys
from pathlib import Path

ALLOWED = {"br", "kbd", "sub", "sup", "mark", "u", "wbr"}
BARE = re.compile(r"(?<!\\)</?([A-Za-z][A-Za-z0-9:-]*)(?:\s[^<>\n]*)?/?>|(?<!\\)<(?=[A-Za-z/!?])")
OK_SPECIAL = re.compile(r"<!--|<https?://[^>\s]*>|<mailto:[^>\s]*>|</?data(?:Source|Policy):slack>")
CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
FENCE = re.compile(r"\s*(?:>\s*)*(`{3,}|~{3,})")


def blocks(text):
    """Yield (first line number, [lines]) for each run of non-blank lines outside frontmatter and fences."""
    lines = text.split("\n")
    fence, fm, cur, start = None, False, [], 0
    for i, line in enumerate(lines, 1):
        if i == 1 and line.strip() == "---":
            fm = True
            continue
        if fm:
            fm = line.strip() != "---"
            continue
        m = FENCE.match(line)
        if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
            if cur:
                yield start, cur
                cur = []
            fence = None if fence else m.group(1)
            continue
        if fence:
            continue
        if not line.strip():
            if cur:
                yield start, cur
                cur = []
            continue
        if not cur:
            start = i
        cur.append(line)
    if cur:
        yield start, cur


def mask_code(block):
    return CODE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), block)


def bare_tags(block, allow):
    """Positions (start, end, text, complete) of bare tags in a block's text, code spans masked out."""
    masked = mask_code(block)
    found = []
    for m in BARE.finditer(masked):
        if OK_SPECIAL.match(masked, m.start()):
            continue
        name = m.group(1)
        if name and name.lower() in ALLOWED | allow:
            continue
        if name is None:  # a `<` that starts a tag-like thing but never closes on its line
            found.append((m.start(), m.end(), masked[m.start():m.start() + 12], False))
        else:
            found.append((m.start(), m.end(), m.group(0), True))
    return found


def cells(row):
    row = row.strip()
    row = row[1:] if row.startswith("|") else row
    row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
    return len(re.split(r"(?<!\\)\|", row))


def check(path, fix=False, allow=frozenset()):
    text = Path(path).read_text()
    problems, edits = [], []
    for start, lines in blocks(text):
        block = "\n".join(lines)
        for pos, end, tok, complete in bare_tags(block, allow):
            line = start + block.count("\n", 0, pos)
            problems.append((line, f"bare {tok.strip()!r}: write it in backticks or as &lt;&gt;" + ("" if complete else " (unclosed)")))
            if complete:
                edits.append((start, len(lines), pos, end))
        if len(lines) > 1 and re.match(r"\s*\|?\s*:?-{3,}", lines[1]) and "|" in lines[1]:
            want = cells(lines[1])
            for k, row in enumerate(lines[2:], 2):
                if not row.lstrip().startswith("|"):
                    break
                if cells(row) != want:
                    problems.append((start + k, f"table row has {cells(row)} cells, the header has {want}: write a `|` inside a cell as \\|"))
    if fix and edits:
        out = text.split("\n")
        by_block = {}
        for start, n, pos, end in edits:
            by_block.setdefault((start, n), []).append((pos, end))
        for (start, n), spans in by_block.items():
            block = "\n".join(out[start - 1:start - 1 + n])
            for pos, end in sorted(spans, reverse=True):
                block = block[:pos] + "`" + block[pos:end] + "`" + block[end:]
            out[start - 1:start - 1 + n] = block.split("\n")
        Path(path).write_text("\n".join(out))
        return check(path, False, allow)
    return problems


def slack_last(path):
    lines = Path(path).read_text().split("\n")
    closes = [i for i, l in enumerate(lines) if l.strip() == "</dataPolicy:slack>"]
    if closes and any(l.strip() for l in lines[closes[-1] + 1:]):
        return [(closes[-1] + 2, "text after </dataPolicy:slack>: Obsidian does not render markdown after the Slack tags; move the Slack section to the end of the file")]
    opens = [i for i, l in enumerate(lines) if l.strip() == "<dataSource:slack>"]
    if opens and not closes:
        return [(opens[0] + 1, "<dataSource:slack> without a closing </dataPolicy:slack>")]
    return []


def main(argv):
    fix = "--fix" in argv
    allow = set()
    args = []
    it = iter(a for a in argv if a != "--fix")
    for a in it:
        if a == "--allow":
            allow = {n.lower() for n in next(it, "").split(",") if n}
        else:
            args.append(a)
    bad = 0
    for path in args:
        for line, msg in check(path, fix, frozenset(allow)) + slack_last(path):
            print(f"{path}:{line}: {msg}")
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
