# Enable Powerlevel10k instant prompt. Should stay close to the top of ~/.zshrc.
# Initialization code that may require console input (password prompts, [y/n]
# confirmations, etc.) must go above this block; everything else may go below.
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# If you come from bash you might have to change your $PATH.
# export PATH=$HOME/bin:/usr/local/bin:$PATH

# Path to your oh-my-zsh installation.
if [ "$(uname 2> /dev/null)" != "Linux" ]; then
    # Not Linux, assumed to be OSX
    export ZSH="/Users/kohenchia/.oh-my-zsh"
else
    # Linux
    export ZSH="/home/kohenchia/.oh-my-zsh"
fi

# Set name of the theme to load --- if set to "random", it will
# load a random theme each time oh-my-zsh is loaded, in which case,
# to know which specific one was loaded, run: echo $RANDOM_THEME
# See https://github.com/ohmyzsh/ohmyzsh/wiki/Themes
ZSH_THEME="powerlevel10k/powerlevel10k"

# Set list of themes to pick from when loading at random
# Setting this variable when ZSH_THEME=random will cause zsh to load
# a theme from this variable instead of looking in $ZSH/themes/
# If set to an empty array, this variable will have no effect.
# ZSH_THEME_RANDOM_CANDIDATES=( "robbyrussell" "agnoster" )

# Uncomment the following line to use case-sensitive completion.
# CASE_SENSITIVE="true"

# Uncomment the following line to use hyphen-insensitive completion.
# Case-sensitive completion must be off. _ and - will be interchangeable.
# HYPHEN_INSENSITIVE="true"

# Uncomment the following line to disable bi-weekly auto-update checks.
# DISABLE_AUTO_UPDATE="true"

# Uncomment the following line to automatically update without prompting.
# DISABLE_UPDATE_PROMPT="true"

# Uncomment the following line to change how often to auto-update (in days).
# export UPDATE_ZSH_DAYS=13

# Uncomment the following line if pasting URLs and other text is messed up.
# DISABLE_MAGIC_FUNCTIONS=true

# Uncomment the following line to disable colors in ls.
# DISABLE_LS_COLORS="true"

# Uncomment the following line to disable auto-setting terminal title.
# DISABLE_AUTO_TITLE="true"

# Uncomment the following line to enable command auto-correction.
# ENABLE_CORRECTION="true"

# Uncomment the following line to display red dots whilst waiting for completion.
# COMPLETION_WAITING_DOTS="true"

# Uncomment the following line if you want to disable marking untracked files
# under VCS as dirty. This makes repository status check for large repositories
# much, much faster.
# DISABLE_UNTRACKED_FILES_DIRTY="true"

# Uncomment the following line if you want to change the command execution time
# stamp shown in the history command output.
# You can set one of the optional three formats:
# "mm/dd/yyyy"|"dd.mm.yyyy"|"yyyy-mm-dd"
# or set a custom format using the strftime function format specifications,
# see 'man strftime' for details.
# HIST_STAMPS="mm/dd/yyyy"

# Would you like to use another custom folder than $ZSH/custom?
# ZSH_CUSTOM=/path/to/new-custom-folder

# Which plugins would you like to load?
# Standard plugins can be found in $ZSH/plugins/
# Custom plugins may be added to $ZSH_CUSTOM/plugins/
# Example format: plugins=(rails git textmate ruby lighthouse)
# Add wisely, as too many plugins slow down shell startup.
plugins=(git)

source $ZSH/oh-my-zsh.sh

# User configuration

# export MANPATH="/usr/local/man:$MANPATH"

# You may need to manually set your language environment
# export LANG=en_US.UTF-8

# Preferred editor for local and remote sessions
# if [[ -n $SSH_CONNECTION ]]; then
#   export EDITOR='vim'
# else
#   export EDITOR='mvim'
# fi

# Compilation flags
# export ARCHFLAGS="-arch x86_64"

# Set personal aliases, overriding those provided by oh-my-zsh libs,
# plugins, and themes. Aliases can be placed here, though oh-my-zsh
# users are encouraged to define aliases within the ZSH_CUSTOM folder.
# For a full list of active aliases, run `alias`.
#
# Example aliases
# alias zshconfig="mate ~/.zshrc"
# alias ohmyzsh="mate ~/.oh-my-zsh"
source ~/.oh-my-zsh/custom/themes/powerlevel10k/powerlevel10k.zsh-theme

# To customize prompt, run `p10k configure` or edit ~/.p10k.zsh.
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# ====================================
# Custom

export POWERLEVEL9K_COMMAND_EXECUTION_TIME_THRESHOLD=0

function drawline() {
    printf %"$COLUMNS"s | tr " " "-"
}

function ff() {
    find . -type f -name ${@}
}

function fd() {
    find . -type d -name ${@}
}

# Git aliases
unalias ga
alias ga='git add -A'
unalias gb
alias gb='git branch'
unalias gc
alias gc='git commit -v -m'  # This will force a commit message to be provided
unalias gd
alias gd='git diff -w "$@"'
alias ghist="git log --pretty=format:'%h %ad | %s%d [%an]' --graph --date=short"
function glc
{
    echo Counting all lines in the ${1:-master} branch...
    wc -l `git ls-tree -r ${1:-master} --name-only`
}
unalias gm
alias gm='git merge --no-commit --no-ff'
alias gpush='git push -f --tags -u origin "$@"'
alias gs='git status -s'
unalias gup
alias gup='git fetch --prune && git fetch --prune origin "+refs/tags/*:refs/tags/*" && git rebase -r'

# k8s
alias k='kubectl'

function ssd
{
    docker exec -e COLUMNS="`tput cols`" -e LINES="`tput lines`" -it ${1} sh -l
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
        echo "You are already in a virtualenv: ${VIRTUAL_ENV}"
        return 1
    fi

    if ! type "pyenv" > /dev/null 2>&1; then
        "Please first install pyenv on your system."
        return 1
    fi

    if [[ -z $1 ]]; then
        echo "Usage: vc <python_version>"
        echo ""
        echo "Available Python versions:"
        pyenv versions
        return 1
    fi

    if ! pyenv local $1; then
        echo ""
        echo "Available Python versions:"
        pyenv versions
        return 1
    fi

    # Upgrade pyenv's version of virtualenv and pip
    pip install --upgrade virtualenv pip

    # Create the virtualenv
    virtualenv .virtualenv -p python3

    # Activate the virtualenv
    ve

    # Upgrade the virtualenv's version of pip
    pip install --upgrade pip

    # Install additional stuff
    pip install pipdeptree requests arrow flake8 black mypy

    # Cleanup: Remove pyenv reference since we are now using the virtualenv
    rm .python-version
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

# Setting options
setopt PUSHDSILENT

# Aliases
alias bb='cd ~/bitbucket'
alias cf='caffeinate'
alias cputemp='sudo powermetrics --samplers smc | grep -i "CPU die temperature"'
alias d='docker'
alias dcp='docker-compose'
alias dev='cd ~/development'
alias gh='cd ~/github'
alias home='cd ~'
alias l='ls -lFh'
alias ll='ls -alFh'
alias p='python'
alias p3='python3'
alias pdp='pipdeptree'
alias pdt='pipdeptree'
alias pvd='echo Starting debupy server at port 17778. Waiting for client...; p -ic "import debugpy; debugpy.listen(17778); debugpy.wait_for_client()"; print("Connected.")'
alias rn='npx react-native'
alias resetaudio='sudo kill -9 `ps ax|grep "coreaudio[a-z]" | awk "{print $1}"`'
alias tmp='cd /tmp'
alias wt='watson'

function gt() {
    branch=`git branch 2> /dev/null | sed -n -e 's/^\* \(.*\)/\1/p'`
    git ls-tree -r --name-only ${1:-${branch}}
}

# Application shortcuts
if [ "$(uname 2> /dev/null)" != "Linux" ]; then
    # Not Linux, assumed to be OSX
    alias a='open -a Atom'
    alias m='open -a MacVim'
    alias vsc='open -a Visual\ Studio\ Code'
fi

# Thid will ensure pyenv always installs Python as a framework,
# which is required for some libraries like matplotlib to control native UI elements
export PYTHON_CONFIGURE_OPTS="--enable-framework"

eval "$(pyenv init -)"

export PATH="/usr/local/opt/ruby/bin:$PATH"

# Work stuff
if [[ -e "/Users/kohenchia/.zshrc_work" ]]; then
    source /Users/kohenchia/.zshrc_work
fi


export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
