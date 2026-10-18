# Manual sentence for Stella: the first window (to apply to `claude/agents/stella.md`)

Replace the sentence in "One space per project" that says a project's first window is his main Claude session
that "starts `cy` itself" with:

> A project's first window, named after the project, IS its main session: the `claude attach` window of the
> project's primary session (the one named like the project, else one that is blocked or working, else the most
> recently started; adopted ones count; a stopped one never). That session has no second window. A project with no
> session has a plain shell in its directory: nothing starts Claude there on its own. Renaming that window renames
> the project; closing it leaves the space's title following whichever window leads.

Also: `stella project main` no longer exists (remove it from any list of commands), and `stella crew empties
[<since>]` is new: read-only, it lists sessions started by hand in a project's directory that hold no work.
