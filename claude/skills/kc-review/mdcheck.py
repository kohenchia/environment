#!/usr/bin/env python3
"""Check vault markdown for text Obsidian misreads. Run before saving any note or report.

  mdcheck.py [--fix] [--allow name,name] <file.md>...

Exit 1 and print `file:line: message` for each of:
  - a bare `<name>` / `</name>` / `<name ...>` outside a code span or fence. Obsidian reads it as an HTML tag: the
    text `<name>` disappears, and a tag alone on its line starts an HTML block that stops markdown (tables, bold,
    lists) rendering until the next blank line. Write it as `<name>` in backticks, or as &lt;name&gt;.
  - a table row whose unescaped `|` count differs from its header (a `|` in a cell, even inside backticks or in
    [[note|alias]], must be written `\\|`).
  - a table inside a list item that Obsidian's reading view shows as plain lines with a literal `|---|`: its rows are
    indented 1 to 3 spaces (4 spaces or a tab are needed under `5. ` and `- `) or no blank line comes before it. A table
    after the list, at column 0 behind a blank line, is fine.
  - anything below `</dataPolicy:slack>`: Obsidian does not render the markdown after the Slack tags, so the Slack
    section must be the last thing in the file (a block inside a code fence is fine).
  - frontmatter Obsidian cannot read as YAML: an unquoted value holding `: ` (`updated: 2026-11-03 (replies: ask 3)`),
    starting with a YAML indicator (`@`, a backtick, `&`, `*`, `!`, `%`), or with a quote it never closes, and a
    ` #` that YAML takes as a comment (`title: issue #42` keeps only `issue`). Obsidian then shows the whole block
    as raw text instead of Properties. A first `---` with no closing `---` is flagged too.
Allowed bare: <br>, <kbd>, <sub>, <sup>, <mark>, <u>, <wbr>, <!-- comments -->, <https://...> autolinks and the
Slack data tags <dataSource:slack>, <dataPolicy:slack>. --allow adds tag names (an old page with inline <svg>).
--fix wraps each complete bare tag in backticks, re-indents such a table to 4 spaces and puts a blank line before it, and
double-quotes such a frontmatter value (the only changes it makes), and still reports what it cannot fix.
"""

import json
import re
import sys
from pathlib import Path

ALLOWED = {"br", "kbd", "sub", "sup", "mark", "u", "wbr"}
BARE = re.compile(r"(?<!\\)</?([A-Za-z][A-Za-z0-9:-]*)(?:\s[^<>\n]*)?/?>|(?<!\\)<(?=[A-Za-z/!?])")
OK_SPECIAL = re.compile(r"<!--|<https?://[^>\s]*>|<mailto:[^>\s]*>|</?data(?:Source|Policy):slack>")
CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.S)
LIST_ITEM = re.compile(r"(?:\d{1,9}[.)]|[-*+])(?:\s|$)")
DELIM = re.compile(r"\s*\|?\s*:?-{3,}")
FENCE = re.compile(r"\s*(?:>\s*)*(`{3,}|~{3,})")
FM_ITEM = re.compile(r"((?:[A-Za-z0-9_][\w .-]*?):[ \t]+|[ \t]*-[ \t]+)(.*)$")
INDICATORS = "@`&*!%"


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


def in_list(lines, h):
    """True when the nearest line above line index h that is neither blank nor indented starts a list item."""
    for j in range(h - 1, -1, -1):
        if lines[j].strip() and lines[j][0] not in " \t":
            return bool(LIST_ITEM.match(lines[j]))
    return False


def tables(text):
    """Yield (header line index, row count, indent, blank line before, inside a list) for each table outside fences."""
    doc = text.split("\n")
    for start, lines in blocks(text):
        for k in range(1, len(lines)):
            if "|" not in lines[k] or not DELIM.match(lines[k]) or "|" not in lines[k - 1]:
                continue
            n = 2
            while k + n - 1 < len(lines) and lines[k + n - 1].lstrip().startswith("|"):
                n += 1
            h = start - 1 + k - 1
            lead = re.match(r"[ \t]*", doc[h]).group(0)
            yield h, n, 4 if "\t" in lead else len(lead), h == 0 or not doc[h - 1].strip(), in_list(doc, h)
            break


def bad_layout(indent, blank, listy):
    """The reason Obsidian will not render this table, or None."""
    if not listy:
        return None
    if not blank:
        return "no blank line before the table inside a list item: add one"
    if 0 < indent < 4:
        return f"table inside a list item is indented {indent} spaces: Obsidian needs 4 (or a tab) to read it as a table"
    return None


def fix_tables(text):
    """Re-indent each badly laid out table to 4 spaces and put a blank line before it."""
    doc = text.split("\n")
    for h, n, indent, blank, listy in sorted(tables(text), reverse=True):
        if not bad_layout(indent, blank, listy):
            continue
        if indent < 4:
            for i in range(h, h + n):
                doc[i] = " " * 4 + doc[i].lstrip(" ")
        if not blank:
            doc.insert(h, "")
    return "\n".join(doc)


def frontmatter_problem(value):
    """Why YAML would not read this frontmatter value as the text it shows, or None."""
    v = value.strip()
    if not v or v[0] in "[{|>":  # empty, a flow collection or a block scalar
        return None
    if v[0] in "\"'":
        closed = len(v) > 1 and v[-1] == v[0] and (v[0] == "'" or not v.endswith('\\"'))
        return None if closed else f"frontmatter value opens a {v[0]} quote it never closes"
    if ": " in v or v.endswith(":"):
        return "unquoted frontmatter value holds ': ', so YAML fails and Obsidian shows the block as raw text: quote it"
    if v[0] in INDICATORS:
        return f"unquoted frontmatter value starts with {v[0]!r}, a YAML indicator: quote it"
    if " #" in v:
        return "unquoted frontmatter value holds ' #', which YAML reads as a comment and drops: quote it"
    return None


def frontmatter(text, fix=False):
    """(problems, text) for the YAML frontmatter; with fix, each flagged plain value is double-quoted."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return [], text
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    if end is None:
        return [(1, "frontmatter opens with --- and never closes: add a closing --- line")], text
    problems = []
    for i in range(1, end):
        m = FM_ITEM.match(lines[i])
        if not m or lines[i].lstrip().startswith("#"):
            continue
        why = frontmatter_problem(m.group(2))
        if why and fix and not why.startswith("frontmatter value opens"):
            lines[i] = m.group(1) + json.dumps(m.group(2).strip(), ensure_ascii=False)
        elif why:
            problems.append((i + 1, why))
    return problems, "\n".join(lines)


def check(path, fix=False, allow=frozenset()):
    text = Path(path).read_text()
    fm_problems, fixed = frontmatter(text, fix)
    if fix and fixed != text:
        Path(path).write_text(fixed)
        text = fixed
    if fix and (fixed := fix_tables(text)) != text:
        Path(path).write_text(fixed)
        text = fixed
    problems, edits = list(fm_problems), []
    doc = text.split("\n")
    for h, n, indent, blank, listy in tables(text):
        if (why := bad_layout(indent, blank, listy)):
            problems.append((h + 1, why))
        want = cells(doc[h + 1])
        for i in range(h, h + n):
            if cells(doc[i]) != want:
                problems.append((i + 1, f"table row has {cells(doc[i])} cells, the header has {want}: write a `|` inside a cell as \\|"))
    for start, lines in blocks(text):
        block = "\n".join(lines)
        for pos, end, tok, complete in bare_tags(block, allow):
            line = start + block.count("\n", 0, pos)
            problems.append((line, f"bare {tok.strip()!r}: write it in backticks or as &lt;&gt;" + ("" if complete else " (unclosed)")))
            if complete:
                edits.append((start, len(lines), pos, end))
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
    """The Slack tags outside a code fence must be the last thing in the file; a fenced block renders as code."""
    lines = Path(path).read_text().split("\n")
    fence, loose = None, []
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if m and (fence is None or m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)):
            fence = None if fence else m.group(1)
        elif not fence:
            loose.append((i, line.strip()))
    closes = [i for i, t in loose if t in ("</dataPolicy:slack>", "</dataSource:slack>")]
    opens = [i for i, t in loose if t == "<dataSource:slack>"]
    tail = re.sub(r"<!--.*?-->", "", "\n".join(t for i, t in loose if closes and i > closes[-1]), flags=re.S)
    if closes and tail.strip():
        return [(closes[-1] + 2, "text after </dataPolicy:slack>: Obsidian does not render markdown after the Slack tags; move the Slack section to the end of the file (or put the block in a code fence)")]
    if opens and not any(t == "</dataPolicy:slack>" for i, t in loose):
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
