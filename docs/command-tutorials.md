# Command Tutorials (`h`)

`h` prints a short, color-coded, copy-pasteable tutorial for a console command
right in your terminal — a faster, friendlier alternative to `man` for the
handful of flags you actually use day to day.

```
h rg          # print the tutorial for ripgrep
h             # list every command that has a tutorial
```

Color is emitted only when writing to a terminal, so piping or redirecting
(`h rg | less`, `h rg > rg.txt`) yields clean plain text. Set `NO_COLOR` to
force plain output even in a terminal.

## How it works

- The `h` script lives at [`bin/h`](../bin/h) and is symlinked to
  `~/.local/bin/h` (already on `PATH`) by `setup.sh`.
- Each tutorial is a plain-markdown file in [`tutorials/`](../tutorials):
  `tutorials/<command>.md`. `h <command>` renders that file with ANSI color —
  headings, fenced code blocks, inline `` `code` ``, and **bold** text.

## Adding a tutorial

Drop a new markdown file in `tutorials/` named after the command — no code
changes needed:

```
tutorials/jq.md      # enables `h jq`
tutorials/fzf.md     # enables `h fzf`
```

The renderer understands:

| Markdown | Rendered as |
|---|---|
| `# Title` / `## Section` | bold cyan heading |
| `### Subsection` | bold heading |
| ` ```…``` ` fenced block | green code; trailing `# comments` dimmed |
| `` `code` `` | yellow inline code |
| `**bold**` | bold text |
| `---` | dim horizontal rule |
