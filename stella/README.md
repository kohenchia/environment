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
| **Team windows** | `stella launch <team>` opens a tmux window in the server you are in (else the default server) running the lead. When the lead exits (`/quit`, a crash) the window stays as your login shell in the same directory, so you can run things or `claude --resume`; `stella reap` still closes it, and the end is still recorded (a crash with no SessionEnd hook is fed to it by the launch script). `stella tell` types into it only while the lead runs. `stella reopen <team, name or id>` opens a window that resumes a finished session. Stella never starts a tmux server |
| **Registry** | `teams.toml` here and in each extension. Entries point at the team's own skill and CLI (`stella team <name>` reads them live), so Stella drives teams through their interface |
| **Credentials** (`pass_env`) | Variables named in `pass_env` (say, a token for a shared quota) are either on or off for every session Stella starts: team windows, her own session, the scheduler's runs. The terminal decides nothing: only `stella pass-env on\|off` and `stella run --pass-env on\|off` change the switch (a plain `stella run` reads it; never set means off); off removes them even if tmux has them; on takes each value from `<pass_env_dir>/<NAME>`, never from the caller's environment. `stella pass-env` also lists, per live session, whether it runs on the shared or personal credentials. `stella pass-env on\|off --respawn` switches mid-day and restarts running teams (and Stella) in place, resuming their conversations |
| **Attention** | Finished or blocked teams, stale orders, nightly alerts and proposals. A finished team also raises a desktop notification |
| **Wake line** | When a team reports done, reports `--needs-you` or exits unexpectedly, a `[Stella] Team X finished…` line is typed into Stella's own window once Claude Code shows its input box empty with no spinner (idle); while she is mid-turn it waits, and her next turn carries it. Events within 20 s share a line, at most one line a minute. The prompt hook treats exactly that line as a system note, never an order; anything you type, even after it, is recorded as usual. Progress reports and windows you close by hand don't wake her. It types only in the tmux server her session started in, into the one `stella` window whose pane runs her; otherwise nothing is typed and an alert is raised. A lead whose shell is sandboxed may not reach tmux: then the line comes from the scheduler's 20-minute backstop instead |
| **Follow-ups** | `stella followup add "<do Y>" --after <team>[,…]` records "after X is done, do Y" in the ledger. Her brief and every turn in her session show each one READY (all named teams done) or waiting on whom; `stella followup close N` when done |
| **Scheduler** | A background process started by `stella run` from your terminal (so it has your terminal's file access); no window. Runs the daily log and then the nightly jobs for the day that just ended, at local midnight (`daily_time`, default `00:00`; the cutoff is always a local midnight). Each run covers a window between two cutoffs, stored in `scheduler.json` as `last_cutoff`; only work completed inside it is logged, and a time-zone change is handled by splitting or skipping windows so they always tile (leak sweep, reflection → morning digest and learning proposals). Every `wake_check_minutes` (20) it sends a wake line that never arrived, if one is due; that check runs no model. With `wrapup_auto = true` it also runs the wrap-up sweep every minute (below). If it isn't running when a run is due, the next Claude session that starts runs one catch-up pass |
| **Canon** (`store/canon.md`, `cases.toml`) | Your judgment, as numbered principles with evidence, replayed by `stella eval`. Only you accept changes; the `stella-curator` agent writes them |
| **Push prompt** | When a Claude session runs a command that pushes from any git repo with a remote (`git push`, `gh pr create`, …), the tool hook asks Claude Code to show you its yes/no prompt first, showing `Push <repo> -> <branch> (N commits)`, the newest subjects, `FORCE` for a force push, and where to see the full diff (a background tmux window `push-diff` you jump to and back, or a file if tmux is unreachable; `stella diff [repo]` prints it anywhere). Yes runs the push; no stops it and leaves it outstanding. It looks at the parsed command, so text that merely mentions a push (a commit message, a grep, a heredoc) never asks. A yes is remembered per repo and head commit for every session and subagent (recorded by a PostToolUse hook after the push ran), so the same head is asked once; a plain push with nothing ahead of its upstream is not asked. A `git push` you type in a terminal is plain git. Teams push their own branch before reporting done, and it is structural: a Stop hook (and `stella done`) refuses once, per repo head and session, when a session finishes with unpushed commits in a repo it worked in (its directory, and repos it committed to), telling the session to run the push now so this prompt appears. A no is recorded as deferred ("not pushed, deferred"), reported once and never asked again for that head. There is no command for you to run: it is the prompt, or nothing; `stella launch --auto-push` skips the prompt when you said up front to push |
| **Extensions** | Directories listed in `~/.config/stella/extensions.toml` that add teams, knowledge maps, persona and playbook addenda, doctor checks, the daily-log prompt, and leak-guard rules. The core never names one |

### Wrapping up a session

You decide when a session is done. Nothing closes sessions automatically unless you turn it on.

* **In a session:** type `/stella:wrap-up` (or run `stella wrap`). It records the team as wrapped up and
  closes that session's tmux window a few seconds later. It reports unpushed or uncommitted work first;
  the work stays on disk.
* **Resume picker:** `claude --resume` hides a transcript whose first `entrypoint` is `sdk-cli` (a `claude -p` run), even if it was later resumed by hand. `stella reopen` and the nightly job rewrite that origin to `cli` (`stella fix-resume [name|id]` does it on demand; a transcript touched in the last minute is skipped). Sessions are listed under the directory they started in, by name.
* **From Stella:** `stella reap <team>` closes a finished team's window and verifies it is gone.
* **What is ready:** `stella wrapup --dry-run` and the brief's "Finished, not wrapped up" section list each
  finished team with its one reason it is not ready (grace period of `wrapup_grace_minutes`, default 5,
  restarted when you type to it; unpushed commits; uncommitted changes; needs-you; a follow-up or deferred
  push waiting on it; `keep_open`; session busy), or "ready to wrap up".
* **Optional automation:** `wrapup_auto = true` in the config lets the scheduler wrap up every ready team
  about once a minute (closing the window, its orders, a `wrapped_up` event and one quiet notification).
  Off by default. A team with `keep_open = true` in its `teams.toml` entry is never wrapped up automatically.

## Developing

```
uv sync
uv run pytest
```

Tests run the real CLI against a throwaway store and config; tmux tests use a private socket.
