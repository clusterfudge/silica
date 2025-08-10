"""
Google authentication CLI tools for Heare

This module provides CLI tools to manage Google API tokens for remote/headless environments.
It offers functionality to:
1. Generate tokens using device flow authentication
2. Export tokens to a portable format or to stdout
3. Import tokens from a portable format or from stdin

These tools are designed to be used as subcommands on the hdev entry point:
  hdev gauth generate gmail
  hdev gauth generate calendar

  # Export options
  hdev gauth export gmail --output ~/gmail_token.txt  # to file
  hdev gauth export gmail                            # to stdout

  # Import options
  hdev gauth import gmail --input ~/gmail_token.txt  # from file
  hdev gauth import gmail                            # from stdin
"""

import sys
from typing import List

from heare.developer.tools.gcal import CALENDAR_SCOPES
from heare.developer.tools.gmail import GMAIL_SCOPES
from heare.developer.tools.google_shared import (
    get_credentials_using_device_flow,
    export_token,
    import_token,
    get_auth_info,
    ensure_dirs,
)


def google_auth(user_input: str = "", **kwargs):
    """Manage Google authentication tokens.

    This command allows you to generate, export, and import Google API tokens.

    Examples:
      gauth generate gmail - Generate a token for Gmail API
      gauth export gmail --output ~/gmail_token.txt - Export Gmail token to file
      gauth import gmail --input ~/gmail_token.txt - Import Gmail token from file
    """
    # Parse arguments
    parts = user_input.strip().split()

    if len(parts) < 1:
        print("Usage: gauth <command> [options]\n")
        print("Available commands:")
        print("- generate - Generate a new token using device flow")
        print("- export - Export a token to a portable format")
        print("- import - Import a token from a portable format\n")
        print("For more information, use: gauth <command> --help")
        return

    # Handle subcommands
    subcommand = parts[0]
    args = parts[1:]

    if subcommand == "generate":
        handle_generate(args)
    elif subcommand == "export":
        handle_export(args)
    elif subcommand == "import":
        handle_import(args)
    else:
        print(f"Unknown subcommand: {subcommand}")
        print("Available commands: generate, export, import")


def handle_generate(args: List[str]):
    """Handle the generate subcommand."""
    if not args or args[0] not in ["gmail", "calendar"]:
        print("Usage: gauth generate <service>")
        print("Where <service> is one of: gmail, calendar")
        return

    service = args[0]
    auth_info = get_auth_info()
    ensure_dirs()

    # Determine which token file and scopes to use
    if service == "gmail":
        scopes = GMAIL_SCOPES
        token_file = auth_info["gmail_token_file"]
    else:  # calendar
        scopes = CALENDAR_SCOPES
        token_file = auth_info["calendar_token_file"]

    print(f"Generating {service} token using device flow...")

    try:
        get_credentials_using_device_flow(
            scopes, auth_info["client_secrets_file"], token_file
        )
        print("\nToken generated and saved successfully!")
    except Exception as e:
        print(f"Error generating token: {str(e)}", file=sys.stderr)


def handle_export(args: List[str]):
    """Handle the export subcommand."""
    if not args or args[0] not in ["gmail", "calendar"]:
        print("Usage: gauth export <service> [--output PATH]")
        print("Where <service> is one of: gmail, calendar")
        return

    service = args[0]
    auth_info = get_auth_info()
    ensure_dirs()

    # Determine which token file to use
    if service == "gmail":
        token_file = auth_info["gmail_token_file"]
    else:  # calendar
        token_file = auth_info["calendar_token_file"]

    # Check for output file parameter
    output_file = None
    if len(args) > 1 and (args[1] == "--output" or args[1] == "-o") and len(args) > 2:
        output_file = args[2]

    try:
        if output_file:
            print(f"Exporting {service} token to {output_file}...", file=sys.stderr)
            export_token(token_file, output_file)
            print(f"Token exported to {output_file}", file=sys.stderr)
        else:
            # Export to stdout
            encoded_token = export_token(token_file)
            print(encoded_token)
    except Exception as e:
        print(f"Error exporting token: {str(e)}", file=sys.stderr)


def handle_import(args: List[str]):
    """Handle the import subcommand."""
    if not args or args[0] not in ["gmail", "calendar"]:
        print("Usage: gauth import <service> [--input PATH]")
        print("Where <service> is one of: gmail, calendar")
        return

    service = args[0]
    auth_info = get_auth_info()
    ensure_dirs()

    # Determine which token file to use
    if service == "gmail":
        token_file = auth_info["gmail_token_file"]
    else:  # calendar
        token_file = auth_info["calendar_token_file"]

    # Check for input file parameter
    input_file = None
    if len(args) > 1 and (args[1] == "--input" or args[1] == "-i") and len(args) > 2:
        input_file = args[2]

    try:
        if input_file:
            print(f"Importing {service} token from {input_file}...", file=sys.stderr)
            import_token(token_file, input_file=input_file)
            print(
                f"Token imported from {input_file} and saved successfully",
                file=sys.stderr,
            )
        else:
            # Import from stdin
            print(f"Reading {service} token from stdin...", file=sys.stderr)
            print("Paste your token and press Ctrl+D when finished:", file=sys.stderr)
            encoded_token = sys.stdin.read().strip()
            import_token(token_file, encoded_token=encoded_token)
            print("Token imported from stdin and saved successfully", file=sys.stderr)
    except Exception as e:
        print(f"Error importing token: {str(e)}", file=sys.stderr)


# CLI Tools to be registered
GOOGLE_AUTH_CLI_TOOLS = {
    "gauth": {
        "func": google_auth,
        "docstring": "Manage Google authentication tokens",
        "aliases": ["google-auth", "google_auth"],
    },
}
