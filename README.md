# kohenchia/environment

Contains scripts for setting up a new development environment on OSX.

### First-time setup

Change your default shell to `zsh`:

```
$ chsh -s /bin/zsh
```

Install [oh-my-zsh](https://ohmyz.sh):

```
$ sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

$ Install [powerlevel10k](https://github.com/romkatv/powerlevel10k#oh-my-zsh):

```
$ git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/themes/powerlevel10k
```

$ Install [uv](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer)

```
$ brew install uv
```

### Installation

```
$ git clone git@github.com:kohenchia/environment.git
$ cd environment
$ ./setup.sh
```

## Git Worktree Workflow

The shell config includes `wt*` commands for managing [git worktrees](https://git-scm.com/docs/git-worktree) across your repos. Worktrees let you work on multiple branches simultaneously without stashing or switching — each branch gets its own directory with a full working copy.

### Commands

| Command | Description |
|---|---|
| `wta <repo> <branch> [base]` | **Add** a worktree. Creates `~/github/<repo>-wt/<branch>/` and cds into it. |
| `wtl [repo]` | **List** all active worktrees, optionally filtered to one repo. |
| `wtc <repo> <branch>` | **Change** into an existing worktree. |
| `wtr <repo> <branch>` | **Remove** a finished worktree. Offers to delete the branch too. |

All four commands support tab completion for both `<repo>` and `<branch>` arguments.

### Directory layout

Worktrees are created alongside the main checkout, in a `-wt/` sibling directory:

```
~/github/
├── myproject/                    # main checkout (untouched)
├── myproject-wt/
│   ├── feature-a/                # worktree for feature-a branch
│   └── bugfix-123/               # worktree for bugfix-123 branch
├── otherproject/
└── otherproject-wt/
    └── refactor-api/
```

Your main checkout stays on its current branch. `git pull`, CI scripts, and other tooling that expects a clean main branch are unaffected.

### Examples

**Start a new feature:**

```bash
$ wta myproject add-login-page
# Fetches latest, creates branch add-login-page, cds into the worktree
# ✓ Worktree ready at ~/github/myproject-wt/add-login-page
```

**Branch off a specific base:**

```bash
$ wta myproject hotfix-99 origin/release-2.0
# Creates the branch from origin/release-2.0 instead of HEAD
```

**Check out an existing remote branch:**

```bash
$ wta myproject someone-elses-branch
# If the branch already exists locally, the worktree uses it as-is
```

**See what you have going:**

```bash
$ wtl
# Active worktrees:
#
#   myproject
#     /Users/you/github/myproject              abc1234 [main]
#     /Users/you/github/myproject-wt/add-login  def5678 [add-login-page]
#
#   otherproject
#     /Users/you/github/otherproject           111aaaa [main]
#     /Users/you/github/otherproject-wt/fix    222bbbb [fix-api]
```

**Jump between worktrees:**

```bash
$ wtc myproject add-login-page
# Now in ~/github/myproject-wt/add-login-page (add-login-page)

$ wtc otherproject fix-api
# Now in ~/github/otherproject-wt/fix-api (fix-api)
```

**Clean up when done:**

```bash
$ wtr myproject add-login-page
# ✓ Removed worktree ~/github/myproject-wt/add-login-page
# Delete branch 'add-login-page' too? [y/N] y
# ✓ Branch 'add-login-page' deleted
```

### Controlling the repo list

By default, tab completion and `wtl` auto-discover all git repos under `~/github/`. To restrict completions to a specific set of repos, set `WT_REPOS` before the worktree block is loaded:

```bash
# In .zshrc or a sourced file (e.g. .zshrc_work):
WT_REPOS=(myproject otherproject webapp)
```

### Tips

- **Each worktree is independent.** You can have different virtual environments, run tests, and build in each one without interference.
- **Worktrees share the same `.git` data.** Commits, branches, stashes, and reflog are shared with the main checkout. There is no extra clone overhead.
- **Don't manually delete worktree directories.** Always use `wtr` (or `git worktree remove`) so git's internal bookkeeping stays clean. If you accidentally `rm -rf` a worktree directory, run `git worktree prune` in the main checkout to clean up.
- **You can't have the same branch checked out in two places.** Git enforces this. If you need the same code in two terminals, just `cd` into the same worktree from both.