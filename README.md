# kohenchia/environment

Contains scripts for setting up a new development environment.

### First-time setup

Change your default shell to `zsh`:

```
chsh -s /bin/zsh
```

Install [oh-my-zsh](https://ohmyz.sh):

```
sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"
```

Install [powerlevel10k](https://github.com/romkatv/powerlevel10k#oh-my-zsh):

```
git clone --depth=1 https://github.com/romkatv/powerlevel10k.git ${ZSH_CUSTOM:-~/.oh-my-zsh/custom}/themes/powerlevel10k
```

### Installation

```
git clone git@github.com:kohenchia/environment.git
cd environment
./setup.sh
```