#!/bin/bash

link_file() {
    if [ -f "${2}" ]; then
        if [ -f "${2}.bak" ]; then
            unlink ${2}.bak
        fi
        mv ${2} ${2}.bak
    fi
    ln -s $(pwd)/${1} ${2}
}

link_file local/.zshrc ~/.zshrc
link_file vim/.vimrc ~/.vimrc
link_file vim/.gvimrc ~/.gvimrc

link_directory() {
    if [ -d "${2}" ]; then
        if [ -d "${2}.bak" ]; then
            unlink ${2}.bak
        fi
        mv ${2} ${2}.bak
    fi
    ln -s $(pwd)/${1} ${2}
}

link_directory vim ~/.vim
