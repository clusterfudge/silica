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

import base64
import json
import sys
from pathlib import Path

import cyclopts
from googleapiclient.discovery import build

sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema, generate_schemas_for_commands
from _google_auth import get_credentials, check_credentials

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

app = cyclopts.App()


def _get_service():
    """Get authenticated Gmail API service."""
    creds = get_credentials(GMAIL_SCOPES, "gmail_token.pickle")
    return build("gmail", "v1", credentials=creds)


def _extract_header(headers, name, default="Unknown"):
    """Extract a header value from Gmail message headers."""
    return next(
        (h["value"] for h in headers if h["name"].lower() == name.lower()),
        default,
    )


def _extract_body(payload):
    """Extract plain text body from a Gmail message payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8")
            # Recursively check nested parts
            if "parts" in part:
                body = _extract_body(part)
                if body:
                    return body
    elif "body" in payload and "data" in payload["body"]:
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
    return ""


@app.command()
def search(
    query: str,
    max_results: int = 10,
    *,
    toolspec: bool = False,
):
    """Search for emails in Gmail using Google's search syntax.

    Args:
        query: Gmail search query (e.g., "from:example@gmail.com", "subject:meeting", "is:unread")
        max_results: Maximum number of results to return (default: 10)
    """
    if toolspec:
        print(json.dumps(generate_schema(search, "gmail_search")))
        return

    try:
        service = _get_service()

        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])

        if not messages:
            print("No emails found matching the query.")
            return

        email_details = []
        for message in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message["id"], format="metadata")
                .execute()
            )

            headers = msg["payload"]["headers"]
            subject = _extract_header(headers, "subject", "No Subject")
            sender = _extract_header(headers, "from", "Unknown Sender")
            date = _extract_header(headers, "date", "Unknown Date")

            email_details.append(
                f"ID: {message['id']}\n"
                f"From: {sender}\n"
                f"Subject: {subject}\n"
                f"Date: {date}\n"
                f"Labels: {', '.join(msg.get('labelIds', []))}\n"
                f"Link: https://mail.google.com/mail/u/0/#inbox/{message['id']}\n"
            )

        print("Found the following emails:\n\n" + "\n---\n".join(email_details))

    except Exception as e:
        print(f"Error searching Gmail: {str(e)}")


@app.command()
def read(
    email_id: str,
    *,
    toolspec: bool = False,
):
    """Read the content of a specific email by its ID.

    Args:
        email_id: The ID of the email to read
    """
    if toolspec:
        print(json.dumps(generate_schema(read, "gmail_read")))
        return

    try:
        service = _get_service()

        message = (
            service.users()
            .messages()
            .get(userId="me", id=email_id, format="full")
            .execute()
        )

        headers = message["payload"]["headers"]
        subject = _extract_header(headers, "subject", "No Subject")
        sender = _extract_header(headers, "from", "Unknown Sender")
        date = _extract_header(headers, "date", "Unknown Date")
        to = _extract_header(headers, "to", "Unknown Recipient")

        body = _extract_body(message["payload"])

        email_details = (
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Date: {date}\n"
            f"Subject: {subject}\n"
            f"Labels: {', '.join(message.get('labelIds', []))}\n\n"
            f"Body:\n{body}"
        )

        print(email_details)

    except Exception as e:
        print(f"Error reading email: {str(e)}")


@app.command()
def send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    reply_to: str = "",
    in_reply_to: str = "",
    content_type: str = "plain",
    *,
    toolspec: bool = False,
):
    """Send an email via Gmail.

    Args:
        to: Email address(es) of the recipient(s), comma-separated for multiple
        subject: Subject line of the email
        body: Body text of the email
        cc: Email address(es) to CC, comma-separated for multiple (optional)
        bcc: Email address(es) to BCC, comma-separated for multiple (optional)
        reply_to: Email address to set in the Reply-To header (optional)
        in_reply_to: Message ID of the email being replied to (optional)
        content_type: Content type of the body - "plain", "html", or "markdown" (optional, default: "plain")
    """
    if toolspec:
        print(json.dumps(generate_schema(send, "gmail_send")))
        return

    valid_content_types = ["plain", "html", "markdown"]
    if content_type.lower() not in valid_content_types:
        print(f"Error: Invalid content_type '{content_type}'. Must be one of: {', '.join(valid_content_types)}")
        return

    try:
        service = _get_service()

        # Process body based on content type
        processed_body = body
        mime_subtype = "plain"

        if content_type.lower() == "markdown":
            import markdown
            processed_body = markdown.markdown(body)
            mime_subtype = "html"
        elif content_type.lower() == "html":
            processed_body = body
            mime_subtype = "html"

        # Construct the email
        from email.mime.text import MIMEText

        message = MIMEText(processed_body, mime_subtype)
        message["to"] = to
        message["subject"] = subject

        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc
        if reply_to:
            message["reply-to"] = reply_to

        # Get sender's email
        profile = service.users().getProfile(userId="me").execute()
        message["from"] = profile["emailAddress"]

        thread_id = None

        # Handle reply threading
        if in_reply_to:
            try:
                original_message = (
                    service.users()
                    .messages()
                    .get(userId="me", id=in_reply_to, format="metadata")
                    .execute()
                )

                thread_id = original_message.get("threadId")
                headers = original_message["payload"]["headers"]
                message_id = _extract_header(headers, "message-id", None)

                if message_id:
                    message["In-Reply-To"] = message_id
                    references = _extract_header(headers, "references", None)
                    if references:
                        message["References"] = f"{references} {message_id}"
                    else:
                        message["References"] = message_id

                # Add Re: prefix if needed
                if not subject.lower().startswith("re:"):
                    original_subject = _extract_header(headers, "subject", subject)
                    if not original_subject.lower().startswith("re:"):
                        message["subject"] = f"Re: {original_subject}"
                    else:
                        message["subject"] = original_subject

            except Exception as e:
                print(f"Warning: Error setting reply headers: {str(e)}")

        # Encode and send
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        email_body = {"raw": encoded_message}

        if thread_id:
            email_body["threadId"] = thread_id

        send_message = (
            service.users().messages().send(userId="me", body=email_body).execute()
        )

        result = f"Email sent successfully. Message ID: {send_message['id']}"
        if thread_id:
            result += f"\nAdded to thread ID: {thread_id}"

        print(result)

    except Exception as e:
        print(f"Error sending email: {str(e)}")


@app.command()
def read_thread(
    thread_or_message_id: str,
    *,
    toolspec: bool = False,
):
    """Read all messages in a Gmail thread without duplicated content.

    This tool takes either a message ID or a thread ID and prints out all
    individual messages in the thread while excluding duplicate content
    that appears in reply chains.

    Args:
        thread_or_message_id: Either a Gmail message ID or thread ID
    """
    if toolspec:
        print(json.dumps(generate_schema(read_thread, "gmail_read_thread")))
        return

    try:
        service = _get_service()

        # Determine if it's a message ID or thread ID
        try:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=thread_or_message_id, format="minimal")
                .execute()
            )
            thread_id = message.get("threadId")
        except Exception:
            thread_id = thread_or_message_id

        # Get all messages in thread
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        if not thread or "messages" not in thread:
            print(f"Could not find thread with ID: {thread_id}")
            return

        messages = thread.get("messages", [])
        if not messages:
            print("Thread found but contains no messages.")
            return

        formatted_thread = f"Thread ID: {thread_id}\n"
        formatted_thread += f"Total messages in thread: {len(messages)}\n\n"

        # Sort by date
        messages.sort(key=lambda x: int(x["internalDate"]))

        for i, msg in enumerate(messages, 1):
            headers = msg["payload"]["headers"]
            subject = _extract_header(headers, "subject", "No Subject")
            sender = _extract_header(headers, "from", "Unknown Sender")
            date = _extract_header(headers, "date", "Unknown Date")
            to = _extract_header(headers, "to", "Unknown Recipient")

            formatted_thread += f"--- Message {i}/{len(messages)} ---\n"
            formatted_thread += f"ID: {msg['id']}\n"
            formatted_thread += f"From: {sender}\n"
            formatted_thread += f"To: {to}\n"
            formatted_thread += f"Date: {date}\n"
            formatted_thread += f"Subject: {subject}\n"

            body = _extract_body(msg["payload"])

            # Remove quoted content
            clean_body = _remove_quoted_content(body)
            formatted_thread += f"\nBody:\n{clean_body}\n\n"

        print(formatted_thread)

    except Exception as e:
        print(f"Error reading thread: {str(e)}")


def _remove_quoted_content(body: str) -> str:
    """Remove quoted/reply content from email body."""
    if not body:
        return ""

    lines = body.split("\n")
    clean_lines = []
    in_quote = False

    quote_patterns = [
        "On ",
        "From: ",
        "Sent: ",
        ">",
        "|",
        "-----Original Message-----",
        "wrote:",
        "Reply to this email directly",
    ]

    for line in lines:
        if not line.strip() and not clean_lines:
            continue

        if any(line.lstrip().startswith(pattern) for pattern in quote_patterns):
            in_quote = True

        if not in_quote:
            clean_lines.append(line)

    clean_body = "\n".join(clean_lines).strip()

    # If we removed too much, return original
    if not clean_body or len(clean_body) < len(body) * 0.1:
        return body

    return clean_body


@app.command()
def find_needing_response(
    recipient_email: str = "me",
    *,
    toolspec: bool = False,
):
    """Find email threads that need a response.

    This tool efficiently searches for threads addressed to a specified recipient email
    and identifies those where the latest message might need a response.
    It returns information about threads without requiring agent inference for the discovery phase.

    Args:
        recipient_email: The email address to search for (defaults to "me", which uses the authenticated user's email)
    """
    if toolspec:
        print(json.dumps(generate_schema(find_needing_response, "find_emails_needing_response")))
        return

    try:
        service = _get_service()

        # Get actual email if "me"
        if recipient_email == "me":
            profile = service.users().getProfile(userId="me").execute()
            recipient_email = profile["emailAddress"]

        # Search for messages to recipient
        query = f"to:{recipient_email}"
        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])

        if not messages:
            print(f"No emails addressed to {recipient_email} found.")
            return

        # Get unique thread IDs
        unique_thread_ids = set()
        for message in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message["id"], format="minimal")
                .execute()
            )
            unique_thread_ids.add(msg.get("threadId"))

        threads_needing_response = []

        for thread_id in unique_thread_ids:
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            thread_messages = thread.get("messages", [])

            if not thread_messages:
                continue

            last_msg = thread_messages[-1]
            headers = last_msg["payload"]["headers"]

            subject = _extract_header(headers, "subject", "No Subject")
            sender = _extract_header(headers, "from", "Unknown Sender")
            date = _extract_header(headers, "date", "Unknown Date")
            to_field = _extract_header(headers, "to", "")

            # Check if last message was TO us (not FROM us)
            if recipient_email.lower() in to_field.lower():
                if recipient_email.lower() not in sender.lower():
                    threads_needing_response.append({
                        "thread_id": thread_id,
                        "message_id": last_msg["id"],
                        "subject": subject,
                        "sender": sender,
                        "date": date,
                        "message_count": len(thread_messages),
                    })

        if not threads_needing_response:
            print(f"No threads needing response found for {recipient_email}.")
            return

        output = f"Found {len(threads_needing_response)} threads that may need a response:\n\n"

        for i, thread in enumerate(threads_needing_response, 1):
            output += (
                f"{i}. Thread: {thread['thread_id']}\n"
                f"   Subject: {thread['subject']}\n"
                f"   From: {thread['sender']}\n"
                f"   Date: {thread['date']}\n"
                f"   Messages in thread: {thread['message_count']}\n"
                f"   Last message ID: {thread['message_id']}\n\n"
            )

        print(output)

    except Exception as e:
        print(f"Error finding emails needing response: {str(e)}")


@app.command()
def forward(
    message_or_thread_id: str,
    to: str,
    cc: str = "",
    bcc: str = "",
    additional_message: str = "",
    *,
    toolspec: bool = False,
):
    """Forward a Gmail message or thread to specified recipients.

    Args:
        message_or_thread_id: The ID of the message or thread to forward
        to: Email address(es) of the recipient(s), comma-separated for multiple
        cc: Email address(es) to CC, comma-separated for multiple (optional)
        bcc: Email address(es) to BCC, comma-separated for multiple (optional)
        additional_message: Additional message to include at the top of the forwarded content (optional)
    """
    if toolspec:
        print(json.dumps(generate_schema(forward, "gmail_forward")))
        return

    try:
        service = _get_service()

        # Try as message first, then thread
        try:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_or_thread_id, format="full")
                .execute()
            )
            messages_to_forward = [message]
            is_thread = False
        except Exception:
            try:
                thread = (
                    service.users()
                    .threads()
                    .get(userId="me", id=message_or_thread_id, format="full")
                    .execute()
                )
                messages_to_forward = thread.get("messages", [])
                is_thread = True
            except Exception:
                print(f"Could not find message or thread with ID: {message_or_thread_id}")
                return

        if not messages_to_forward:
            print("No messages found to forward.")
            return

        # Get sender email
        profile = service.users().getProfile(userId="me").execute()
        sender_email = profile["emailAddress"]

        # Build forwarded content
        forwarded_content = ""

        if additional_message:
            forwarded_content += f"{additional_message}\n\n"

        forwarded_content += "---------- Forwarded message"
        if is_thread and len(messages_to_forward) > 1:
            forwarded_content += "s"
        forwarded_content += " ----------\n\n"

        # Sort by date
        if is_thread and len(messages_to_forward) > 1:
            messages_to_forward.sort(key=lambda x: int(x["internalDate"]))

        for i, msg in enumerate(messages_to_forward):
            headers = msg["payload"]["headers"]
            original_subject = _extract_header(headers, "subject", "No Subject")
            original_sender = _extract_header(headers, "from", "Unknown Sender")
            original_date = _extract_header(headers, "date", "Unknown Date")
            original_to = _extract_header(headers, "to", "Unknown Recipient")

            if is_thread and len(messages_to_forward) > 1:
                forwarded_content += f"Message {i + 1}:\n"

            forwarded_content += f"From: {original_sender}\n"
            forwarded_content += f"Date: {original_date}\n"
            forwarded_content += f"Subject: {original_subject}\n"
            forwarded_content += f"To: {original_to}\n\n"

            body = _extract_body(msg["payload"])
            forwarded_content += f"{body}\n"

            if is_thread and i < len(messages_to_forward) - 1:
                forwarded_content += "\n--- Next message ---\n\n"

        # Get subject from first message
        first_headers = messages_to_forward[0]["payload"]["headers"]
        original_subject = _extract_header(first_headers, "subject", "No Subject")

        if not original_subject.lower().startswith("fwd:"):
            forward_subject = f"Fwd: {original_subject}"
        else:
            forward_subject = original_subject

        # Construct email
        from email.mime.text import MIMEText

        message = MIMEText(forwarded_content)
        message["to"] = to
        message["subject"] = forward_subject
        message["from"] = sender_email

        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        email_body = {"raw": encoded_message}

        send_message = (
            service.users().messages().send(userId="me", body=email_body).execute()
        )

        result = f"Email forwarded successfully. Message ID: {send_message['id']}"
        if is_thread:
            result += f"\nForwarded {len(messages_to_forward)} messages from thread"
        else:
            result += "\nForwarded 1 message"

        print(result)

    except Exception as e:
        print(f"Error forwarding email: {str(e)}")


@app.default
def main(*, toolspec: bool = False, authorize: bool = False):
    """Gmail tools for email management.

    Available commands: search, read, send, read_thread, find_needing_response, forward
    """
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
            try:
                get_credentials(GMAIL_SCOPES, "gmail_token.pickle")
                print(json.dumps({"success": True, "message": "Authorization successful"}))
            except Exception as e:
                print(json.dumps({"success": False, "message": str(e)}))
        return

    print("Gmail tools for email management.")
    print("\nAvailable commands:")
    print("  search              - Search for emails")
    print("  read                - Read a specific email")
    print("  send                - Send an email")
    print("  read_thread         - Read all messages in a thread")
    print("  find_needing_response - Find threads needing response")
    print("  forward             - Forward a message or thread")
    print("\nRun with --help for details, or use --toolspec for API spec.")


if __name__ == "__main__":
    app()
