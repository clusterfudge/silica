# Migration Plan: Gmail and Google Calendar Tools to User Tools

## Implementation Status

**IMPLEMENTED (2025-12-28):**
- ✅ Phase 1: Created `~/.silica/tools/_google_auth.py` - shared authentication helper
- ✅ Phase 2: Created `~/.silica/tools/gmail.py` - 6 Gmail tools (search, read, send, read_thread, find_needing_response, forward)
- ✅ Phase 3: Created `~/.silica/tools/gcal.py` - 6 Calendar tools (list_events, create_event, delete_event, search_events, setup, list_calendars)
- ✅ Phase 4: Updated `silica/remote/cli/commands/sync_tools.py` to include all `_*.py` helpers and `*.yml` config files
- ✅ Phase 4b: Updated `silica/developer/toolbox.py` to deduplicate tools - user tools take precedence over built-in tools with same name
- ✅ Phase 6: Removed built-in Gmail/Calendar tools from `ALL_TOOLS`, moved to `silica/developer/tools/.deprecated/`
- ✅ Phase 5: Added `silica remote google-auth export/import` CLI commands for SSH-pipeable token transfer

**ALL PHASES COMPLETE!**

## Executive Summary

This document outlines the plan to migrate the built-in Gmail and Google Calendar tools from `silica/developer/tools/gmail.py` and `silica/developer/tools/gcal.py` to the user tools system (`~/.silica/tools/`). This migration will:

1. Convert the tools to self-contained, portable Python scripts
2. Enable tool sync to remote workspaces via `silica remote sync-tools`
3. Maintain backward compatibility with existing authentication flows
4. Preserve the multi-tool structure (gmail.py → 6 tools, gcal.py → 6 tools)

## Current State Analysis

### Existing Tool Structure

**Gmail Tools** (`silica/developer/tools/gmail.py`):
- `gmail_search` - Search emails using Gmail query syntax
- `gmail_read` - Read a specific email by ID
- `gmail_send` - Send an email (with cc, bcc, reply-to, markdown support)
- `gmail_read_thread` - Read all messages in a thread
- `find_emails_needing_response` - Find threads awaiting response
- `gmail_forward` - Forward a message or thread

**Calendar Tools** (`silica/developer/tools/gcal.py`):
- `calendar_list_events` - List upcoming events
- `calendar_create_event` - Create a new event
- `calendar_delete_event` - Delete an event
- `calendar_search` - Search events by keyword
- `calendar_setup` - Interactive calendar configuration
- `calendar_list_calendars` - List available calendars

### Dependencies

Both tool sets depend on:
- `google-api-python-client` - Google API client
- `google-auth-oauthlib` - OAuth authentication
- `google-auth-httplib2` - Auth transport
- `pytz` - Timezone handling
- `pyyaml` - Config file handling (calendar only)
- `markdown` - Markdown to HTML conversion (gmail only)

### Authentication System

The current authentication is in `silica/developer/tools/google_shared.py`:
- Credentials stored in `~/.hdev/credentials/`
- Client secrets in `~/.hdev/credentials/google_clientid.json`
- Token files: `gmail_token.pickle`, `calendar_token.pickle`
- Supports both browser and device code flow (for remote/headless)
- Token import/export for remote deployment

### Remote Sync System

`silica/remote/cli/commands/sync_tools.py`:
- Reads tools from `~/.silica/tools/`
- Creates tar.gz archive of selected tools + `_silica_toolspec.py` helper
- Syncs to remote workspace at `~/.silica/workspaces/{workspace}/tools/`
- Tools dir can be overridden via `SILICA_TOOLS_DIR` env var

## Migration Architecture

### File Structure

```
~/.silica/tools/
├── _silica_toolspec.py          # Existing helper (auto-generated)
├── _google_auth.py              # NEW: Shared Google auth helper
├── gmail.py                     # NEW: Multi-tool Gmail file
├── gcal.py                      # NEW: Multi-tool Calendar file
└── google-calendar.yml          # Calendar configuration (created by setup)
```

### Key Design Decisions

1. **Shared Auth Helper (`_google_auth.py`)**
   - Extract authentication code to a shared helper module
   - Prefix with `_` so it's not discovered as a tool
   - Include token import/export for remote deployment
   - Support both browser and device code flows

2. **Configuration File Location**
   - Calendar config moves to `~/.silica/tools/google-calendar.yml`
   - Or use `SILICA_TOOLS_CONFIG_DIR` env var for remote workspaces

3. **Multi-Tool File Pattern**
   - Each file exports multiple tool specs via `--toolspec`
   - Subcommands map to individual tools (e.g., `gmail.py search`)
   - Use `generate_schemas_for_commands()` helper

4. **Authorization Flow**
   - Set `requires_auth: true` in metadata
   - Implement `--authorize` flag to check/perform auth
   - Agent prompts user when auth needed

## Detailed Implementation Plan

### Phase 1: Create Auth Helper Module

**File: `~/.silica/tools/_google_auth.py`**

```python
#!/usr/bin/env python3
"""Google authentication helper for Gmail and Calendar tools.

This module is not a tool itself but provides shared authentication
functionality for Google API tools.
"""

import base64
import json
import os
import pickle
from pathlib import Path
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, Flow


def get_config_dir() -> Path:
    """Get the configuration directory, respecting env override."""
    env_dir = os.environ.get("SILICA_TOOLS_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".hdev" / "credentials"


def get_credentials_dir() -> Path:
    """Get the credentials directory."""
    env_dir = os.environ.get("SILICA_TOOLS_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".hdev" / "credentials"


def get_client_secrets_path() -> Path:
    """Get path to Google OAuth client secrets file."""
    return get_credentials_dir() / "google_clientid.json"


def get_token_path(token_file: str) -> Path:
    """Get full path to a token file."""
    return get_credentials_dir() / token_file


def check_credentials(scopes: List[str], token_file: str) -> tuple[bool, str]:
    """Check if valid credentials exist without triggering auth flow.
    
    Returns:
        (is_valid, message) tuple
    """
    token_path = get_token_path(token_file)
    
    if not token_path.exists():
        return False, f"No credentials found at {token_path}"
    
    try:
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        
        if creds.valid:
            return True, "Credentials valid"
        
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
            return True, "Credentials refreshed"
        
        return False, "Credentials expired and cannot be refreshed"
    except Exception as e:
        return False, f"Error checking credentials: {e}"


def get_credentials(scopes: List[str], token_file: str) -> Credentials:
    """Get or create Google API credentials.
    
    Supports both browser-based and device code flows.
    """
    creds_dir = get_credentials_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)
    token_path = creds_dir / token_file
    
    creds = None
    
    # Try to load existing credentials
    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
    
    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)
        return creds
    
    # Return if valid
    if creds and creds.valid:
        return creds
    
    # Need new credentials
    client_secrets = get_client_secrets_path()
    if not client_secrets.exists():
        raise FileNotFoundError(
            f"Google OAuth client secrets not found at {client_secrets}. "
            "Download from Google Cloud Console."
        )
    
    auth_method = os.environ.get("HEARE_GOOGLE_AUTH_METHOD", "auto")
    
    if auth_method == "device" or (auth_method == "auto" and not _has_display()):
        # Device code flow for remote/headless
        creds = _device_code_flow(scopes, client_secrets, token_path)
    else:
        # Browser-based flow
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secrets), scopes
            )
            creds = flow.run_local_server(port=0)
        except Exception as e:
            if auth_method == "auto":
                # Fall back to device flow
                creds = _device_code_flow(scopes, client_secrets, token_path)
            else:
                raise
    
    # Save credentials
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)
    
    return creds


def _has_display() -> bool:
    """Check if we have a display for browser-based auth."""
    return os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")


def _device_code_flow(scopes: List[str], client_secrets: Path, token_path: Path) -> Credentials:
    """Perform device code authentication flow."""
    with open(client_secrets) as f:
        client_info = json.load(f)
    
    flow = Flow.from_client_config(
        client_info,
        scopes=scopes,
        redirect_uri="urn:ietf:wg:oauth:2.0:oob",
    )
    
    auth_url, _ = flow.authorization_url(prompt="consent")
    
    print("\n" + "=" * 60)
    print("Google Authentication Required")
    print("=" * 60)
    print(f"\nVisit this URL to authenticate:\n\n{auth_url}\n")
    print("Enter the authorization code:")
    
    code = input("> ").strip()
    flow.fetch_token(code=code)
    
    return flow.credentials


def export_token(token_file: str) -> str:
    """Export a token as base64 for transfer to remote systems."""
    token_path = get_token_path(token_file)
    if not token_path.exists():
        raise FileNotFoundError(f"Token not found: {token_path}")
    
    with open(token_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def import_token(token_file: str, encoded_token: str) -> None:
    """Import a base64-encoded token."""
    token_path = get_token_path(token_file)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(token_path, "wb") as f:
        f.write(base64.b64decode(encoded_token))
```

### Phase 2: Create Gmail User Tool

**File: `~/.silica/tools/gmail.py`**

Key structure:
```python
#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "cyclopts",
#     "google-api-python-client",
#     "google-auth-oauthlib",
#     "google-auth-httplib2",
#     "markdown",
# ]
# ///

"""Gmail tools for searching, reading, and sending emails.

Provides Gmail access through the Gmail API with OAuth authentication.
Supports search, read, send, forward, and thread operations.

Metadata:
    category: communication
    tags: email, gmail, google
    creator_persona: system
    created: 2025-01-13
    long_running: false
    requires_auth: true
"""

import json
import sys
from pathlib import Path

import cyclopts

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema, generate_schemas_for_commands
from _google_auth import get_credentials, check_credentials

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

app = cyclopts.App()


@app.command()
def search(query: str, max_results: int = 10, *, toolspec: bool = False):
    """Search for emails in Gmail using Google's search syntax.
    
    Args:
        query: Gmail search query (e.g., "from:example@gmail.com", "subject:meeting", "is:unread")
        max_results: Maximum number of results to return (default: 10)
    """
    if toolspec:
        print(json.dumps(generate_schema(search, "gmail_search")))
        return
    
    # ... implementation from current gmail.py ...


@app.command()
def read(email_id: str, *, toolspec: bool = False):
    """Read the content of a specific email by its ID.
    
    Args:
        email_id: The ID of the email to read
    """
    # ... implementation ...


# ... other commands: send, read_thread, find_needing_response, forward ...


@app.default
def main(*, toolspec: bool = False, authorize: bool = False):
    """Gmail tools for email management."""
    if toolspec:
        specs = generate_schemas_for_commands([
            (search, "gmail_search"),
            (read, "gmail_read"),
            (send, "gmail_send"),
            (read_thread, "gmail_read_thread"),
            (find_needing_response, "find_emails_needing_response"),
            (forward, "gmail_forward"),
        ])
        print(json.dumps(specs))
        return
    
    if authorize:
        is_valid, message = check_credentials(GMAIL_SCOPES, "gmail_token.pickle")
        if is_valid:
            print(json.dumps({"success": True, "message": message}))
        else:
            # Trigger auth flow
            try:
                get_credentials(GMAIL_SCOPES, "gmail_token.pickle")
                print(json.dumps({"success": True, "message": "Authorization successful"}))
            except Exception as e:
                print(json.dumps({"success": False, "message": str(e)}))
        return
    
    print("Use subcommands: search, read, send, read_thread, find_needing_response, forward")
    print("Run with --help for details.")


if __name__ == "__main__":
    app()
```

### Phase 3: Create Calendar User Tool

**File: `~/.silica/tools/gcal.py`**

Similar structure to gmail.py with:
- Calendar-specific scopes
- Config file management for calendar selection
- All 6 calendar commands as subcommands

### Phase 4: Update Remote Sync

**Modifications to `sync_tools.py`:**

1. Also sync files starting with `_` that are imported by tools (e.g., `_google_auth.py`)
2. Handle config files (e.g., `google-calendar.yml`)
3. Add `--with-config` flag to include config files in sync

```python
def create_tools_archive(tool_paths: List[Path]) -> bytes:
    """Create a tar.gz archive of the specified tools."""
    buffer = BytesIO()
    tools_dir = tool_paths[0].parent if tool_paths else get_local_tools_dir()

    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        # Add specified tools
        for path in tool_paths:
            tar.add(path, arcname=path.name)

        # Always include helper modules (starting with _)
        for helper in tools_dir.glob("_*.py"):
            tar.add(helper, arcname=helper.name)
        
        # Include YAML config files
        for config in tools_dir.glob("*.yml"):
            tar.add(config, arcname=config.name)

    buffer.seek(0)
    return buffer.read()
```

### Phase 5: Token Transfer for Remote

Add a command to export/import tokens for remote deployment:

```bash
# Export tokens locally
silica auth export-tokens --output tokens.json

# On remote, import tokens
silica auth import-tokens --input tokens.json
```

Or integrate into remote create:
```bash
silica remote create --with-tools --sync-google-auth
```

## Migration Steps (Execution Order)

### Step 1: Create Helper Modules
1. Create `_google_auth.py` in `~/.silica/tools/`
2. Test auth flows work correctly
3. Test token export/import

### Step 2: Create Gmail Tool
1. Create `~/.silica/tools/gmail.py`
2. Copy implementation from current `gmail.py`
3. Update imports to use `_google_auth`
4. Test all 6 commands work
5. Verify `--toolspec` returns correct specs
6. Test `--authorize` flow

### Step 3: Create Calendar Tool
1. Create `~/.silica/tools/gcal.py`
2. Copy implementation from current `gcal.py`
3. Update config file path handling
4. Test all 6 commands work
5. Verify `--toolspec` returns correct specs

### Step 4: Update Remote Sync
1. Modify `sync_tools.py` to include helper modules
2. Add config file syncing
3. Test sync to remote workspace
4. Verify tools work on remote

### Step 5: Add Token Transfer
1. Add `silica auth export-tokens` command
2. Add `silica auth import-tokens` command
3. Integrate into remote workflow
4. Document remote auth setup

### Step 6: Deprecate Built-in Tools
1. Add deprecation warning to old tools
2. Update documentation
3. After transition period, remove from built-ins

## Testing Checklist

- [x] Gmail search works locally
- [ ] Gmail send works locally
- [ ] Gmail thread reading works
- [x] Calendar list events works
- [ ] Calendar create event works
- [x] Calendar setup works (list_calendars confirmed)
- [x] `--toolspec` returns valid JSON for all tools
- [x] `--authorize` triggers auth when needed
- [x] Token refresh works
- [ ] Device code flow works (headless)
- [ ] Tools sync to remote workspace
- [ ] Tools work on remote after sync
- [ ] Token transfer works for remote

## Backward Compatibility

1. **Old credentials still work** - Uses same token file locations
2. **Config file migration** - If old config exists, tools read it
3. **Built-in tools remain** - For transition period
4. **No breaking API changes** - Tool specs match current tools

## Open Questions

1. **Calendar config location** - Should we move to `~/.silica/tools/` or keep in `~/.config/hdev/`?
   - Recommendation: Move to tools dir for portability

2. **Token storage on remote** - Should tokens be synced or re-authed?
   - Recommendation: Support both - sync for convenience, device flow for security

3. **Interactive setup on remote** - How to handle `calendar_setup` which requires user input?
   - Recommendation: Run setup locally, sync config file

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking existing workflows | High | Keep built-in tools during transition |
| Auth token security | High | Use device flow on remote, don't sync by default |
| Config file conflicts | Medium | Support env var override for config paths |
| Dependency version conflicts | Medium | Pin dependency versions in script metadata |

## Timeline Estimate

- Phase 1 (Auth Helper): 2-3 hours
- Phase 2 (Gmail Tool): 3-4 hours
- Phase 3 (Calendar Tool): 3-4 hours
- Phase 4 (Sync Updates): 2-3 hours
- Phase 5 (Token Transfer): 2-3 hours
- Phase 6 (Deprecation): 1 hour
- Testing & Documentation: 4-6 hours

**Total: ~20-25 hours**

## Appendix: Tool Spec Examples

### Gmail Toolspec Output
```json
[
  {
    "name": "gmail_search",
    "description": "Search for emails in Gmail using Google's search syntax.",
    "input_schema": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "Gmail search query..."},
        "max_results": {"type": "integer", "description": "Maximum number of results..."}
      },
      "required": ["query"]
    }
  },
  ...
]
```

### Calendar Toolspec Output
```json
[
  {
    "name": "calendar_list_events",
    "description": "List upcoming events from Google Calendar for specific dates.",
    "input_schema": {
      "type": "object",
      "properties": {
        "days": {"type": "integer", "description": "Number of days to look ahead..."},
        "calendar_id": {"type": "string", "description": "ID of the calendar..."},
        "start_date": {"type": "string", "description": "Optional start date..."},
        "end_date": {"type": "string", "description": "Optional end date..."}
      },
      "required": []
    }
  },
  ...
]
```
