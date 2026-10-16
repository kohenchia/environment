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
| **Credentials** (`pass_env`) | Variables named in `pass_env` (say, a token for a shared quota) are either on or off for every session Stella starts: team windows, her own session, the scheduler's runs. The terminal decides nothing: only `stella pass-env on\|off` and `stella run --pass-env on\|off` change the switch (a plain `stella run` reads it; never set means off); off removes them even if tmux has them; on takes each value from `<pass_env_dir>/<NAME>`, never from the caller's environment. `stella pass-env` also lists, per live session, whether it runs on the shared or personal credentials. `stella pass-env on\|off --respawn` switches mid-day and restarts every Claude window in the tmux server in place, resuming their conversations: it finds them from the panes (pane → its `claude` process → `claude agents --json` for the session id and folder), so teams whose window was renamed, windows you resumed by hand, and Stella herself (whatever her window is called) are all restarted; a window is skipped only with a stated reason. Stella's pane, and the pane the command runs in, are restarted last by a detached helper, so it works from inside her own session. Headless runs (daily log, nightly jobs, canon eval) start `claude -p --strict-mcp-config`: they use no MCP tool, and a plugin's MCP server may run a login helper at startup that needs the login keychain, which a scheduler run may not have (macOS then shows "a keychain cannot be found to store token_cache") |
| **Attention** | Finished or blocked teams, stale orders, nightly alerts and proposals. A finished team also raises a desktop notification |
| **Wake line** | When a team reports done, reports `--needs-you` or exits unexpectedly, a `[Stella] Team X finished…` line is typed into Stella's own window once Claude Code shows its input box empty with no spinner (idle); while she is mid-turn it waits, and her next turn carries it. Events within 20 s share a line, at most one line a minute. The prompt hook treats exactly that line as a system note, never an order; anything you type, even after it, is recorded as usual. Progress reports and windows you close by hand don't wake her. It types only in the tmux server her session started in, into the one `stella` window whose pane runs her; otherwise nothing is typed and an alert is raised. A lead whose shell is sandboxed may not reach tmux: then the line comes from the scheduler's 20-minute backstop instead |
| **Follow-ups** | `stella followup add "<do Y>" --after <team>[,…]` records "after X is done, do Y" in the ledger. Her brief and every turn in her session show each one READY (all named teams done) or waiting on whom; `stella followup close N` when done |
| **Scheduler** | A background process started by `stella run` from your terminal (so it has your terminal's file access); no window. Runs the daily log and then the nightly jobs for the day that just ended, at local midnight (`daily_time`, default `00:00`; the cutoff is always a local midnight). Each run covers a window between two cutoffs, stored in `scheduler.json` as `last_cutoff`; only work completed inside it is logged, and a time-zone change is handled by splitting or skipping windows so they always tile (leak sweep, reflection → morning digest and learning proposals). Every `wake_check_minutes` (20) it sends a wake line that never arrived, if one is due; that check runs no model. With `wrapup_auto = true` it also runs the wrap-up sweep every minute (below). If it isn't running when a run is due, the next Claude session that starts runs one catch-up pass |
| **Canon** (`store/canon.md`, `cases.toml`) | Your judgment, as numbered principles with evidence, replayed by `stella eval`. Only you accept changes; the `stella-curator` agent writes them |
| **Push prompt** | When a Claude session runs a command that pushes from any git repo with a remote (`git push`, `gh pr create`, …), the tool hook asks Claude Code to show you its yes/no prompt first, showing one short group per repo (`▲ PUSH  <repo> → <branch>`, `N commits · new branch · FORCE`, the newest three subjects) and a last line `Yes: push · No: defer · Diff: pane on the right`. The dialog's own buttons are Claude Code's (Yes / No); a hook can add nothing to them, so the diff is put on screen instead: when the prompt is raised the hook opens a split pane beside the session's pane (`less -R`, or `delta` if installed; diffstat first), through the scheduler when the hook's own shell cannot reach tmux (up to a second later), and the pane closes itself when the push is answered (the session's next tool call, prompt or stop). Without tmux or a scheduler the last line says `Diff: no viewer; No + Tab, type d`: the refusal then carries your `d` and the session runs `stella diff --show` (pane, else the diffstat in its reply) and pushes again. The prompt is plain text: Claude Code colours the whole reason yellow and the hook can only add glyphs and spacing. Sessions push with `stella push [-C <dir>]` (the current branch of one repo, `git push -u origin <branch>`, after a leak scan of what it sends in a protected repo; no force, no refspec), and nothing else in that command, so the dialog's command line is one calm line; a longer command that also pushes gets `⚠ This command also runs …. Push only?` in the prompt. A raw `git push` (and `gh pr create`, …) is gated exactly as before. Yes runs the push; no stops it and leaves it outstanding. It looks at the parsed command, so text that merely mentions a push (a commit message, a grep, a heredoc) never asks. A yes is remembered per repo and head commit for every session and subagent (recorded by a PostToolUse hook after the push ran), so the same head is asked once; a plain push with nothing ahead of its upstream is not asked. A `git push` you type in a terminal is plain git. Teams push their own branch before reporting done, and it is structural: a Stop hook (and `stella done`) refuses once, per repo head and session, when a session finishes with unpushed commits in a repo it worked in (its directory, and repos it committed to), telling the session to run `stella push` now so this prompt appears. A no is recorded as deferred ("not pushed, deferred"), reported once and never asked again for that head. There is no command for you to run: it is the prompt, or nothing; `stella launch --auto-push` skips the prompt when you said up front to push |
| **Extensions** | Directories listed in `~/.config/stella/extensions.toml` that add teams, knowledge maps, persona and playbook addenda, doctor checks, the daily-log prompt, and leak-guard rules. The core never names one |

### The status line

Every turn of every session in the Stella tmux server (team leads, one-off teams, windows you opened by hand,
and Stella's own) ends with exactly one last line, so you never reread the output to ask "is anything left for me?":

```
NEXT FOR YOU: approve the push of environment status-gg (2 commits); answer the open question: which database?
ALL DONE: ready to wrap up. Type gg.
WORKING: the nightly eval is still running
```

`NEXT FOR YOU` is the one or two things only you can do or decide (a question, a decision, a deferred push, a
review to post); `ALL DONE` means nothing is unpushed, uncommitted, deferred or open for you; `WORKING` only when
background work continues after the turn. It is structural: the Stop hook reads the turn's last assistant message
and, when the line is missing or contradicts the facts (ALL DONE with unpushed commits, a deferred push, an open
needs-you flag or uncommitted changes), blocks the stop once with the exact line to write (never a loop: the
second stop of the turn passes). A deferred push is `NEXT FOR YOU` until you drop it (`stella ack push-deferred:<repo>@<sha>`)
or its commit reaches a remote. In Stella's session `NEXT FOR YOU` lists the items from `stella attention`, and
the empty case is `ALL DONE: nothing needs you.` (she is never wrapped up, so no gg). The rule is also in the
lead prompt, the team skills, Stella's persona, and the per-turn hook context.

### Wrapping up a session

You decide when a session is done. Nothing closes sessions automatically unless you turn it on.

* **`gg`:** type exactly `gg` (alone, any case) as a prompt in any Claude session in the Stella tmux server.
  A UserPromptSubmit hook handles it, so the prompt never reaches the model. It first checks that nothing is
  unpushed, uncommitted, deferred or waiting on you. If something is, it does **not** close: it says what blocks
  it in one line and, when an unpushed commit is the blocker, raises Claude Code's push prompt (never a command
  for you to run); a deferred push is not asked again, answer or drop it. If clean, it records the team as
  wrapped up, closes its orders, and closes the session and its tmux window (verified gone; an alert is raised
  if it stays). It closes `keep_open` teams (review) too, since you said so. In a session that is not a team it
  closes just that window after the same checks. In Stella's own session it is refused with one line.
* **`gg` and `tyfp`, side by side.** Both are typed alone (any case, trimmed) as a prompt in any session in the Stella
  tmux server, are handled by the hook, and never reach the model.

  | | `gg` | `tyfp` |
  | --- | --- | --- |
  | Wraps up | only the session it is typed in | every session that is done |
  | Checks | nothing unpushed, uncommitted, deferred or waiting on you | the same, for each session; plus idle at its prompt |
  | Closes | this session and its window (also `keep_open` and hand-started ones) | each clean, idle one (also `keep_open`, adopted; no grace period) |
  | Never touches | Stella's own session | busy or running sessions, blocked ones, Stella's own |
  | You get | one line if blocked (the push prompt for an unpushed commit) | one report: `wrapped up: <names>`, `left open: <name>: <reason>`; push prompts for sessions blocked only by an unpushed commit; the session you typed it in goes last |

  `stella wrapup <team>` is the same as `gg` for one named team, from outside. `stella sweep` (no argument) is the
  automatic sweep over every finished team: it records teams whose window and process are gone and, only with
  `wrapup_auto = true` (off by default), closes clean finished ones after the grace period; its notice names every
  window it closed. `gg` never runs it. `stella sweep --now` is what `tyfp` does, from a terminal.
* **Adopted sessions:** a Claude session you started by hand in the Stella tmux server is registered on its first prompt
  under its window name (archetype `adopted`), so `stella tell`, `stella fleet`, `stella pass-env --respawn`, `gg`,
  `tyfp` and `stella wrapup <team>` work on it like on a launched one. The automatic sweep never closes it.
* **No tmux, no scheduler:** a hook runs in Claude Code's command sandbox, which blocks the tmux socket and `ps`
  but allows reading process info (libproc) and signalling your own processes. So `gg` closes its own window itself,
  at once (`direct.py`): it finds its Claude process and the window's pane process (the shell the window was started
  with, or Claude itself after `exec`) by walking up the process tree, records the wrap-up, then sends SIGHUP to the
  pane process and SIGTERM to Claude (SIGKILL after 2 s if either is left); tmux then closes the pane and the sidebar
  closes the window. A clean `gg` prints at most `Wrapped up.`. Identity is the process tree, never an environment
  variable, so a `gg` can only close the window it was typed in; it refuses if its session file names another session
  or another Claude shares the pane. `tyfp` reaches the other sessions the same way: through the file each Claude
  writes (`~/.claude/sessions/<pid>.json`: pid, session id, window, idle or busy), checked against the live process
  (same start time, under a pane process of tmux). From a terminal, where tmux is reachable, `tyfp`/`sweep` still kill
  the window through tmux. Only the explicit last resort is queued for the scheduler: a `tyfp` or an adoption where the
  process tree cannot be read at all.
* **In a session:** type `/stella:wrap-up` (or run `stella wrap`); from outside, `stella wrapup <team>`. Same
  checks and closing as `gg`, one code path.
* **Resume picker:** `claude --resume` hides a transcript whose first `entrypoint` is `sdk-cli` (a `claude -p` run), even if it was later resumed by hand. `stella reopen` and the nightly job rewrite that origin to `cli` (`stella fix-resume [name|id]` does it on demand; a transcript touched in the last minute is skipped). Sessions are listed under the directory they started in, by name.
* **From Stella:** `stella reap <team>` closes a finished team's window and verifies it is gone.
* **What is ready:** `stella wrapup --dry-run` and the brief's "Finished, not wrapped up" section list each
  finished team with its one reason it is not ready (grace period of `wrapup_grace_minutes`, default 5,
  restarted when you type to it; unpushed commits; uncommitted changes; needs-you; a follow-up or deferred
  push waiting on it; `keep_open`; session busy), or "ready to wrap up". A team whose window and process
  are both gone (killed by a tmux restart, or closed by hand without `stella done`) is treated as ended whatever
  the ledger says: it has no session to close, so the scheduler records it as wrapped up when it is clean (no
  unpushed commits, nothing uncommitted, nothing asked of you), even with `wrapup_auto` off; otherwise it is
  listed with the reason. `stella fleet` and `stella pass-env` hide wrapped-up teams and show a gone one as
  `gone` instead of a `?` token. Nothing is called gone when tmux cannot be reached from where the command runs.
* **Optional automation:** `wrapup_auto = true` in the config lets the scheduler wrap up every ready team
  about once a minute (closing the window, its orders, a `wrapped_up` event and one quiet notification).
  Off by default. A team with `keep_open = true` in its `teams.toml` entry is never wrapped up automatically.

## Developing

```
uv sync
uv run pytest
```

Tests run the real CLI against a throwaway store and config; tmux tests use a private socket.

The suite is safe to run inside your own tmux: `tests/conftest.py` unsets `$TMUX`/`$TMUX_PANE`, moves tmux's default socket to a
throwaway directory and pins `STELLA_CLAUDE_PID=0`, and `stella.safety` (active when `STELLA_TEST_ROOTS` is set, which also reaches
every `stella` subprocess) refuses any tmux socket outside the tests' directories and any signal to a process that is not a
descendant of a test tmux server or of pytest. A test that needs tmux makes its socket with `conftest.sock_dir()`.
`tests/test_tmux_safety.py` is the guard. Outside tests the refusals are structural only: never pid 1, the caller, or a tmux server.
