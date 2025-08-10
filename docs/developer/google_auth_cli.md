# Google Auth CLI Tools

The `hdev` CLI now includes commands for managing Google API tokens directly, making it easier to authenticate Google services in both interactive and headless environments.

## Overview

These commands replace the standalone script at `scripts/google_token_manager.py` and provide the same functionality:

- Generate tokens using device flow authentication
- Export tokens to portable formats
- Import tokens from files or stdin

## Usage

### General Syntax

```bash
hdev gauth <command> [options]
```

### Available Commands

#### Generate a new token

```bash
# Generate a Gmail token
hdev gauth generate gmail

# Generate a Calendar token
hdev gauth generate calendar
```

This will guide you through a device flow authentication process where you'll visit a Google URL, authenticate, and then paste the provided code back into the terminal.

#### Export a token

Export tokens to share them with other environments or as backups:

```bash
# Export to file
hdev gauth export gmail --output ~/gmail_token.txt
hdev gauth export calendar --output ~/calendar_token.txt

# Export to stdout (for piping)
hdev gauth export gmail
```

#### Import a token

Import tokens from previously exported sources:

```bash
# Import from file
hdev gauth import gmail --input ~/gmail_token.txt
hdev gauth import calendar --input ~/calendar_token.txt

# Import from stdin (paste token)
hdev gauth import gmail
```

### Remote Transfer Example

To transfer tokens from a local machine to a remote one:

```bash
# On local machine, export token
hdev gauth export gmail | ssh user@remote "hdev gauth import gmail"
```

## Configuration

The tool uses the following locations:

- Token storage: `~/.hdev/credentials/`
- Client secrets file: `~/.hdev/credentials/google_clientid.json` (or specified by the `HEARE_GOOGLE_CLIENT_SECRETS` environment variable)

## Environment Variables

The following environment variables can customize behavior:

- `HEARE_GOOGLE_CLIENT_SECRETS`: Path to the client secrets JSON file
- `HEARE_GOOGLE_AUTH_METHOD`: Authentication method (`device`, `browser`, or `auto`)
- `HEARE_GMAIL_TOKEN_FILE`: Gmail token filename (default: `gmail_token.pickle`)
- `HEARE_CALENDAR_TOKEN_FILE`: Calendar token filename (default: `calendar_token.pickle`)