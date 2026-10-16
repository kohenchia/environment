---
name: wrap-up
description: Wrap up this session on the owner's say-so: close the session and its tmux window. Use when the owner types /stella:wrap-up, or says "wrap up" about the session they are in.
---

# Wrap up this session

The owner decides when a session is done; nothing closes sessions automatically.

1. Run `~/.local/bin/stella wrap`. It records this team (if it is one) as wrapped up and closes this
   session's tmux window a few seconds later.
2. Read its output. If it lists unpushed commits or uncommitted changes, say so in one line (the work stays
   on disk; the owner may want to push first). If it says it is not inside tmux, or cannot reach tmux,
   tell the owner to type `/exit` and close the window themselves.
3. Reply with one short line saying the window is closing. Do not start other work: the window is about to go.

`stella wrap --dry-run` shows what would close without changing anything.
