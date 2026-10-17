---
name: kc-tutorial
user-invocable: true
description: Write a new tutorial or explainer into Kohen's Obsidian vault. Routes by shape — a single-page explainer goes to Notes/, a chaptered tutorial goes to Tutorial/. Use when asked to create a tutorial, lesson, explainer, deep dive, or "how does X actually work" writeup — e.g. "/kc-tutorial how the payments auth chain works". Handles research, placement, naming, frontmatter, diagrams, and index linking.
---

# kc-tutorial

Research a topic properly, then write it up in Kohen's Obsidian vault (its location is in the global
instructions).

Before anything else, read `~/.claude/kc-extensions/kc-tutorial.md` if it exists and follow it on top of
this skill: it names this machine's sources, tools and index notes.

Invoked as `/kc-tutorial <what to write about>`. The argument is the brief, not the title,
and may include scope hints ("focus on the on-device path", "for someone new to the team").

## Where it goes — this is the routing decision

| Signal | Destination |
| --- | --- |
| One mechanism, one sitting to read | **`Notes/<Title>.md`** — a single-page explainer |
| Builds concepts in sequence, or >~1500 words | **`Tutorial/<Topic>/`** — chaptered, with an index note named after the folder |

**Default to `Notes/`.** `Notes/` is the only folder a generic Claude session reads, so an
explainer that lands in `Tutorial/` is invisible outside tutorial work. `Tutorial/` is for
material genuinely worth reading start to finish. When it's borderline, write the single
page — a note can grow into a tutorial later, and the reverse never happens.

If a chaptered tutorial produces durable standalone claims, **harvest them into `Notes/`
as separate notes** and link them from the chapters. A finding that only exists inside a
tutorial chapter is a finding a generic session can't see.

## Before writing anything

1. Read the vault's `CLAUDE.md` — vault conventions. **It is authoritative and it
   changes; do not work from memory of it.**
2. Read the vault's `Notes/Notes.md` and, for chaptered work,
   `Tutorial/Tutorial.md` — the indexes and what already exists. **If a
   page already covers this topic, update it rather than adding a near-duplicate.**
3. Read the global instructions for the repo map and per-repo tooling.

## Research first, write second

The value of these pages is that they're accurate about *this* codebase, not generically
correct. Do not write from memory.

- Trace the actual code paths across every repo involved. Follow imports, registrations,
  and CLI entry points to their implementations. Read both sides of a cross-repo call.
- Cite specifics — `file_path:line_number`, function names, config keys, flag names.
  "The registry handles this" is not acceptable.
- Use the available tools for external state (jobs, CI, PRs, decision threads, design docs);
  the extension names them.
- Record the commit or branch you read. These pages age; a reader needs to know against
  what.
- Resolve ambiguity by reading code. Only surface questions that need human judgement.
- Spawn parallel subagents for multi-repo tracing, then synthesize.

## Naming

Sentence case, describing the content. The filename is the display title *and* the
wikilink text, so it has to read well inline.

- Good: `Payments service auth chain`, `Worker pool shutdown order`
- Bad: `PAYMENTS_AUTH`, `notes on payments`, `Tutorial 3`
- Technical identifiers keep their real casing: `launch_worker`, `ROOTS_DICT`.
- Avoid `:` and `"` in filenames; use `—` instead of a colon.
- Chapters: `01 <Title>.md`, `02 <Title>.md`, … cross-linked as `[[NN Title|readable text]]`.
  Follow `Tutorial/Popup isolation/` for the pattern.

## Frontmatter

```yaml
---
type: reference        # single-page explainer in Notes/
                       # use `note` for tutorial chapters and tutorial index notes
status: active
project: <Project>     # or omit if not project-specific
created: <today, YYYY-MM-DD>
updated: <today>
tags:
  - <topic tags>
---
```

Do not invent new frontmatter keys — `Notes index.base` queries this schema.

## Diagrams

**The vault `CLAUDE.md` §Diagrams is authoritative — read it.** The essentials:

- **Never ASCII art.** Ever.
- **A standalone hand-written `.svg` file** beside the note that embeds it, topic-prefixed
  like everything else (`Worktree guide — layout.svg`), embedded with
  `![[Worktree guide — layout.svg]]`. Mermaid is fine when the graph is generic enough that
  default layout works; prefer SVG when placement or emphasis matters. Raster is a last
  resort — it can't be diffed.
- **Background-agnostic palette.** An embedded SVG follows the *OS* colour scheme, not
  Obsidian's theme, so a `prefers-color-scheme` query can paint light-on-light and the
  diagram silently vanishes. Use saturated mid-tones that hold on white *and* near-black:
  `#6366f1` indigo, `#0891b2` cyan, `#e11d48` rose, `#6e6e73` secondary text. Colour
  headline labels with their subject's own colour.
- **Render it and look at it before saving the note.** Not optional. No system renderer is
  installed and `qlmanage` is sandboxed; use a playwright webkit (the extension says which
  venv has one), load the SVG in an `<img>` on a white page *and* a dark page, and read the screenshots
  back. Clipped labels and contrast failures are the two things that actually go wrong.
- `role="img"` with `<title>`/`<desc>`, plus a comment in the file explaining any
  non-obvious choice so the next edit doesn't undo it.
- A diagram earns its place when it shows a flow, a boundary, or a sequence. Skip it for
  anything a table does better.

Note: some older pages carry diagrams as **inline `<svg>` blocks**. That predates this
convention — don't copy it, and don't rewrite those pages just to convert them.

## Rules that matter

1. **Explainers are durable; live state is not.** Current pipeline versions, run IDs, and
   "latest working run" belong in the project note, not here. A tutorial that goes stale in three weeks is worse than none.
2. **Never fabricate an identifier.** Run IDs, pipeline versions, ticket numbers, PR
   numbers — verify from a tool or the vault, or leave it out.
3. **Mark what you couldn't confirm** with a `> [!question]` callout naming what needs
   checking and who would know. Do not paper over a gap with plausible prose.
4. **No task tracking.** Work tracking lives in Kohen's task list (the extension says
   where), not the vault. Checkboxes are only for unresolved factual questions.

## Finish the job

1. Add the page to the right index — `Notes/Notes.md` for a single-page explainer,
   `Tutorial/Tutorial.md` for a chaptered tutorial — and link it from any related project
   index.
2. Link outward from the new page to related notes.
3. Validate the frontmatter parses (any python with PyYAML; the extension may name one):
   ```bash
   uv run --with pyyaml python -c "
   import pathlib,yaml,sys
   p=pathlib.Path(sys.argv[1]); s=p.read_text(); e=s.find(chr(10)+'---'+chr(10),3)
   print(yaml.safe_load(s[4:e+1]))" "<new file>"
   ```
4. Report the file path(s) created, the commit or branch you traced, which index you
   updated, and anything you flagged as unverified. Obsidian Sync is usually running, so
   mention if you edited a file that may have been open.
