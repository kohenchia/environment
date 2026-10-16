#!/bin/sh
# Install Stella on this machine: venv, `stella` on PATH, the store, the push gate on this repo, and
# the Claude Code plugin. Safe to re-run. Extensions install themselves afterwards (they call
# `stella ext register <dir>`).
set -eu
HERE="$(cd "$(dirname "$0")" && pwd -P)"
command -v uv >/dev/null 2>&1 || { echo "Stella needs uv (https://docs.astral.sh/uv/)." >&2; exit 1; }
command -v tmux >/dev/null 2>&1 || echo "warning: tmux not found; team windows will fall back to background sessions" >&2
uv sync --project "$HERE" --quiet
"$HERE/bin/stella" install "$@"
