"""
Remote authentication support for Google APIs.

This module provides authentication methods designed to work in remote/headless
environments, including device code flow and token import/export functionality.
"""

import base64
import json
import os
import pickle
import sys
from pathlib import Path
from typing import Dict, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google_auth_oauthlib.flow import Flow

# Configuration paths from main google.py
CREDENTIALS_DIR = Path.home() / ".hdev" / "credentials"
CONFIG_DIR = Path.home() / ".config" / "hdev"


def ensure_dirs():
    """Ensure the necessary directories exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials_using_device_flow(
    scopes: List[str], client_secrets_file: str, token_file: str
) -> Credentials:
    """Get credentials using the device flow authentication method.

    This method is suitable for headless/remote environments where a browser
    cannot be opened on the local machine.

    Args:
        scopes: List of API scopes to request
        client_secrets_file: Path to the client secrets file
        token_file: Path to save the resulting token

    Returns:
        The credentials object
    """
    ensure_dirs()
    token_path = CREDENTIALS_DIR / token_file

    # Try to load existing credentials
    creds = None
    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # If credentials exist but are expired, refresh them
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)
        return creds

    # If no valid credentials, start device flow
    if not creds or not creds.valid:
        # Load client secrets
        if not os.path.exists(client_secrets_file):
            raise FileNotFoundError(
                f"Client secrets file not found: {client_secrets_file}"
            )

        with open(client_secrets_file, "r") as f:
            client_info = json.load(f)

        # Create a flow using device auth
        flow = Flow.from_client_config(
            client_info,
            scopes=scopes,
            redirect_uri="urn:ietf:wg:oauth:2.0:oob",  # Non-browser redirect URI for device flow
        )

        # Generate the authorization URL
        auth_url, _ = flow.authorization_url(prompt="consent")

        # Instructions for the user
        print("\n")
        print("=" * 80)
        print("Remote Google Authentication Required")
        print("=" * 80)
        print("\nPlease visit this URL on any device to authenticate:")
        print(f"\n{auth_url}\n")
        print("After completing the authentication, you will receive a code.")
        print("Enter that code here:")

        # Get the authorization code from the user
        code = input("> ").strip()

        # Exchange code for credentials
        flow.fetch_token(code=code)
        creds = flow.credentials

        # Save the credentials
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return creds


def export_token(token_file: str, output_file: str = None) -> str:
    """Export a token to a portable format.

    Args:
        token_file: Name of the token file in the credentials directory
        output_file: Path where the exported token should be saved, or None for stdout

    Returns:
        The encoded token string if output_file is None
    """
    ensure_dirs()
    token_path = CREDENTIALS_DIR / token_file

    if not token_path.exists():
        raise FileNotFoundError(f"Token file not found: {token_path}")

    # Load the token
    with open(token_path, "rb") as f:
        token_data = f.read()

    # Encode as base64
    encoded_token = base64.b64encode(token_data).decode("utf-8")

    # Either write to file or return the encoded token
    if output_file:
        with open(output_file, "w") as f:
            f.write(encoded_token)
        print(f"Token exported to {output_file}", file=sys.stderr)
        return None
    else:
        # Return for stdout
        return encoded_token


def import_token(
    token_file: str, input_file: str = None, encoded_token: str = None
) -> None:
    """Import a token from a portable format.

    Args:
        token_file: Name to save the token as in the credentials directory
        input_file: Path to the file containing the exported token, or None to use encoded_token
        encoded_token: Encoded token string, used if input_file is None
    """
    ensure_dirs()
    token_path = CREDENTIALS_DIR / token_file

    # Get the encoded token from either file or parameter
    if input_file:
        if not os.path.exists(input_file):
            raise FileNotFoundError(f"Input file not found: {input_file}")
        with open(input_file, "r") as f:
            encoded_token = f.read().strip()
    elif encoded_token is None:
        # If neither input_file nor encoded_token provided, raise error
        raise ValueError("Either input_file or encoded_token must be provided")

    # Decode from base64
    token_data = base64.b64decode(encoded_token)

    # Write to token file
    with open(token_path, "wb") as f:
        f.write(token_data)

    print(f"Token imported and saved as {token_path}", file=sys.stderr)


# Keep backward compatibility
def export_token_to_file(token_file: str, output_file: str) -> None:
    """Export a token to a portable file format (legacy function name).

    Args:
        token_file: Name of the token file in the credentials directory
        output_file: Path where the exported token should be saved
    """
    return export_token(token_file, output_file)


def import_token_from_file(token_file: str, input_file: str) -> None:
    """Import a token from a portable file format (legacy function name).

    Args:
        token_file: Name to save the token as in the credentials directory
        input_file: Path to the file containing the exported token
    """
    return import_token(token_file, input_file)


def get_auth_info() -> Dict[str, str]:
    """Get authentication information from environment variables or return defaults.

    Returns:
        Dictionary with auth configuration
    """
    return {
        "client_secrets_file": os.environ.get(
            "HEARE_GOOGLE_CLIENT_SECRETS", str(CREDENTIALS_DIR / "google_clientid.json")
        ),
        "auth_method": os.environ.get("HEARE_GOOGLE_AUTH_METHOD", "auto"),
        "gmail_token_file": os.environ.get(
            "HEARE_GMAIL_TOKEN_FILE", "gmail_token.pickle"
        ),
        "calendar_token_file": os.environ.get(
            "HEARE_CALENDAR_TOKEN_FILE", "calendar_token.pickle"
        ),
    }


def get_credentials_auto(scopes: List[str], token_file: str) -> Credentials:
    """Get credentials using the appropriate method based on environment.

    This function will try to determine the best authentication method:
    - If running in interactive mode, uses the browser flow
    - If running in non-interactive mode, uses the device flow

    Args:
        scopes: List of API scopes to request
        token_file: Name of the token file

    Returns:
        The credentials object
    """
    auth_info = get_auth_info()
    client_secrets_file = auth_info["client_secrets_file"]
    auth_method = auth_info["auth_method"]

    # Full path to the token file
    token_path = CREDENTIALS_DIR / token_file

    # Try to load existing credentials
    creds = None
    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # If credentials exist but are expired, refresh them
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)
        return creds

    # If there are valid credentials, return them
    if creds and creds.valid:
        return creds

    # Need new credentials, determine auth method
    if auth_method == "device":
        # Use device flow
        return get_credentials_using_device_flow(
            scopes, client_secrets_file, token_file
        )
    elif auth_method == "browser" or auth_method == "auto":
        # Try to use browser flow (default)
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_file, scopes
            )
            creds = flow.run_local_server(port=0)

            # Save the credentials
            with open(token_path, "wb") as token:
                pickle.dump(creds, token)

            return creds
        except Exception as e:
            # If in auto mode and browser flow fails, try device flow
            if auth_method == "auto":
                print(f"Browser auth failed ({str(e)}), falling back to device flow...")
                return get_credentials_using_device_flow(
                    scopes, client_secrets_file, token_file
                )
            else:
                # Browser mode was explicitly requested but failed
                raise
    else:
        raise ValueError(f"Unknown auth method: {auth_method}")


def ensure_config_dir():
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_credentials(scopes: List[str], token_file: str = "token.pickle"):
    """Get or refresh credentials for the Google API.

    Args:
        scopes: List of API scopes to request
        token_file: Path to the token pickle file (default: 'token.pickle')

    Returns:
        The credentials object
    """
    # Check if we should use remote/device auth
    auth_method = os.environ.get("HEARE_GOOGLE_AUTH_METHOD", "auto")

    if auth_method in ["device", "auto"]:
        # Use the automatic method which will choose the appropriate flow
        return get_credentials_auto(scopes, token_file)

    # Original browser-based flow
    creds = None
    # The file token.pickle stores the user's access and refresh tokens
    token_path = CREDENTIALS_DIR / token_file

    # Create directory if it doesn't exist
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)

    # Try to load existing credentials
    if token_path.exists():
        with open(token_path, "rb") as token:
            creds = pickle.load(token)

    # If no valid credentials, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Look for credentials.json file
            credentials_path = CREDENTIALS_DIR / "google_clientid.json"
            client_secrets_file = os.environ.get(
                "HEARE_GOOGLE_CLIENT_SECRETS", str(credentials_path)
            )

            if not os.path.exists(client_secrets_file):
                raise FileNotFoundError(
                    f"Google credentials file not found. Please download your OAuth client ID credentials "
                    f"from Google Cloud Console and save them as {client_secrets_file} or "
                    f"set HEARE_GOOGLE_CLIENT_SECRETS environment variable."
                )

            flow = InstalledAppFlow.from_client_secrets_file(
                client_secrets_file, scopes
            )
            creds = flow.run_local_server(port=0)

        # Save the credentials for the next run
        with open(token_path, "wb") as token:
            pickle.dump(creds, token)

    return creds
