#!/usr/bin/env bash
# Source this script to load piku environment variables
# Usage: source load_env.sh [app_name]

# Get the app name from parameter, or detect from current directory
# When sourced from code directory (source ../load_env.sh): pwd ends in /code
# When sourced from workspace root (source ./load_env.sh): pwd is the workspace
if [ -z "$1" ]; then
    if [[ "$(basename $(pwd))" == "code" ]]; then
        # We're in the code directory, app name is parent
        APP_NAME="$(basename $(dirname $(pwd)))"
    else
        # We're in the workspace root, app name is current directory
        APP_NAME="$(basename $(pwd))"
    fi
else
    APP_NAME="$1"
fi

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
