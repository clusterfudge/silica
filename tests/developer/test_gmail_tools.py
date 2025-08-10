import unittest
from unittest.mock import Mock, patch
from silica.developer.context import AgentContext
from silica.developer.tools.gmail import gmail_forward, gmail_send


class TestGmailTools(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.context = Mock(spec=AgentContext)

    @patch("silica.developer.tools.gmail.get_credentials")
    @patch("silica.developer.tools.gmail.build")
    def test_gmail_forward_single_message(self, mock_build, mock_get_credentials):
        """Test forwarding a single message."""
        # Mock the Gmail service
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock credentials
        mock_get_credentials.return_value = Mock()

        # Mock profile response
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com"
        }

        # Mock message response
        mock_message = {
            "id": "msg123",
            "threadId": "thread123",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                    {"name": "To", "value": "recipient@example.com"},
                ],
                "body": {
                    "data": "VGVzdCBtZXNzYWdlIGJvZHk="  # Base64 encoded "Test message body"
                },
            },
            "internalDate": "1704110400000",
        }

        # Configure mock to return message when accessed as single message
        mock_service.users().messages().get().execute.return_value = mock_message

        # Mock send response
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_msg_id"
        }

        # Test forwarding a single message
        result = gmail_forward(
            self.context,
            message_or_thread_id="msg123",
            to="forward@example.com",
            additional_message="Please see forwarded message below.",
        )

        # Verify the result
        self.assertIn("Email forwarded successfully", result)
        self.assertIn("sent_msg_id", result)
        self.assertIn("Forwarded 1 message", result)

        # Verify that the Gmail API was called correctly
        # The function tries to get message first, so it should be called
        assert mock_service.users().messages().get.called
        # Send is called once (but the mock framework counts both send() and send().execute())
        assert mock_service.users().messages().send.called

    @patch("silica.developer.tools.gmail.get_credentials")
    @patch("silica.developer.tools.gmail.build")
    def test_gmail_forward_thread(self, mock_build, mock_get_credentials):
        """Test forwarding a thread of messages."""
        # Mock the Gmail service
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock credentials
        mock_get_credentials.return_value = Mock()

        # Mock profile response
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com"
        }

        # Mock single message get to fail (to trigger thread lookup)
        mock_service.users().messages().get().execute.side_effect = Exception(
            "Not a message"
        )

        # Mock thread response with multiple messages
        mock_thread = {
            "id": "thread123",
            "messages": [
                {
                    "id": "msg1",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Test Subject"},
                            {"name": "From", "value": "sender1@example.com"},
                            {"name": "Date", "value": "Mon, 1 Jan 2024 12:00:00 +0000"},
                            {"name": "To", "value": "recipient@example.com"},
                        ],
                        "body": {
                            "data": "Rmlyc3QgbWVzc2FnZQ=="  # Base64 encoded "First message"
                        },
                    },
                    "internalDate": "1704110400000",
                },
                {
                    "id": "msg2",
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": "Re: Test Subject"},
                            {"name": "From", "value": "sender2@example.com"},
                            {"name": "Date", "value": "Mon, 1 Jan 2024 13:00:00 +0000"},
                            {"name": "To", "value": "recipient@example.com"},
                        ],
                        "body": {
                            "data": "U2Vjb25kIG1lc3NhZ2U="  # Base64 encoded "Second message"
                        },
                    },
                    "internalDate": "1704114000000",
                },
            ],
        }

        mock_service.users().threads().get().execute.return_value = mock_thread

        # Mock send response
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_thread_id"
        }

        # Test forwarding a thread
        result = gmail_forward(
            self.context, message_or_thread_id="thread123", to="forward@example.com"
        )

        # Verify the result
        self.assertIn("Email forwarded successfully", result)
        self.assertIn("sent_thread_id", result)
        self.assertIn("Forwarded 2 messages from thread", result)

        # Verify that the Gmail API was called correctly
        # The function tries to get message first (which fails), then gets thread
        assert mock_service.users().messages().get.called
        assert mock_service.users().threads().get.called
        # Send is called once (but the mock framework counts both send() and send().execute())
        assert mock_service.users().messages().send.called

    def test_gmail_forward_schema(self):
        """Test that the tool schema is correctly defined."""
        schema = gmail_forward.schema()

        # Check basic schema structure
        self.assertEqual(schema["name"], "gmail_forward")
        self.assertIn("description", schema)
        self.assertIn("input_schema", schema)

        # Check required parameters
        required_params = schema["input_schema"]["required"]
        self.assertIn("message_or_thread_id", required_params)
        self.assertIn("to", required_params)

        # Check optional parameters are defined but not required
        properties = schema["input_schema"]["properties"]
        self.assertIn("cc", properties)
        self.assertIn("bcc", properties)
        self.assertIn("additional_message", properties)
        self.assertNotIn("cc", required_params)
        self.assertNotIn("bcc", required_params)
        self.assertNotIn("additional_message", required_params)

    @patch("silica.developer.tools.gmail.get_credentials")
    @patch("silica.developer.tools.gmail.build")
    def test_gmail_send_plain_text(self, mock_build, mock_get_credentials):
        """Test sending a plain text email."""
        # Mock the Gmail service
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock credentials
        mock_get_credentials.return_value = Mock()

        # Mock profile response
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com"
        }

        # Mock send response
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_msg_id"
        }

        # Test sending plain text email
        result = gmail_send(
            self.context,
            to="recipient@example.com",
            subject="Test Subject",
            body="This is plain text content.",
            content_type="plain",
        )

        # Verify the result
        self.assertIn("Email sent successfully", result)
        self.assertIn("sent_msg_id", result)

        # Verify send was called
        assert mock_service.users().messages().send.called

    @patch("silica.developer.tools.gmail.get_credentials")
    @patch("silica.developer.tools.gmail.build")
    def test_gmail_send_html(self, mock_build, mock_get_credentials):
        """Test sending an HTML email."""
        # Mock the Gmail service
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock credentials
        mock_get_credentials.return_value = Mock()

        # Mock profile response
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com"
        }

        # Mock send response
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_msg_id"
        }

        # Test sending HTML email
        result = gmail_send(
            self.context,
            to="recipient@example.com",
            subject="Test Subject",
            body="<h1>This is HTML content</h1><p>With <em>formatting</em>.</p>",
            content_type="html",
        )

        # Verify the result
        self.assertIn("Email sent successfully", result)
        self.assertIn("sent_msg_id", result)

        # Verify send was called
        assert mock_service.users().messages().send.called

    @patch("silica.developer.tools.gmail.get_credentials")
    @patch("silica.developer.tools.gmail.build")
    @patch("markdown.markdown")
    def test_gmail_send_markdown(
        self, mock_markdown_func, mock_build, mock_get_credentials
    ):
        """Test sending a markdown email (converted to HTML)."""
        # Mock the Gmail service
        mock_service = Mock()
        mock_build.return_value = mock_service

        # Mock credentials
        mock_get_credentials.return_value = Mock()

        # Mock profile response
        mock_service.users().getProfile().execute.return_value = {
            "emailAddress": "test@example.com"
        }

        # Mock send response
        mock_service.users().messages().send().execute.return_value = {
            "id": "sent_msg_id"
        }

        # Mock markdown conversion
        mock_markdown_func.return_value = (
            "<h1>This is converted HTML</h1><p>With <em>formatting</em>.</p>"
        )

        # Test sending markdown email
        result = gmail_send(
            self.context,
            to="recipient@example.com",
            subject="Test Subject",
            body="# This is converted HTML\n\nWith *formatting*.",
            content_type="markdown",
        )

        # Verify the result
        self.assertIn("Email sent successfully", result)
        self.assertIn("sent_msg_id", result)

        # Verify markdown conversion was called
        mock_markdown_func.assert_called_once_with(
            "# This is converted HTML\n\nWith *formatting*."
        )

        # Verify send was called
        assert mock_service.users().messages().send.called

    def test_gmail_send_invalid_content_type(self):
        """Test that invalid content types return an error."""
        # The validation should happen before any Gmail API calls,
        # so we don't need to mock anything for this test
        result = gmail_send(
            self.context,
            to="recipient@example.com",
            subject="Test Subject",
            body="Test body",
            content_type="invalid",
        )

        # Verify error message
        self.assertIn("Error: Invalid content_type 'invalid'", result)
        self.assertIn("Must be one of: plain, html, markdown", result)

    def test_gmail_send_schema(self):
        """Test that the gmail_send tool schema includes content_type parameter."""
        schema = gmail_send.schema()

        # Check basic schema structure
        self.assertEqual(schema["name"], "gmail_send")
        self.assertIn("description", schema)
        self.assertIn("input_schema", schema)

        # Check required parameters
        required_params = schema["input_schema"]["required"]
        self.assertIn("to", required_params)
        self.assertIn("subject", required_params)
        self.assertIn("body", required_params)

        # Check that content_type is an optional parameter
        properties = schema["input_schema"]["properties"]
        self.assertIn("content_type", properties)
        self.assertNotIn("content_type", required_params)


if __name__ == "__main__":
    unittest.main()
