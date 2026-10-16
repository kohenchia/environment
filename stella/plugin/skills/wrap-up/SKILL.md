---
name: wrap-up
description: Wrap up this session on the owner's say-so: close the session and its tmux window. Use when the owner types /stella:wrap-up, or says "wrap up" about the session they are in. The owner can also type `gg` alone as a prompt, which does the same without reaching the model.
---

# Wrap up this session

The owner decides when a session is done; nothing closes sessions automatically. Typing exactly `gg` (alone,
any case) in any session in the Stella tmux server does this too: a hook handles it before the model sees the
prompt, through the same code as below.

1. Run `~/.local/bin/stella wrap`. It first checks that nothing is unpushed, uncommitted, deferred or waiting on
   the owner. If something is, it closes nothing and says what in one line. If clean, it records this team (if it
   is one) as wrapped up, closes its orders, and closes this session's tmux window a few seconds later
   (`keep_open` teams too: he asked). A session that is not a team just loses its window. Stella's own session
   is never wrapped up.
2. Read its output. If it names an unpushed commit, push it now (`git push -u origin <branch>`: Claude Code
   shows the owner the yes/no prompt; never tell him to run anything), then run `stella wrap` again. For
   anything else it names, say it in one line and end with `NEXT FOR YOU: <that>`. If it says it is not inside
   tmux, or cannot reach tmux, tell the owner to type `/exit` and close the window themselves.
3. When it closed, reply with one short line saying the window is closing. Do not start other work: the window
   is about to go.

`stella wrap --dry-run` shows what would close without changing anything. From outside, Stella uses
`stella wrapup <team>`: the same checks, and the window is verified gone.
