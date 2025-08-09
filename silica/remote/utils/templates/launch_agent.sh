#!/usr/bin/env bash
if [ -d /home/piku/.pyenv/shims/ ]; then
  export PATH=/home/piku/.pyenv/shims/:$PATH
fi
uv run silica workspace-environment setup
uv run silica workspace-environment run