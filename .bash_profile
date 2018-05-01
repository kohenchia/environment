# Dependencies
source ~/bitbucket/environment/git-prompt.sh

# Colors
export CLICOLOR=1
export LSCOLORS=gxFxhxDxfxhxhxhxhxcxcx

IBlack='\033[38;5;8m'
IRed='\033[38;5;9m'
IGreen='\033[38;5;10m'
IYellow='\033[38;5;11m'
IBlue='\033[38;5;12m'
IMagenta='\033[38;5;13m'
ICyan='\033[38;5;14m'
IWhite='\033[38;5;15m'

# Prompt
export GIT_PS1_SHOWDIRTYSTATE=1
export GIT_PS1_SHOWUNTRACKEDFILES=1

function __ps_line_1
{
    echo "${IRed}\h:${ICyan}\w${IMagenta}"'$(__git_ps1 " (%s)")'
}

function __ps_line_2
{
    echo "${IWhite}\$ \[$(tput sgr0)\]"
}

export PS1="$(__ps_line_1)\n$(__ps_line_2)"

# Command Functions
function ga
{
    git add -A "$@"
}

function gb
{
    git branch "$@"
}

function gc
{
    git commit -m "$@"
}

function gch
{
    git checkout "$@"
}

function gf
{
    git fetch --prune
}

function ghist
{
    git log --pretty=format:'%h %ad | %s%d [%an]' --graph --date=short
}

function gl
{
    git log "$@"
}

function gs
{
    git status -s "$@"
}

function gpull
{
    git pull origin "$@"
}

function gpush
{
    git push origin "$@"
}

# Commands
alias ll='ls -alFh'
alias home='cd ~'
alias bb='cd ~/bitbucket'
alias m='open -a MacVim'
