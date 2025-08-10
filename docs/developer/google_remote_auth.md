# Remote Google Authentication

This document explains how to set up Google integration tools for use in remote/headless environments, where the default browser-based OAuth flow isn't suitable.

## Configuration Options

The Google integration supports several authentication methods:

1. **Browser Flow** (default): Opens a browser window on the local machine to complete authentication
2. **Device Flow**: Provides a URL and code to be entered on any device with a browser
3. **Auto Mode**: Tries browser flow first, falls back to device flow if browser flow fails

## Environment Variables

You can configure the Google authentication behavior using these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `HEARE_GOOGLE_AUTH_METHOD` | Authentication method (`browser`, `device`, or `auto`) | `auto` |
| `HEARE_GOOGLE_CLIENT_SECRETS` | Path to the client secrets JSON file | `~/.hdev/credentials/google_clientid.json` |
| `HEARE_GMAIL_TOKEN_FILE` | Name of the Gmail token file | `gmail_token.pickle` |
| `HEARE_CALENDAR_TOKEN_FILE` | Name of the Calendar token file | `calendar_token.pickle` |

## Remote Authentication Methods

### Option 1: Use Device Flow on the Remote Machine

1. Set the auth method to use device flow:
   ```bash
   export HEARE_GOOGLE_AUTH_METHOD="device"
   ```

2. Run any Google tool (e.g., `gmail_search` or `calendar_list_events`)

3. You'll see a prompt with a URL and instructions:
   ```
   Remote Google Authentication Required
   ====================================================================

   Please visit this URL on any device to authenticate:

   https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=...

   After completing the authentication, you will receive a code.
   Enter that code here:
   ```

4. Visit the URL on any device with a web browser, complete the authentication, and enter the provided code in the terminal

### Option 2: Generate Tokens on a Local Machine and Transfer to Remote

Use the token manager script to generate and transfer tokens. You have several approaches:

#### Method A: Using intermediate files (less secure)

1. On your local machine (with a browser):
   ```bash
   # Generate tokens
   python scripts/google_token_manager.py generate gmail
   python scripts/google_token_manager.py generate calendar
   
   # Export tokens to portable format
   python scripts/google_token_manager.py export gmail --output ~/gmail_token.txt
   python scripts/google_token_manager.py export calendar --output ~/calendar_token.txt
   ```

2. Transfer the token files to the remote machine (e.g., using SCP or SFTP):
   ```bash
   scp ~/gmail_token.txt ~/calendar_token.txt user@remote-host:~/
   ```

3. On the remote machine, import the tokens:
   ```bash
   python scripts/google_token_manager.py import gmail --input ~/gmail_token.txt
   python scripts/google_token_manager.py import calendar --input ~/calendar_token.txt
   ```

#### Method B: Direct pipe through SSH (more secure)

Transfer tokens directly without storing them in intermediate files:

```bash
# One-line command to transfer Gmail token
python scripts/google_token_manager.py export gmail | ssh user@remote-host "python scripts/google_token_manager.py import gmail"

# One-line command to transfer Calendar token
python scripts/google_token_manager.py export calendar | ssh user@remote-host "python scripts/google_token_manager.py import calendar"
```

This method is more secure since it avoids writing sensitive tokens to the filesystem.

### Option 3: Use a Shared Configuration Directory

If you have a shared filesystem or can mount the same directory on both machines:

1. Set up Google authentication on your local machine normally
2. Configure the remote machine to use the same token files:
   ```bash
   export HEARE_GOOGLE_CLIENT_SECRETS="/path/to/shared/google_clientid.json"
   export HEARE_GMAIL_TOKEN_FILE="/path/to/shared/gmail_token.pickle"
   export HEARE_CALENDAR_TOKEN_FILE="/path/to/shared/calendar_token.pickle"
   ```

## Security Considerations

- The exported token files contain sensitive authentication information that grants access to your Google account
- Always transfer tokens securely (e.g., using encrypted connections)
- Don't store token files in public or shared locations
- Consider setting restrictive file permissions:
  ```bash
  chmod 600 ~/.hdev/credentials/*.pickle
  ```
- When using the device flow, ensure you're visiting the correct Google authentication URL

## Troubleshooting

### Token Refresh Issues

If you encounter token refresh issues, the easiest solution is to regenerate the tokens:

```bash
# Remove existing tokens
rm ~/.hdev/credentials/gmail_token.pickle
rm ~/.hdev/credentials/calendar_token.pickle

# Generate new tokens using device flow
python scripts/google_token_manager.py generate gmail
python scripts/google_token_manager.py generate calendar
```

### Permission Issues

If you see permission errors when accessing Google services, it might be because:

1. The tokens were generated with insufficient scopes
2. The user authenticated with the tokens doesn't have access to the requested resources
3. The client ID in the client secrets file doesn't have the appropriate API enabled

In these cases, regenerate the tokens after fixing the underlying issue.

### Client Secrets File Not Found

If you get a "Client secrets file not found" error, make sure:

1. You've downloaded the OAuth client ID credentials from Google Cloud Console
2. The file is saved at the expected location (`~/.hdev/credentials/google_clientid.json` by default)
3. Or set the `HEARE_GOOGLE_CLIENT_SECRETS` environment variable to point to your client secrets file