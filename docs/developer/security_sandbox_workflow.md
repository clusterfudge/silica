# Security Sandbox Workflow

The Heare Developer CLI provides a security sandbox for controlling access to system resources. When an action requires permission, the user is prompted to allow or deny the action.

## Permission Options

When a tool tries to access a system resource, the user has three options:

1. **Allow (Y)** - Grant permission for the requested action.
2. **Deny (N)** - Reject the permission request.
3. **Do Something Else (D)** - This special option allows the user to provide an alternative prompt.

## "Do Something Else" Workflow

When the user selects "Do Something Else" (by entering "D" at the permission prompt), the following happens:

1. The last assistant message that introduced the tool request is removed from the conversation history.
2. The user is prompted to enter an alternative request.
3. The alternative request is appended to the previous user message as an "Alternate request" section.
4. The conversation continues with this new context, allowing the assistant to respond to the alternative request instead.

## Use Cases

The "Do Something Else" option is particularly useful when:

- The assistant proposes a tool or approach that isn't appropriate for the task.
- You want to redirect the conversation without explicitly denying a permission.
- You have a better approach in mind for solving the problem.

## Example

```
AI: I'll help you optimize this code. Let me examine the file first.

[Using tool read_file with input {"path": "example.py"}]

Allow read_file on example.py with arguments {'path': 'example.py'}? (Y/N/D for 'do something else'): D

You selected 'do something else'. Please enter what you'd like to do instead:
Instead of reading the file, let me describe the code structure to you. It has three functions...

AI: Thank you for describing the code structure. Based on your description of the three functions...
```

In this example, instead of reading the file directly, the assistant now responds to the user's description of the code.