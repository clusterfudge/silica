#!/usr/bin/env bash
set -e

# Add pyenv to PATH if available
if [ -d /home/piku/.pyenv/shims/ ]; then
  export PATH=/home/piku/.pyenv/shims/:$PATH
fi

# Load environment variables from piku ENV files
# This ensures they're available to all subprocesses
APP_NAME="$(basename $(pwd))"
ENV_FILE="$HOME/.piku/envs/$APP_NAME/ENV"
LIVE_ENV_FILE="$HOME/.piku/envs/$APP_NAME/LIVE_ENV"

# Function to load and export environment variables
load_env_file() {
    local file="$1"
    if [ -f "$file" ]; then
        echo "Loading environment from $file"
        while IFS='=' read -r key value; do
            # Skip comments and empty lines
            [[ $key =~ ^#.*$ ]] && continue
            [[ -z $key ]] && continue
            
            # Remove quotes from value
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            
            # Export the variable
            export "$key=$value"
        done < "$file"
    fi
}

# Load environment files
load_env_file "$ENV_FILE"
load_env_file "$LIVE_ENV_FILE"

# Verify critical environment variables
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY not set"
    echo "Set it with: piku config:set ANTHROPIC_API_KEY=your-key"
    exit 1
fi

# Run setup and agent
uv run silica workspace-environment setup
uv run silica workspace-environment run