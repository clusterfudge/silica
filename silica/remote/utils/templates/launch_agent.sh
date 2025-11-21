#!/usr/bin/env bash
set -e

# Add pyenv to PATH if available
if [ -d /home/piku/.pyenv/shims/ ]; then
  export PATH=/home/piku/.pyenv/shims/:$PATH
fi

# Load environment variables from piku ENV files using load_env.sh
if [ -f ./load_env.sh ]; then
    source ./load_env.sh
else
    echo "WARNING: load_env.sh not found - environment variables may not be available"
fi

# Verify critical environment variables
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set"
    echo "Set it with: piku config:set ANTHROPIC_API_KEY=your-key"
    exit 1
fi

# Run setup and agent
uv run silica workspace-environment setup
uv run silica workspace-environment run