from googleapiclient.discovery import build

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool
from silica.developer.tools.google_shared import get_credentials

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


@tool
def gmail_search(context: "AgentContext", query: str, max_results: int = 10) -> str:
    """Search for emails in Gmail using Google's search syntax.

    Args:
        query: Gmail search query (e.g., "from:example@gmail.com", "subject:meeting", "is:unread")
        max_results: Maximum number of results to return (default: 10)
    """
    try:
        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Execute the search query
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])

        if not messages:
            return "No emails found matching the query."

        # Get full message details for each result
        email_details = []
        for message in messages:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message["id"], format="metadata")
                .execute()
            )

            # Extract headers
            headers = msg["payload"]["headers"]
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"),
                "Unknown Date",
            )

            # Format the email details
            email_details.append(
                f"ID: {message['id']}\n"
                f"From: {sender}\n"
                f"Subject: {subject}\n"
                f"Date: {date}\n"
                f"Labels: {', '.join(msg.get('labelIds', []))}\n"
                f"Link: https://mail.google.com/mail/u/0/#inbox/{message['id']}\n"
            )

        # Return the formatted results
        return "Found the following emails:\n\n" + "\n---\n".join(email_details)

    except Exception as e:
        return f"Error searching Gmail: {str(e)}"


@tool
def gmail_read(context: "AgentContext", email_id: str) -> str:
    """Read the content of a specific email by its ID.

    Args:
        email_id: The ID of the email to read
    """
    try:
        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Get the full message
        message = (
            service.users()
            .messages()
            .get(userId="me", id=email_id, format="full")
            .execute()
        )

        # Extract headers
        headers = message["payload"]["headers"]
        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"),
            "No Subject",
        )
        sender = next(
            (h["value"] for h in headers if h["name"].lower() == "from"),
            "Unknown Sender",
        )
        date = next(
            (h["value"] for h in headers if h["name"].lower() == "date"), "Unknown Date"
        )
        to = next(
            (h["value"] for h in headers if h["name"].lower() == "to"),
            "Unknown Recipient",
        )

        # Extract message body
        body = ""
        if "parts" in message["payload"]:
            for part in message["payload"]["parts"]:
                if part["mimeType"] == "text/plain" and "data" in part["body"]:
                    import base64

                    body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                        "utf-8"
                    )
                    break
        elif "body" in message["payload"] and "data" in message["payload"]["body"]:
            import base64

            body = base64.urlsafe_b64decode(message["payload"]["body"]["data"]).decode(
                "utf-8"
            )

        # Format the email details
        email_details = (
            f"From: {sender}\n"
            f"To: {to}\n"
            f"Date: {date}\n"
            f"Subject: {subject}\n"
            f"Labels: {', '.join(message.get('labelIds', []))}\n\n"
            f"Body:\n{body}"
        )

        return email_details

    except Exception as e:
        return f"Error reading email: {str(e)}"


@tool
def gmail_send(
    context: "AgentContext",
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    reply_to: str = "",
    in_reply_to: str = "",
    content_type: str = "plain",
) -> str:
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
    # Validate content_type parameter first (before any API calls)
    valid_content_types = ["plain", "html", "markdown"]
    if content_type.lower() not in valid_content_types:
        return f"Error: Invalid content_type '{content_type}'. Must be one of: {', '.join(valid_content_types)}"

    try:
        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Process body based on content type
        processed_body = body
        mime_subtype = "plain"

        if content_type.lower() == "markdown":
            # Convert markdown to HTML
            import markdown

            processed_body = markdown.markdown(body)
            mime_subtype = "html"
        elif content_type.lower() == "html":
            processed_body = body
            mime_subtype = "html"
        else:  # plain text
            processed_body = body
            mime_subtype = "plain"

        # Construct the email
        import base64
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

        # Get the sender's email address
        profile = service.users().getProfile(userId="me").execute()
        message["from"] = profile["emailAddress"]

        # Initialize thread information
        thread_id = None

        # If this is a reply, add the appropriate headers and set thread_id
        if in_reply_to:
            try:
                # Get the original message to extract necessary headers and thread ID
                original_message = (
                    service.users()
                    .messages()
                    .get(userId="me", id=in_reply_to, format="metadata")
                    .execute()
                )

                # Extract the threadId from the original message
                thread_id = original_message.get("threadId")

                # Extract headers from the original message
                headers = original_message["payload"]["headers"]
                message_id = next(
                    (h["value"] for h in headers if h["name"].lower() == "message-id"),
                    None,
                )

                # Set the In-Reply-To and References headers
                if message_id:
                    message["In-Reply-To"] = message_id

                    # Check if there's already a References header
                    references = next(
                        (
                            h["value"]
                            for h in headers
                            if h["name"].lower() == "references"
                        ),
                        None,
                    )

                    # Set or append to References header
                    if references:
                        message["References"] = f"{references} {message_id}"
                    else:
                        message["References"] = message_id

                # If subject doesn't already start with Re:, add it
                if not subject.lower().startswith("re:"):
                    original_subject = next(
                        (h["value"] for h in headers if h["name"].lower() == "subject"),
                        subject,
                    )
                    # If original subject already had Re: prefix, don't add another one
                    if original_subject.lower().startswith("re:"):
                        message["subject"] = original_subject
                    else:
                        message["subject"] = f"Re: {original_subject}"

            except Exception as e:
                # Log the error but continue sending the email
                print(f"Error setting reply headers: {str(e)}")

        # Encode the message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Create the email message body
        email_body = {"raw": encoded_message}

        # If replying to an existing message, include the threadId
        if thread_id:
            email_body["threadId"] = thread_id

        # Send the email
        send_message = (
            service.users().messages().send(userId="me", body=email_body).execute()
        )

        result = f"Email sent successfully. Message ID: {send_message['id']}"
        if thread_id:
            result += f"\nAdded to thread ID: {thread_id}"

        return result

    except Exception as e:
        return f"Error sending email: {str(e)}"

    except Exception as e:
        return f"Error sending email: {str(e)}"


@tool
def gmail_read_thread(context: "AgentContext", thread_or_message_id: str) -> str:
    """Read all messages in a Gmail thread without duplicated content.

    This tool takes either a message ID or a thread ID and prints out all
    individual messages in the thread while excluding duplicate content
    that appears in reply chains.

    Args:
        thread_or_message_id: Either a Gmail message ID or thread ID
    """
    try:
        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Determine if the ID is a message ID or thread ID
        # First, try to get it as a message
        try:
            message = (
                service.users()
                .messages()
                .get(userId="me", id=thread_or_message_id, format="minimal")
                .execute()
            )
            thread_id = message.get("threadId")
        except Exception:
            # If that fails, assume it's a thread ID
            thread_id = thread_or_message_id

        # Get all messages in the thread
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )

        if not thread or "messages" not in thread:
            return f"Could not find thread with ID: {thread_id}"

        messages = thread.get("messages", [])
        if not messages:
            return "Thread found but contains no messages."

        # Process and format the messages
        formatted_thread = f"Thread ID: {thread_id}\n"
        formatted_thread += f"Total messages in thread: {len(messages)}\n\n"

        # Process each message in chronological order (oldest first)
        messages.sort(key=lambda x: int(x["internalDate"]))

        for i, message in enumerate(messages, 1):
            # Extract headers
            headers = message["payload"]["headers"]
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"),
                "Unknown Date",
            )
            to = next(
                (h["value"] for h in headers if h["name"].lower() == "to"),
                "Unknown Recipient",
            )

            # Format message header
            formatted_thread += f"--- Message {i}/{len(messages)} ---\n"
            formatted_thread += f"ID: {message['id']}\n"
            formatted_thread += f"From: {sender}\n"
            formatted_thread += f"To: {to}\n"
            formatted_thread += f"Date: {date}\n"
            formatted_thread += f"Subject: {subject}\n"

            # Extract message body
            body = ""

            def extract_body_content(message_part):
                """Recursively extract the text content from message parts."""
                if message_part.get(
                    "mimeType"
                ) == "text/plain" and "data" in message_part.get("body", {}):
                    import base64

                    text = base64.urlsafe_b64decode(
                        message_part["body"]["data"]
                    ).decode("utf-8")
                    return text

                if message_part.get("parts"):
                    for part in message_part["parts"]:
                        content = extract_body_content(part)
                        if content:
                            return content

                return None

            # Try to extract text content
            if "parts" in message["payload"]:
                for part in message["payload"]["parts"]:
                    extracted = extract_body_content(part)
                    if extracted:
                        body = extracted
                        break
            elif "body" in message["payload"] and "data" in message["payload"]["body"]:
                import base64

                body = base64.urlsafe_b64decode(
                    message["payload"]["body"]["data"]
                ).decode("utf-8")

            # Attempt to remove quoted text/previous messages
            clean_body = ""
            if body:
                # Split by common email quote indicators
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
                    # Skip blank lines at the start
                    if not line.strip() and not clean_lines:
                        continue

                    # Check if this line starts a quoted section
                    if any(
                        line.lstrip().startswith(pattern) for pattern in quote_patterns
                    ):
                        in_quote = True

                    # Keep lines that aren't in quoted sections
                    if not in_quote:
                        clean_lines.append(line)

                clean_body = "\n".join(clean_lines).strip()

                # If we removed too much or couldn't parse correctly, use the original
                if not clean_body or len(clean_body) < len(body) * 0.1:
                    clean_body = body

            # Add the cleaned body to the output
            formatted_thread += f"\nBody:\n{clean_body}\n\n"

        return formatted_thread

    except Exception as e:
        return f"Error reading thread: {str(e)}"


@tool
def find_emails_needing_response(
    context: "AgentContext", recipient_email: str = "me"
) -> str:
    """Find email threads that need a response.

    This tool efficiently searches for threads addressed to a specified recipient email
    and identifies those where the latest message might need a response.
    It returns information about threads without requiring agent inference for the discovery phase.

    Args:
        recipient_email: The email address to search for (defaults to "me", which uses the authenticated user's email)
                        Set to a specific email address to check emails for that address
    """
    try:
        # Process the recipient_email parameter
        if recipient_email == "me":
            # Get credentials for Gmail API to find authenticated user's email
            creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
            service = build("gmail", "v1", credentials=creds)
            profile = service.users().getProfile(userId="me").execute()
            recipient_email = profile["emailAddress"]

        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Search for messages sent to the recipient email (without unread filter)
        query = f"to:{recipient_email}"
        results = service.users().messages().list(userId="me", q=query).execute()
        messages = results.get("messages", [])

        if not messages:
            return f"No emails addressed to {recipient_email} found."

        # Extract unique thread IDs
        unique_thread_ids = set()
        for message in messages:
            # Get the thread ID without fetching the full message
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=message["id"], format="minimal")
                .execute()
            )
            thread_id = msg.get("threadId")
            unique_thread_ids.add(thread_id)

        # Process each unique thread to determine if it needs a response
        threads_needing_response = []

        for thread_id in unique_thread_ids:
            # Get all messages in the thread
            thread = service.users().threads().get(userId="me", id=thread_id).execute()
            thread_messages = thread.get("messages", [])

            # Examine the last message in the thread
            last_msg = thread_messages[-1]

            # Extract headers from the last message
            headers = last_msg["payload"]["headers"]

            # Extract key information
            subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"),
                "Unknown Date",
            )
            to_field = next(
                (h["value"] for h in headers if h["name"].lower() == "to"), ""
            )

            # If the last message was sent TO our recipient email (not FROM it)
            # This means our recipient hasn't responded yet
            if recipient_email.lower() in to_field.lower():
                # Check if the sender is not the recipient (to avoid counting self-sent emails)
                if recipient_email.lower() not in sender.lower():
                    # Format thread information
                    thread_info = {
                        "thread_id": thread_id,
                        "message_id": last_msg["id"],
                        "subject": subject,
                        "sender": sender,
                        "date": date,
                        "message_count": len(thread_messages),
                    }
                    threads_needing_response.append(thread_info)

        # Format the results
        if not threads_needing_response:
            return f"No threads needing response found for {recipient_email}."

        # Format output
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

        return output

    except Exception as e:
        return f"Error finding emails needing response: {str(e)}"


@tool
def gmail_forward(
    context: "AgentContext",
    message_or_thread_id: str,
    to: str,
    cc: str = "",
    bcc: str = "",
    additional_message: str = "",
) -> str:
    """Forward a Gmail message or thread to specified recipients.

    Args:
        message_or_thread_id: The ID of the message or thread to forward
        to: Email address(es) of the recipient(s), comma-separated for multiple
        cc: Email address(es) to CC, comma-separated for multiple (optional)
        bcc: Email address(es) to BCC, comma-separated for multiple (optional)
        additional_message: Additional message to include at the top of the forwarded content (optional)
    """
    try:
        # Get credentials for Gmail API
        creds = get_credentials(GMAIL_SCOPES, token_file="gmail_token.pickle")
        service = build("gmail", "v1", credentials=creds)

        # Determine if we're forwarding a single message or a thread
        try:
            # Try to get it as a message first
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_or_thread_id, format="full")
                .execute()
            )
            messages_to_forward = [message]
            is_thread = False
        except Exception:
            # If that fails, try to get it as a thread
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
                return (
                    f"Could not find message or thread with ID: {message_or_thread_id}"
                )

        if not messages_to_forward:
            return "No messages found to forward."

        # Get the sender's email address
        profile = service.users().getProfile(userId="me").execute()
        sender_email = profile["emailAddress"]

        # Build the forwarded content
        forwarded_content = ""

        if additional_message:
            forwarded_content += f"{additional_message}\n\n"

        forwarded_content += "---------- Forwarded message"
        if is_thread:
            forwarded_content += "s"
        forwarded_content += " ----------\n\n"

        # Process each message (for threads, sort by date)
        if is_thread and len(messages_to_forward) > 1:
            messages_to_forward.sort(key=lambda x: int(x["internalDate"]))

        for i, msg in enumerate(messages_to_forward):
            # Extract headers
            headers = msg["payload"]["headers"]
            original_subject = next(
                (h["value"] for h in headers if h["name"].lower() == "subject"),
                "No Subject",
            )
            original_sender = next(
                (h["value"] for h in headers if h["name"].lower() == "from"),
                "Unknown Sender",
            )
            original_date = next(
                (h["value"] for h in headers if h["name"].lower() == "date"),
                "Unknown Date",
            )
            original_to = next(
                (h["value"] for h in headers if h["name"].lower() == "to"),
                "Unknown Recipient",
            )

            # Add message header info
            if is_thread and len(messages_to_forward) > 1:
                forwarded_content += f"Message {i + 1}:\n"

            forwarded_content += f"From: {original_sender}\n"
            forwarded_content += f"Date: {original_date}\n"
            forwarded_content += f"Subject: {original_subject}\n"
            forwarded_content += f"To: {original_to}\n\n"

            # Extract message body
            body = ""

            def extract_body_content(message_part):
                """Recursively extract the text content from message parts."""
                if message_part.get(
                    "mimeType"
                ) == "text/plain" and "data" in message_part.get("body", {}):
                    import base64

                    text = base64.urlsafe_b64decode(
                        message_part["body"]["data"]
                    ).decode("utf-8")
                    return text

                if message_part.get("parts"):
                    for part in message_part["parts"]:
                        content = extract_body_content(part)
                        if content:
                            return content
                return None

            # Try to extract text content
            if "parts" in msg["payload"]:
                for part in msg["payload"]["parts"]:
                    extracted = extract_body_content(part)
                    if extracted:
                        body = extracted
                        break
            elif "body" in msg["payload"] and "data" in msg["payload"]["body"]:
                import base64

                body = base64.urlsafe_b64decode(msg["payload"]["body"]["data"]).decode(
                    "utf-8"
                )

            # Add the message body
            forwarded_content += f"{body}\n"

            # Add separator between messages in a thread
            if is_thread and i < len(messages_to_forward) - 1:
                forwarded_content += "\n--- Next message ---\n\n"

        # Create the forward subject
        # Use the subject from the first message
        first_message_headers = messages_to_forward[0]["payload"]["headers"]
        original_subject = next(
            (
                h["value"]
                for h in first_message_headers
                if h["name"].lower() == "subject"
            ),
            "No Subject",
        )

        # Add "Fwd: " prefix if not already present
        if not original_subject.lower().startswith("fwd:"):
            forward_subject = f"Fwd: {original_subject}"
        else:
            forward_subject = original_subject

        # Construct the email
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(forwarded_content)
        message["to"] = to
        message["subject"] = forward_subject
        message["from"] = sender_email

        if cc:
            message["cc"] = cc
        if bcc:
            message["bcc"] = bcc

        # Encode the message
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Create the email message body
        email_body = {"raw": encoded_message}

        # Send the forwarded email
        send_message = (
            service.users().messages().send(userId="me", body=email_body).execute()
        )

        result = f"Email forwarded successfully. Message ID: {send_message['id']}"
        if is_thread:
            result += f"\nForwarded {len(messages_to_forward)} messages from thread"
        else:
            result += "\nForwarded 1 message"

        return result

    except Exception as e:
        return f"Error forwarding email: {str(e)}"
