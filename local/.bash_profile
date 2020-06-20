# Dependencies
source ~/bitbucket/environment/git-prompt.sh

# Don't generate .pyc files
export PYTHONDONTWRITEBYTECODE=1

# Colors
export CLICOLOR=1
export LSCOLORS=gxFxhxDxCxhxhxhxhxcxcx

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

function ff() {
    find . -type f -name ${@}
}

function fd() {
    find . -type d -name ${@}
}

# disable the default virtualenv prompt change
export VIRTUAL_ENV_DISABLE_PROMPT=1

function __ps_line_1
{
    echo "${IYellow}\$(conda_info)\$(virtualenv_info)${IRed}\h:${ICyan}\w${IOrange}\$(mounted_info)${IMagenta}"'$(__git_ps1 " (%s)")'
}

function __ps_line_2
{
    echo "\[$(tput sgr0)\]\$ "
}

export PS1="$(__ps_line_1)\n$(__ps_line_2)\[$(tput sgr0)\]"

# Argbash
function argbash-docker
{
    #!/bin/bash
    docker run -it --rm -v "$(pwd):/work" matejak/argbash "$@"
}

function argbash-init-docker
{
    #!/bin/bash
    docker run -it -e PROGRAM=argbash-init --rm -v "$(pwd):/work" matejak/argbash "$@"
}

# Command Functions
function cna
{
    conda activate "$@"
}

function cnd
{
    conda deactivate
}

function drm
{
    docker stop ${1}; docker rm ${1}
}

function drmall
{
    docker ps -aq | xargs -I {} bash -c "docker stop {}; docker rm {}"
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

function glc
{
    echo Counting all lines in the ${1:-master} branch...
    wc -l `git ls-tree -r ${1:-master} --name-only`
}

function gmr
{
    git merge --no-commit --no-ff "$@"
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

function gif
{
    palette="/tmp/palette.png"
    filters="fps=15,scale=320:-1:flags=lanczos"

    ffmpeg -i ${1} -vf "$filters,palettegen" -y $palette
    ffmpeg -i ${1} -i $palette -lavfi "$filters [x]; [x][1:v] paletteuse" -y output.gif
}

function mnt
{
    if [ "$1" = "gpu" ]; then
        sshfs ec2-user@gpu:/home/ec2-user ~/mnt/gpu
    else
        cd ~/mnt
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

# Push docker image
function push_image
{
    logincmd=$(aws ecr get-login --no-include-email)
    eval $logincmd
    docker tag ${1:?}-service:local 980036564575.dkr.ecr.us-west-2.amazonaws.com/${1:?}-service:latest
    docker push 980036564575.dkr.ecr.us-west-2.amazonaws.com/${1:?}-service:latest
}

# Log in to docker container
function ssd
{
    docker exec -e COLUMNS="`tput cols`" -e LINES="`tput lines`" -it ${1} sh -l
}

function sshswap
{
    pushd ~/.ssh
    ./swap.sh
    popd
}

# Terraform commands 
function tf
{
    terraform "$@"
}

function ta
{
    terraform apply "$@"
}

function tp
{
    terraform plan "$@"
}

function twl
{
    terraform workspace list
}

function tws
{
    terraform workspace select "$@"
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
        pyenv local 3.8.0
	    pip install virtualenv
        virtualenv .virtualenv -p python3
        ve
        pip install --upgrade pip
        pip install requests arrow flake8 black mypy
        rm .python-version
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

# Set minikube envvars
if [ -x "$(command -v minikube)" ]; then
    export MINIKUBE_IN_STYLE=true
    export MINIKUBE_WANTUPDATENOTIFICATION=true
    export MINIKUBE_REMINDERWAITPERIODINHOURS=24
fi

# Aliases
alias a='open -a Atom'
alias bb='cd ~/bitbucket'
alias d='docker'
alias dcp='docker-compose'
alias gh='cd ~/github'
alias home='cd ~'
alias l='ls -lFh'
alias ll='ls -alFh'
alias m='open -a MacVim'
alias p='python'
alias p3='python3'
alias tmp='cd /tmp'
alias vsc='open -a Visual\ Studio\ Code'

eval "$(pyenv init -)"

# Use conda from one of the pyenv Anaconda installations
# . /Users/kohenchia/.pyenv/versions/anaconda3-5.2.0/etc/profile.d/conda.sh
