#!/usr/bin/env bash
# Source this script to load piku environment variables
# Usage: source ~/load_env.sh

# Get the app name from current directory or parameter
APP_NAME="${1:-$(basename $(pwd))}"

# Piku environment file locations
ENV_FILE="$HOME/.piku/envs/$APP_NAME/ENV"
LIVE_ENV_FILE="$HOME/.piku/envs/$APP_NAME/LIVE_ENV"

# Function to load environment file
load_env_file() {
    local file="$1"
    if [ -f "$file" ]; then
        echo "Loading environment from $file"
        # Export all variables from the file
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
        return 0
    else
        echo "Environment file not found: $file" >&2
        return 1
    fi
}

# Load ENV file first
if load_env_file "$ENV_FILE"; then
    echo "✓ Loaded base environment"
fi

# Load LIVE_ENV file (overrides ENV)
if load_env_file "$LIVE_ENV_FILE"; then
    echo "✓ Loaded live environment"
fi

# Verify critical variables
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "⚠ Warning: ANTHROPIC_API_KEY not set" >&2
fi

if [ -z "$GH_TOKEN" ] && [ -z "$GITHUB_TOKEN" ]; then
    echo "⚠ Warning: GitHub token not set" >&2
fi

echo "Environment loaded for app: $APP_NAME"
