# Stella

Stella is a chief of staff for [Claude Code](https://docs.claude.com/en/docs/claude-code): a persona any
session adopts when you address her, her own session (`stella run`) where everything you say is to her, and a
small CLI that gives every session the same memory, opens a tmux window for each team she launches, and
guards what gets pushed.

```
you ──"S, build a tool that renames my photos"──▶ any session
                                                   │ hook: records the order in the ledger, injects Stella
                                                   ▼
                                          Stella: "Launched builder-photo-renamer in window @7."
                                                   │ stella launch
                                                   ▼
                                   tmux window "builder-photo-renamer": the team lead (a Claude session)
                                     you can switch to it and type to the lead at any time
                                     the lead reports with `stella report` / `stella done` → notification
```

## Install

```
./install.sh
```

Needs `uv`, `tmux`, `git` and `claude`. It creates the venv, links `~/.local/bin/stella`, initialises
the store (`~/.local/share/stella`, a local-only git repo), installs the push gate on this repository,
and installs the `stella` plugin into Claude Code. Then, inside tmux:

```
stella run       # run Stella here (and the scheduler in the background)
stella stop      # stop her session and the scheduler (launched teams keep running)
stella doctor    # check everything
```

## Talking to Stella

| Where | What counts as talking to her |
| --- | --- |
| Stella's own session (`stella run`, window `stella`) | Every message |
| Any other session | A message that starts with `Stella`, `S,` or `S:`, or says "ask Stella". Only that turn is hers; the next plain message is for the session again |
| A team's window | Plain messages go to the team lead; address her to talk to her |

## How it works

| Piece | What it does |
| --- | --- |
| **Ledger** (`store/ledger/*.jsonl`) | Every order, decision, launch, relay and result, append-only, totally ordered under a lock. The prompt hook writes your words *before* the model sees them, so nothing depends on a model remembering |
| **Brief and delta** | The ledger is never read whole. Each addressed turn gets what other sessions recorded since this one last looked (≤15 lines) and possible conflicts with open orders; Stella's own session gets the state brief (≤60 lines) at start, resume and after compaction |
| **Team windows** | `stella launch <team>` opens a tmux window in the server you are in (else the default server) running the lead. `stella tell` types into it. Stella never starts a tmux server |
| **Registry** | `teams.toml` here and in each extension. Entries point at the team's own skill and CLI (`stella team <name>` reads them live), so Stella drives teams through their interface |
| **Attention** | Finished or blocked teams, stale orders, nightly alerts and proposals. A finished team also raises a desktop notification |
| **Scheduler** | A background process started by `stella run` from your terminal (so it has your terminal's file access); no window. Runs the daily log at `daily_time`, then the nightly jobs (leak sweep, push audit, reflection → morning digest and learning proposals). If it isn't running when a run is due, the next Claude session that starts runs one catch-up pass |
| **Canon** (`store/canon.md`, `cases.toml`) | Your judgment, as numbered principles with evidence, replayed by `stella eval`. Only you accept changes; the `stella-curator` agent writes them |
| **Push gate** | Nothing is pushed from this repo (or any guarded repo) without you: `stella review-push <repo>` at a terminal, or telling Stella explicitly "S, push <repo>". Enforced by a tool hook, a `pre-push` hook and a blocked push URL; `stella push` is the only way through |
| **Extensions** | Directories listed in `~/.config/stella/extensions.toml` that add teams, knowledge maps, persona and playbook addenda, doctor checks, the daily-log prompt, and leak-guard rules. The core never names one |

## Developing

```
uv sync
uv run pytest
```

Tests run the real CLI against a throwaway store and config; tmux tests use a private socket.
