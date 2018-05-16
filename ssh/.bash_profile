# Dependencies
source ~/bitbucket/environment/git-prompt.sh

# Colors
IBlack='\[\033[38;5;8m\]'
IRed='\[\033[38;5;9m\]'
IOrange='\[\033[38;5;208m\]'
IGreen='\[\033[38;5;10m\]'
IYellow='\[\033[38;5;11m\]'
IBlue='\[\033[38;5;12m\]'
IMagenta='\[\033[38;5;13m\]'
ICyan='\[\033[38;5;14m\]'
IWhite='\[\033[38;5;244m\]'

# Prompt
export GIT_PS1_SHOWDIRTYSTATE=1
export GIT_PS1_SHOWUNTRACKEDFILES=1

# LS colors
export LS_COLORS="no=00:fi=00:di=00;36:ln=00;95:pi=40;33:so=00;35:bd=40;33;01:cd=40;33;01:or=01;05;37;41:mi=01;05;37;41:ex=00;35:*.cmd=00;32:*.exe=00;32:*.sh=00;92:*.gz=00;31:*.bz2=00;31:*.bz=00;31:*.tz=00;31:*.rpm=00;31:*.cpio=00;31:*.t=93:*.pm=00;36:*.pod=00;96:*.conf=00;33:*.off=00;9:*.jpg=00;94:*.png=00;94:*.xcf=00;94:*.JPG=00;94:*.gif=00;94:*.pdf=00;91"

function virtualenv_info(){
    # Get Virtual Env
    if [[ -n "$VIRTUAL_ENV" ]]; then
        # Strip out the path and just leave the env name
        # venv=`python --version | sed -e 's/^Python //' -e 's/ //'`
        venv=`echo $VIRTUAL_ENV | sed -e 's/.*\/\([^/]*\)\/.virtualenv/\1/'`
    else
        # In case you don't have one activated
        venv=''
    fi
    [[ -n "$venv" ]] && echo "(v:$venv) "
}

function conda_info() {
    # Get conda env
    if [[ -n "$CONDA_PREFIX" ]]; then
        cenv=`basename $CONDA_PREFIX`
    else
        cenv=''
    fi
    [[ -n "$cenv" ]] && echo "(c:$cenv) "
}

# disable the default virtualenv prompt change
export VIRTUAL_ENV_DISABLE_PROMPT=1

function __ps_line_1
{
    echo "${IYellow}\$(conda_info)\$(virtualenv_info)${IGreen}\u@${IOrange}\h:${ICyan}\w${IMagenta}"'$(__git_ps1 " (%s)")'
}

function __ps_line_2
{
    echo "\[$(tput sgr0)\]\$ "
}

export PS1="$(__ps_line_1)\n$(__ps_line_2)\[$(tput sgr0)\]"

# Command Functions
function cna
{
    conda activate "$@"
}

function cnd
{
    conda deactivate
}

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

function gd
{
    git diff "$@"
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
    git push -u origin "$@"
}

function mnt
{
    if [[ -n "$1" ]]; then
        sshfs kohenc@"$1":/home/kohenc ~/mnt/"$1"
    fi
}

function umnt
{
    if [[ -n "$1" ]]; then
        umount ~/mnt/"$1"
    fi
}

function pd
{
    echo "Working Directory: $(pwd)"
    if [[ -n "${VIRTUAL_ENV}" ]]; then
        echo "Virtual Environment: ${VIRTUAL_ENV}"
    fi
}

function ve
{
    if [[ -n "$VIRTUAL_ENV" ]]; then
        echo "Current virtualenv: ${VIRTUAL_ENV}"
        return 1
    else
        local curdir=`pwd`
        while [[ ! -d "${curdir}/.virtualenv" && -n "${curdir}" ]]; do
            curdir=${curdir%/*}
        done
        if [[ -d "${curdir}/.virtualenv" ]]; then
            . "${curdir}/.virtualenv/bin/activate"
        else
            echo "Virtualenv not found in the hierarchy $(pwd)"
            return 1
        fi
    fi
}

function vc
{
    if [[ -n "$VIRTUAL_ENV" ]]; then
        echo "Current virtualenv: ${VIRTUAL_ENV}"
        return 1
    else
        virtualenv .virtualenv -p python3
        ve
    fi
}

function vd
{
    if [[ -n "$VIRTUAL_ENV" ]]; then
        deactivate
    else
        echo "Not currently in a virtualenv"
        return 1
    fi
}

# Commands
alias ll='ls -alFh --color'
alias home='cd ~'
alias bb='cd ~/bitbucket'
alias tmp='cd /tmp'
alias p='python'
alias nv='nvidia-smi'
