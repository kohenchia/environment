# Stella

Stella is a chief of staff for [Claude Code](https://docs.claude.com/en/docs/claude-code): a persona any
session adopts when you address her, her own session (`stella run`) where everything you say is to her, and a
small CLI that gives every session the same memory, opens a tmux window for each team she launches, and
asks you before any session pushes.

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
the store (`~/.local/share/stella`, a local-only git repo), installs the leak guard's commit hooks on
this repository (and removes the old push gate's hooks and push URL), and installs the `stella` plugin
into Claude Code. Then, inside tmux:

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
| **Credentials** (`pass_env`) | Variables named in `pass_env` (say, a token for a shared quota) are either on or off for every session Stella starts: team windows, her own session, the scheduler's runs. `stella run` sets the switch from the environment it starts in; off removes them even if tmux has them; on takes each value from the caller's environment, else `<pass_env_dir>/<NAME>`. `stella pass-env on\|off --respawn` switches mid-day and restarts running teams (and Stella) in place, resuming their conversations |
| **Attention** | Finished or blocked teams, stale orders, nightly alerts and proposals. A finished team also raises a desktop notification |
| **Wake line** | When a team reports done, reports `--needs-you` or exits unexpectedly, a `[Stella] Team X finished…` line is typed into Stella's own window once Claude Code shows its input box empty with no spinner (idle); while she is mid-turn it waits, and her next turn carries it. Events within 20 s share a line, at most one line a minute. The prompt hook treats exactly that line as a system note, never an order; anything you type, even after it, is recorded as usual. Progress reports and windows you close by hand don't wake her. It types only in the tmux server her session started in, into the one `stella` window whose pane runs her; otherwise nothing is typed and an alert is raised. A lead whose shell is sandboxed may not reach tmux: then the line comes from the scheduler's 20-minute backstop instead |
| **Follow-ups** | `stella followup add "<do Y>" --after <team>[,…]` records "after X is done, do Y" in the ledger. Her brief and every turn in her session show each one READY (all named teams done) or waiting on whom; `stella followup close N` when done |
| **Scheduler** | A background process started by `stella run` from your terminal (so it has your terminal's file access); no window. Runs the daily log at `daily_time`, then the nightly jobs (leak sweep, reflection → morning digest and learning proposals). Every `wake_check_minutes` (20) it sends a wake line that never arrived, if one is due; that check runs no model. If it isn't running when a run is due, the next Claude session that starts runs one catch-up pass |
| **Canon** (`store/canon.md`, `cases.toml`) | Your judgment, as numbered principles with evidence, replayed by `stella eval`. Only you accept changes; the `stella-curator` agent writes them |
| **Push prompt** | When a Claude session runs a command that pushes from any git repo with a remote (`git push`, `gh pr create`, …), the tool hook asks Claude Code to show you its yes/no prompt first, naming the repo, the branch and how far it is ahead. Yes runs the push; no stops it. It looks at the parsed command, so text that merely mentions a push (a commit message, a grep, a heredoc) never asks. A yes is remembered per repo and head commit for every session and subagent (recorded by a PostToolUse hook after the push ran), so the same head is asked once; a plain push with nothing ahead of its upstream is not asked. A `git push` you type in a terminal is plain git. Teams push their own branch before reporting done, so you answer a prompt and never have to remember a chore; `stella launch --auto-push` skips the prompt when you said up front to push |
| **Extensions** | Directories listed in `~/.config/stella/extensions.toml` that add teams, knowledge maps, persona and playbook addenda, doctor checks, the daily-log prompt, and leak-guard rules. The core never names one |

## Developing

```
uv sync
uv run pytest
```

Tests run the real CLI against a throwaway store and config; tmux tests use a private socket.
