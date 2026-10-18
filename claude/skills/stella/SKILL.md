---
name: stella
description: Relay a message to Stella, Kohen's project manager and first mate. Use when a message is addressed to Stella ("Stella, …", "S, …", "S: …", "ask Stella", or the prompt hook says so), or when Kohen types /stella <message>.
---

# Stella

Stella is Kohen's project manager and first mate: he manages his projects through her, and she runs the
crew that does the work. Her operating manual is her agent definition (`claude/agents/stella.md`), loaded
only by her own session; this skill is only how any other session reaches her.

## Relaying a message

The prompt hook says when a message is for her. Do not act on it yourself:

1. Find her: `ListAgents`; she is the peer named `stella`. If she is not running, start her with
   `~/.local/bin/stella start`, then look again.
2. Send it verbatim with `SendMessage` (to `stella`), prefixed with where it came from:
   `From <this session's name> (<cwd>): <the message>`.
3. Tell Kohen in one line that you passed it on.

`/stella <message>` does the same, for when the hook did not catch it.
