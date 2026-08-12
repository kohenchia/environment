# Shared with .zshrc — resolve through the ~/.zprofile symlink to find the repo.
# ${(%):-%x} is the path of this file; :A resolves symlinks, :h takes its dir.
source "${${(%):-%x}:A:h}/.shell-common.zsh"
