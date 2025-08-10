# Google Tools Examples

This guide provides examples of how to use the Google service tools in both regular and headless environments.

## Authentication Setup

Before using any Google services, you need to authenticate:

### Interactive Environment

In an interactive environment with a browser:

```bash
# For Gmail
hdev gauth generate gmail

# For Calendar
hdev gauth generate calendar
```

This will open a browser window for authentication.

### Headless Environment

For servers or environments without a browser:

```bash
# Set environment variable to force device flow
export HEARE_GOOGLE_AUTH_METHOD=device

# Then generate token
hdev gauth generate gmail
```

This will provide a URL to visit on another device and ask for a verification code.

### Transferring Tokens

Export tokens from your development machine and import them on your server:

```bash
# On your local machine
hdev gauth export gmail --output ~/gmail_token.txt

# Copy the file to the server
scp ~/gmail_token.txt user@server:~/

# On the server
hdev gauth import gmail --input ~/gmail_token.txt
```

Or do it in a single command:

```bash
# Transfer in one command
hdev gauth export gmail | ssh user@server "hdev gauth import gmail"
```

## Using Gmail Tools

Once authenticated, you can use Gmail tools:

```python
# Search for emails
messages = gmail_search(query="from:example@gmail.com", max_results=5)

# Read a specific email
email_content = gmail_read(email_id="message_id_here")

# Send an email
gmail_send(
    to="recipient@example.com",
    subject="Hello from Heare",
    body="This is a test email."
)
```

## Using Calendar Tools

For Google Calendar:

```python
# List events for next week
events = calendar_list_events(days=7)

# Create a new event
calendar_create_event(
    summary="Team Meeting",
    start_time="2023-06-01T14:00:00",
    end_time="2023-06-01T15:00:00",
    description="Weekly team sync"
)

# Search for specific events
search_results = calendar_search(query="meeting", days=30)
```