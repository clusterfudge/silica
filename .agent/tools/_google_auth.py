#!/usr/bin/env python3
"""Google authentication helper for Gmail and Calendar tools.

This module is not a tool itself but provides shared authentication
functionality for Google API tools. It's prefixed with _ so it won't
be discovered as a tool but will be synced to remote workspaces.

Supports:
- Browser-based OAuth flow (local development)
- Device code flow (remote/headless environments)
- Token refresh
- Token export/import for remote deployment
"""

import base64
import json
import os
import pickle
from pathlib import Path
from typing import List, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow, Flow


def get_credentials_dir() -> Path:
    """Get the credentials directory.
    
    Respects SILICA_GOOGLE_CREDENTIALS_DIR env var for remote workspaces,
    otherwise uses ~/.hdev/credentials/ for backward compatibility.
    """
    env_dir = os.environ.get("SILICA_GOOGLE_CREDENTIALS_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".hdev" / "credentials"


def get_config_dir() -> Path:
    """Get the configuration directory for tool configs like calendar settings.
    
    Respects SILICA_GOOGLE_CONFIG_DIR env var, otherwise uses ~/.config/hdev/
    """
    env_dir = os.environ.get("SILICA_GOOGLE_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".config" / "hdev"


def get_client_secrets_path() -> Path:
    """Get path to Google OAuth client secrets file."""
    env_path = os.environ.get("HEARE_GOOGLE_CLIENT_SECRETS")
    if env_path:
        return Path(env_path)
    return get_credentials_dir() / "google_clientid.json"


def get_token_path(token_file: str) -> Path:
    """Get full path to a token file."""
    return get_credentials_dir() / token_file


def ensure_credentials_dir() -> Path:
    """Ensure the credentials directory exists and return its path."""
    creds_dir = get_credentials_dir()
    creds_dir.mkdir(parents=True, exist_ok=True)
    return creds_dir


def ensure_config_dir() -> Path:
    """Ensure the config directory exists and return its path."""
    config_dir = get_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def check_credentials(scopes: List[str], token_file: str) -> Tuple[bool, str]:
    """Check if valid credentials exist without triggering auth flow.
    
    This is used by the --authorize flag to check auth status.
    
    Args:
        scopes: List of OAuth scopes (used for context, not validation)
        token_file: Name of the token pickle file
    
    Returns:
        (is_valid, message) tuple
    """
    token_path = get_token_path(token_file)
    
    if not token_path.exists():
        return False, f"No credentials found. Please authenticate first."
    
    try:
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        
        if creds.valid:
            return True, "Credentials are valid"
        
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)
                return True, "Credentials refreshed successfully"
            except Exception as e:
                return False, f"Failed to refresh credentials: {e}"
        
        return False, "Credentials expired and cannot be refreshed"
    except Exception as e:
        return False, f"Error checking credentials: {e}"


def get_credentials(scopes: List[str], token_file: str) -> Credentials:
    """Get or create Google API credentials.
    
    Attempts to load existing credentials, refresh if expired, or
    initiate a new OAuth flow if needed.
    
    Supports both browser-based and device code flows based on:
    - HEARE_GOOGLE_AUTH_METHOD env var ("browser", "device", or "auto")
    - Automatic detection of display availability
    
    Args:
        scopes: List of OAuth scopes to request
        token_file: Name of the token pickle file
    
    Returns:
        Valid Credentials object
    
    Raises:
        FileNotFoundError: If client secrets file is not found
        Exception: If authentication fails
    """
    ensure_credentials_dir()
    token_path = get_token_path(token_file)
    
    creds = None
    
    # Try to load existing credentials
    if token_path.exists():
        try:
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
        except Exception:
            # Corrupted token file, will re-authenticate
            creds = None
    
    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
            return creds
        except Exception:
            # Refresh failed, will re-authenticate
            creds = None
    
    # Return if valid
    if creds and creds.valid:
        return creds
    
    # Need new credentials - check for client secrets
    client_secrets = get_client_secrets_path()
    if not client_secrets.exists():
        raise FileNotFoundError(
            f"Google OAuth client secrets not found at {client_secrets}.\n"
            "Please download your OAuth 2.0 Client ID credentials from the "
            "Google Cloud Console and save them to this location.\n"
            "You can also set HEARE_GOOGLE_CLIENT_SECRETS environment variable."
        )
    
    # Determine auth method
    auth_method = os.environ.get("HEARE_GOOGLE_AUTH_METHOD", "auto")
    
    if auth_method == "device":
        creds = _device_code_flow(scopes, client_secrets)
    elif auth_method == "browser":
        creds = _browser_flow(scopes, client_secrets)
    else:  # auto
        if _has_display():
            try:
                creds = _browser_flow(scopes, client_secrets)
            except Exception:
                # Fall back to device flow
                creds = _device_code_flow(scopes, client_secrets)
        else:
            creds = _device_code_flow(scopes, client_secrets)
    
    # Save credentials
    with open(token_path, "wb") as f:
        pickle.dump(creds, f)
    
    return creds


def _has_display() -> bool:
    """Check if we have a display for browser-based auth."""
    # Check common display environment variables
    if os.environ.get("DISPLAY"):
        return True
    if os.environ.get("WAYLAND_DISPLAY"):
        return True
    # macOS doesn't set DISPLAY but has a display
    if os.environ.get("TERM_PROGRAM") or os.path.exists("/Applications"):
        return True
    return False


def _browser_flow(scopes: List[str], client_secrets: Path) -> Credentials:
    """Perform browser-based OAuth flow."""
    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_secrets), scopes
    )
    return flow.run_local_server(port=0)


def _device_code_flow(scopes: List[str], client_secrets: Path) -> Credentials:
    """Perform device code authentication flow for headless environments."""
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
    print(f"\nVisit this URL to authenticate:\n")
    print(auth_url)
    print(f"\nAfter authorizing, enter the code shown:")
    
    code = input("> ").strip()
    flow.fetch_token(code=code)
    
    print("Authentication successful!")
    return flow.credentials


def export_token(token_file: str) -> str:
    """Export a token as base64 for transfer to remote systems.
    
    Args:
        token_file: Name of the token pickle file
    
    Returns:
        Base64-encoded token string
    
    Raises:
        FileNotFoundError: If token file doesn't exist
    """
    token_path = get_token_path(token_file)
    if not token_path.exists():
        raise FileNotFoundError(f"Token not found: {token_path}")
    
    with open(token_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def import_token(token_file: str, encoded_token: str) -> None:
    """Import a base64-encoded token.
    
    Args:
        token_file: Name to save the token as
        encoded_token: Base64-encoded token string
    """
    ensure_credentials_dir()
    token_path = get_token_path(token_file)
    
    with open(token_path, "wb") as f:
        f.write(base64.b64decode(encoded_token))


def export_all_google_tokens() -> dict:
    """Export all Google tokens as a dictionary.
    
    Returns:
        Dictionary with token names as keys and base64-encoded tokens as values
    """
    tokens = {}
    creds_dir = get_credentials_dir()
    
    for token_file in ["gmail_token.pickle", "calendar_token.pickle"]:
        token_path = creds_dir / token_file
        if token_path.exists():
            with open(token_path, "rb") as f:
                tokens[token_file] = base64.b64encode(f.read()).decode("utf-8")
    
    return tokens


def import_all_google_tokens(tokens: dict) -> None:
    """Import multiple Google tokens from a dictionary.
    
    Args:
        tokens: Dictionary with token names as keys and base64-encoded tokens as values
    """
    ensure_credentials_dir()
    
    for token_file, encoded_token in tokens.items():
        import_token(token_file, encoded_token)
