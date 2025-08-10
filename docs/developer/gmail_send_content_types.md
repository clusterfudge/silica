# Gmail Send with Content Type Support

The `gmail_send` tool has been enhanced to support different content types: plain text, HTML, and Markdown. This allows for rich email formatting while maintaining backward compatibility.

## Function Signature

```python
gmail_send(
    context: AgentContext,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    reply_to: str = "",
    in_reply_to: str = "",
    content_type: str = "plain",
) -> str
```

## Parameters

- `to` (required): Email address(es) of the recipient(s), comma-separated for multiple
- `subject` (required): Subject line of the email
- `body` (required): Body content of the email
- `cc` (optional): Email address(es) to CC, comma-separated for multiple
- `bcc` (optional): Email address(es) to BCC, comma-separated for multiple
- `reply_to` (optional): Email address to set in the Reply-To header
- `in_reply_to` (optional): Message ID of the email being replied to
- `content_type` (optional): Content type - "plain", "html", or "markdown" (default: "plain")

## Supported Content Types

### Plain Text (`content_type="plain"`)

Default behavior. Sends the email as plain text with no formatting.

```python
gmail_send(
    context,
    to="recipient@example.com",
    subject="Plain Text Email",
    body="This is plain text.\n\nLine breaks are preserved but no formatting is applied.",
    content_type="plain"  # optional, this is the default
)
```

### HTML (`content_type="html"`)

Sends the email as HTML, allowing for rich formatting. The body should contain valid HTML.

```python
gmail_send(
    context,
    to="recipient@example.com",
    subject="HTML Email",
    body="""
    <h1>Project Update</h1>
    <p>We've made significant progress:</p>
    <ul>
        <li><strong>Feature A</strong>: Complete</li>
        <li><strong>Feature B</strong>: In testing</li>
        <li><em>Feature C</em>: In development</li>
    </ul>
    <p>Please visit <a href="https://project.example.com">our project site</a> for more details.</p>
    """,
    content_type="html"
)
```

### Markdown (`content_type="markdown"`)

Automatically converts Markdown syntax to HTML before sending. This provides an easy way to create formatted emails using familiar Markdown syntax.

```python
gmail_send(
    context,
    to="recipient@example.com",
    subject="Markdown Email",
    body="""
# Project Status Report

## Completed This Week
- [x] User authentication system
- [x] Database optimization
- [x] API documentation

## In Progress
- [ ] Frontend redesign
- [ ] Mobile app testing

## Key Metrics
- **Users**: 1,250 (+15% from last week)
- **Performance**: 95% uptime
- **Bug reports**: 3 (all resolved)

Please review the [detailed report](https://reports.example.com/weekly) and let me know if you have any questions.

---
*Generated automatically by the development team*
""",
    content_type="markdown"
)
```

## Markdown Features Supported

The Markdown conversion supports standard Markdown syntax including:

- **Headers**: `# H1`, `## H2`, `### H3`, etc.
- **Bold text**: `**bold**` or `__bold__`
- **Italic text**: `*italic*` or `_italic_`
- **Links**: `[text](URL)`
- **Lists**: 
  - Unordered: `- item` or `* item`
  - Ordered: `1. item`
  - Task lists: `- [x] completed` or `- [ ] incomplete`
- **Inline code**: `code`
- **Code blocks**: 
  ```
  ```language
  code here
  ```
  ```
- **Horizontal rules**: `---` or `***`
- **Blockquotes**: `> quoted text`
- **Tables**: Standard Markdown table syntax
- **Line breaks**: Two spaces at end of line or blank line

## Examples

### Simple Notification Email

```python
gmail_send(
    context,
    to="team@example.com",
    subject="Build Completed Successfully",
    body="""
# Build Status: ✅ SUCCESS

The latest build has completed successfully!

## Details
- **Commit**: abc123def
- **Duration**: 5 minutes 32 seconds  
- **Tests**: 127 passed, 0 failed

The updated application is now available at: https://staging.example.com
""",
    content_type="markdown"
)
```

### Weekly Report with Multiple Recipients

```python
gmail_send(
    context,
    to="stakeholders@example.com",
    cc="dev-team@example.com",
    bcc="archive@example.com",
    subject="Weekly Development Report",
    body="""
# Weekly Development Report
*Week of January 15-21, 2024*

## 🎯 Goals Achieved
- Completed user dashboard redesign
- Fixed critical security vulnerability
- Improved API response times by 40%

## 📊 Metrics
| Metric | This Week | Last Week | Change |
|--------|-----------|-----------|---------|
| Active Users | 2,847 | 2,634 | +8.1% |
| Page Load Time | 1.2s | 2.0s | -40% |
| Bug Reports | 3 | 8 | -62.5% |

## 🚧 Next Week Priorities
1. Launch mobile app beta
2. Implement advanced search functionality
3. Complete security audit

## ⚠️ Blockers
- Waiting for third-party API approval
- Need additional server resources for load testing

---
*Questions? Reply to this email or reach out on Slack.*
""",
    content_type="markdown"
)
```

### HTML Email for Rich Formatting

```python
gmail_send(
    context,
    to="customer@example.com",
    subject="Welcome to Our Service!",
    body="""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <header style="background-color: #4CAF50; color: white; padding: 20px; text-align: center;">
            <h1 style="margin: 0;">Welcome to Example Service!</h1>
        </header>
        
        <div style="padding: 20px; background-color: #f9f9f9;">
            <h2 style="color: #333;">Getting Started</h2>
            <p>Thank you for signing up! Here's what you can do next:</p>
            
            <div style="background-color: white; padding: 15px; margin: 10px 0; border-left: 4px solid #4CAF50;">
                <h3 style="color: #4CAF50; margin-top: 0;">Step 1: Complete Your Profile</h3>
                <p>Add your information to personalize your experience.</p>
                <a href="https://example.com/profile" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Complete Profile</a>
            </div>
            
            <div style="background-color: white; padding: 15px; margin: 10px 0; border-left: 4px solid #2196F3;">
                <h3 style="color: #2196F3; margin-top: 0;">Step 2: Explore Features</h3>
                <p>Discover all the tools available to you.</p>
                <a href="https://example.com/features" style="background-color: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">View Features</a>
            </div>
        </div>
        
        <footer style="background-color: #333; color: white; padding: 20px; text-align: center;">
            <p style="margin: 0;">Need help? Contact us at <a href="mailto:support@example.com" style="color: #4CAF50;">support@example.com</a></p>
        </footer>
    </div>
    """,
    content_type="html"
)
```

## Error Handling

The tool validates the content_type parameter and returns an error message for invalid values:

```python
# This will return an error
result = gmail_send(
    context,
    to="test@example.com",
    subject="Test",
    body="Test body",
    content_type="invalid"
)
# Returns: "Error: Invalid content_type 'invalid'. Must be one of: plain, html, markdown"
```

## Backward Compatibility

Existing code that uses `gmail_send` without the `content_type` parameter will continue to work unchanged, as the default behavior is plain text (`content_type="plain"`).

## Best Practices

1. **Choose the right content type**:
   - Use `plain` for simple notifications and plain text content
   - Use `markdown` for structured content that benefits from formatting
   - Use `html` when you need precise control over styling and layout

2. **Test your content**:
   - Markdown: Preview the converted HTML to ensure it looks as expected
   - HTML: Validate your HTML and test in multiple email clients
   - Plain text: Ensure line breaks and formatting work as intended

3. **Email client compatibility**:
   - HTML and Markdown (converted to HTML) may render differently across email clients
   - Plain text is universally supported but lacks formatting

4. **Content length**:
   - Keep emails concise and scannable
   - Use headers and lists to break up long content
   - Consider the mobile viewing experience

## Return Values

All content types return the same format on success:

```
Email sent successfully. Message ID: 1234567890abcdef
```

Or for replies:

```
Email sent successfully. Message ID: 1234567890abcdef
Added to thread ID: thread_9876543210
```