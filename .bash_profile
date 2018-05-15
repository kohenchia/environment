# Dependencies
source ~/bitbucket/environment/git-prompt.sh

# Colors
export CLICOLOR=1
export LSCOLORS=gxFxhxDxfxhxhxhxhxcxcx

IBlack='\[\033[38;5;8m\]'
IRed='\[\033[38;5;9m\]'
IGreen='\[\033[38;5;10m\]'
IYellow='\[\033[38;5;11m\]'
IBlue='\[\033[38;5;12m\]'
IMagenta='\[\033[38;5;13m\]'
ICyan='\[\033[38;5;14m\]'
IWhite='\[\033[38;5;244m\]'

# Prompt
export GIT_PS1_SHOWDIRTYSTATE=1
export GIT_PS1_SHOWUNTRACKEDFILES=1

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

function mounted_info() {
    if [[ "$PWD" == */mnt/* ]]; then
        mounted=' (Mounted)'
    else
        mounted=''
    fi
    [[ -n "$mounted" ]] && echo "$mounted"
}

# disable the default virtualenv prompt change
export VIRTUAL_ENV_DISABLE_PROMPT=1

function __ps_line_1
{
    echo "${IGreen}\$(conda_info)${IYellow}\$(virtualenv_info)${IRed}\h:${ICyan}\w${IGreen}\$(mounted_info)${IMagenta}"'$(__git_ps1 " (%s)")'
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
alias ll='ls -alFh'
alias home='cd ~'
alias bb='cd ~/bitbucket'
alias m='open -a MacVim'
alias tmp='cd /tmp'
alias mnt='cd /mnt'
alias p='python'

# added by Anaconda3 5.1.0 installer
export PATH="/anaconda3/bin:$PATH"
. /anaconda3/etc/profile.d/conda.sh
