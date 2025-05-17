#!/usr/bin/env bash
# Get the directory where this script is located
TOP=$(cd $(dirname $0) && pwd)

# Load environment variables
if [ -f ~/.profile ]; then
    . ~/.profile
fi
if [ -f ~/.bashrc ]; then
    . ~/.bashrc
fi

# Load piku-specific environment
if [ -f ~/.piku_env ]; then
    . ~/.piku_env
fi

# Synchronize dependencies
cd "${TOP}"
uv sync

# Change to the code directory and start the agent
cd "${TOP}/code"
echo "Starting the agent from $(pwd) at $(date)"
uv run hdev --dwr || echo "Agent exited with status $? at $(date)"

# If the agent exits, keep the shell open for debugging in tmux
echo "Agent process has ended. Keeping tmux session alive."