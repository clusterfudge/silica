# MCP Integration

Silica can act as an MCP (Model Context Protocol) host, allowing you to connect to external MCP servers and expose their tools to the AI agent.

## Overview

MCP is an open standard created by Anthropic for connecting AI applications to external systems. It provides a standardized way to expose tools, resources, and prompts from external servers.

### Key Benefits

- **Ecosystem Access**: Use existing MCP servers from the ecosystem (filesystem, database, web APIs)
- **Standardized Integration**: No need to write custom user tools for common functionality
- **Dynamic Tool Discovery**: Tools are discovered at runtime from external processes
- **Interoperability**: Share server configurations with other MCP hosts (Claude Desktop, Cursor, etc.)

## Configuration

MCP servers are configured via JSON files. Silica supports three configuration levels, merged with the following precedence (highest first):

1. **Per-Project**: `.silica/mcp_servers.json` in your project root
2. **Per-Persona**: `~/.silica/personas/{persona}/mcp_servers.json`
3. **Global**: `~/.silica/mcp_servers.json`

### Basic Configuration Format

```json
{
  "servers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "/path/to/db.sqlite"],
      "enabled": true,
      "cache": true
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/dir"],
      "enabled": true
    }
  }
}
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `command` | string | required | The command to run (e.g., `uvx`, `npx`, `python`) |
| `args` | array | `[]` | Arguments to pass to the command |
| `env` | object | `{}` | Environment variables for the server process |
| `enabled` | boolean | `true` | Whether to auto-connect at startup |
| `cache` | boolean | `true` | Whether to cache tool schemas (disable for development) |

### Environment Variable Expansion

Configuration values support environment variable expansion using `${VAR}` syntax:

```json
{
  "servers": {
    "myserver": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "${HOME}/data/db.sqlite"],
      "env": {
        "API_KEY": "${MY_API_KEY}"
      }
    }
  }
}
```

You can also provide default values with `${VAR:-default}`:

```json
{
  "args": ["--port", "${MCP_PORT:-8080}"]
}
```

## Tool Naming

To avoid collisions between servers that expose tools with the same name, MCP tools are prefixed with the server name:

- Server `sqlite` with tool `query` becomes `mcp_sqlite_query`
- Server `filesystem` with tool `read_file` becomes `mcp_filesystem_read_file`

This ensures all tools have unique names in the agent's toolbox.

## Using MCP Tools

### From the Agent

MCP tools are automatically available to the agent once servers are connected. The agent can use them just like any other tool:

```
I'll query the database for you using the MCP sqlite server.

<tool_use name="mcp_sqlite_query">
<input>{"sql": "SELECT * FROM users LIMIT 10"}</input>
</tool_use>
```

### Managing Servers

The agent can manage MCP servers dynamically using the built-in MCP tools:

- `mcp_list_servers` - List all configured servers with status
- `mcp_connect` - Connect to a server
- `mcp_disconnect` - Disconnect from a server
- `mcp_set_cache` - Toggle schema caching
- `mcp_refresh` - Force refresh tool schemas
- `mcp_list_tools` - List available tools

## CLI Commands

For interactive use, Silica provides `/mcp` CLI commands:

### `/mcp` or `/mcp status`
Show all servers with connection status, tool count, and cache settings:

```
MCP Servers:
  sqlite      ✓ connected   12 tools   cache: on
  filesystem  ✓ connected    5 tools   cache: on
  my-dev      ✗ disconnected           cache: off
```

### `/mcp connect [server]`
Connect to a specific server or all enabled servers:

```
/mcp connect sqlite
/mcp connect          # Connect all enabled servers
```

### `/mcp disconnect [server]`
Disconnect from a specific server or all servers:

```
/mcp disconnect sqlite
/mcp disconnect       # Disconnect all
```

### `/mcp reconnect [server]`
Reconnect to a server (useful after server restart):

```
/mcp reconnect sqlite
```

### `/mcp refresh [server]`
Force refresh tool schemas (useful after server changes):

```
/mcp refresh sqlite
/mcp refresh          # Refresh all
```

### `/mcp cache <server> <on|off>`
Toggle schema caching for a server:

```
/mcp cache my-dev off   # Disable caching for development
/mcp cache sqlite on
```

### `/mcp tools [server]`
List tools available from servers:

```
/mcp tools sqlite

sqlite (5 tools):
  mcp_sqlite_query: Execute a SQL query
  mcp_sqlite_insert: Insert data into a table
  ...
```

### `/mcp auth <server>`
Authenticate with an MCP server that requires credentials:

```
/mcp auth gmail
Starting oauth authentication for 'gmail'...
Opening browser for authorization...
Enter the authorization code: <paste code>
✓ Successfully authenticated 'gmail'
```

### `/mcp auth revoke <server>`
Revoke stored credentials for a server:

```
/mcp auth revoke gmail
✓ Credentials revoked for 'gmail'
Re-authentication will be required to use this server.
```

### `/mcp auth` (no server)
Show authentication status for all servers with auth configuration:

```
/mcp auth

MCP Authentication Status:
  gmail: oauth - ✓ authenticated
           expires in 4.2 hours
  openai: api_key - ✗ not configured
```

## Development Mode

When developing an MCP server, disable caching to see changes immediately:

```json
{
  "servers": {
    "my-dev-server": {
      "command": "python",
      "args": ["my_server.py"],
      "cache": false
    }
  }
}
```

With `cache: false`, Silica fetches fresh tool schemas before each API call. You can also toggle caching at runtime:

```
/mcp cache my-dev-server off
```

Or use the agent tool:
```
mcp_set_cache(server="my-dev-server", enabled=False)
```

## Popular MCP Servers

### SQLite Database

```json
{
  "servers": {
    "sqlite": {
      "command": "uvx",
      "args": ["mcp-server-sqlite", "--db-path", "${HOME}/data/mydb.sqlite"]
    }
  }
}
```

Install: `uvx mcp-server-sqlite --help`

### Filesystem Access

```json
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed/directory"]
    }
  }
}
```

Note: The server restricts access to the specified directory and its subdirectories.

### GitHub

```json
{
  "servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
      }
    }
  }
}
```

### Brave Search

```json
{
  "servers": {
    "brave-search": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-brave-search"],
      "env": {
        "BRAVE_API_KEY": "${BRAVE_API_KEY}"
      }
    }
  }
}
```

## Troubleshooting

### Server Won't Connect

1. **Check the command exists**: Run the command manually in your terminal
2. **Check arguments**: Some servers require specific arguments
3. **Check environment variables**: Ensure required env vars are set
4. **Check logs**: MCP connection errors are logged at startup

### Tools Not Appearing

1. **Check server status**: `/mcp status`
2. **Refresh schemas**: `/mcp refresh <server>`
3. **Check tool prefixes**: Tools are prefixed with `mcp_<server>_`

### Changes Not Reflected

If you've modified your MCP server:

1. Disable caching: `/mcp cache <server> off`
2. Or reconnect: `/mcp reconnect <server>`
3. Or refresh schemas: `/mcp refresh <server>`

### Performance Issues

- **Startup**: Many servers can slow startup. Disable unused servers with `"enabled": false`
- **Schema fetching**: Enable caching (`"cache": true`) for production use
- **Tool invocation**: Some servers have slow tools. Consider timeouts.

## Subagent MCP Integration

Subagents can have their own isolated MCP server connections, separate from the parent agent. This enables task-specific tool access without exposing all MCP tools to every subagent.

### Use Cases

- **Database Queries**: Give a subagent access to a specific database for data analysis
- **File Operations**: Limit a subagent to a specific directory via filesystem server
- **API Access**: Provide a subagent with GitHub or other API access for specific tasks
- **Isolation**: Keep sensitive MCP tools (e.g., write access) isolated to specific subagents

### Parameter Format

The `agent()` tool accepts an `mcp_servers` parameter in two formats:

#### 1. Named Server References

Reference servers from your MCP configuration by name (comma-separated):

```python
agent(
    prompt="Query the database for sales data from last month",
    mcp_servers="sqlite"
)

# Multiple servers
agent(
    prompt="Check the repo and query related data",
    mcp_servers="github,sqlite"
)
```

Named servers are loaded from the same 3-tier configuration (project, persona, global).

#### 2. Inline JSON Configuration

Define servers inline for one-off or dynamic configurations:

```python
agent(
    prompt="Analyze the data in this database",
    mcp_servers='{"analytics": {"command": "uvx", "args": ["mcp-server-sqlite", "--db-path", "/data/analytics.db"]}}'
)
```

### Isolation Guarantees

Subagent MCP connections are **fully isolated** from the parent:

1. **Own Manager**: Each subagent gets its own `MCPToolManager` instance
2. **No Inheritance**: Parent's MCP tools are NOT visible to the subagent
3. **No Sharing**: Connections are not shared between parent and subagent
4. **Clean Cleanup**: All MCP connections are closed when the subagent completes

This means:
- A subagent with `mcp_servers="sqlite"` can ONLY use sqlite tools
- The parent's connected MCP servers remain unaffected
- Multiple subagents can connect to the same server independently

### Examples

#### Database Analysis Subagent

```python
# Parent agent delegates database work to a specialized subagent
result = await agent(
    prompt="""
    Analyze the sales data and provide insights:
    1. Total sales by region
    2. Top 10 products
    3. Month-over-month growth
    """,
    tool_names="mcp_sqlite_query,mcp_sqlite_read_table",
    mcp_servers="analytics_db"
)
```

#### File Processing with Limited Access

```python
# Subagent can only access the /tmp/workspace directory
await agent(
    prompt="Process all CSV files and generate a summary report",
    mcp_servers='{"workspace": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/workspace"]}}'
)
```

#### Parallel Subagents with Different Servers

```python
# Multiple subagents can run concurrently with different MCP access
await asyncio.gather(
    agent(prompt="Get GitHub issues", mcp_servers="github"),
    agent(prompt="Query user data", mcp_servers="users_db"),
    agent(prompt="Search for solutions", mcp_servers="brave_search")
)
```

### Error Handling

If MCP server connection fails for a subagent:

1. **Graceful Degradation**: The subagent continues without MCP tools
2. **Logged Warning**: Connection failure is logged but doesn't crash the subagent
3. **No Parent Impact**: Parent's MCP connections remain unaffected

Example with error handling:

```python
# Even if the server fails, the subagent can still use other tools
result = await agent(
    prompt="Try to query the database, but use web search as fallback",
    tool_names="web_search",  # Fallback tool always available
    mcp_servers="maybe_offline_db"
)
```

### Best Practices

1. **Minimal Access**: Only provide servers the subagent actually needs
2. **Named References**: Use named servers from config for consistency
3. **Inline for Dynamic**: Use inline JSON for dynamic paths or one-off tasks
4. **Combine with tool_names**: Use `tool_names` to further limit available tools
5. **Error Handling**: Design subagent prompts to handle missing MCP tools gracefully

## Architecture

```
┌─────────────────────────────────────────┐
│           Silica (MCP HOST)             │
│  ┌──────────┐  ┌──────────┐  ┌────────┐ │
│  │  Client  │  │  Client  │  │ Client │ │
│  └────┬─────┘  └────┬─────┘  └───┬────┘ │
└───────┼─────────────┼────────────┼──────┘
        │ STDIO       │ STDIO      │ STDIO
        ▼             ▼            ▼
   ┌─────────┐   ┌─────────┐  ┌─────────┐
   │ Server  │   │ Server  │  │ Server  │
   │(sqlite) │   │(github) │  │(custom) │
   └─────────┘   └─────────┘  └─────────┘
```

Silica manages MCP servers as subprocesses, communicating via STDIO (stdin/stdout). Each server:

1. Is started when Silica connects
2. Receives tool invocations via JSON-RPC over STDIO
3. Returns results via STDIO
4. Is terminated when Silica disconnects

## Authentication

MCP servers can require authentication, which Silica handles through stored credentials.

### Configuration

Add an `auth` section to your server configuration:

```json
{
  "servers": {
    "gmail": {
      "command": "uvx",
      "args": ["mcp-server-gmail"],
      "auth": {
        "type": "oauth",
        "client_id": "${GOOGLE_CLIENT_ID}",
        "scopes": ["gmail.send", "gmail.readonly"]
      }
    },
    "openai": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-openai"],
      "auth": {
        "type": "api_key"
      }
    }
  }
}
```

### Auth Types

| Type | Description |
|------|-------------|
| `oauth` | OAuth 2.0 flow with browser authorization |
| `api_key` | Simple API key credential |

### OAuth Configuration Options

| Option | Description |
|--------|-------------|
| `client_id` | OAuth client ID |
| `client_secret` | OAuth client secret (optional for public clients) |
| `scopes` | List of OAuth scopes to request |
| `auth_url` | Authorization URL (in `extra` dict) |
| `token_url` | Token URL (in `extra` dict) |
| `redirect_uri` | Redirect URI (in `extra` dict, default: `http://localhost:8085/callback`) |

### Managing Credentials

**Authenticate**: Use `/mcp auth <server>` to initiate authentication

**Check Status**: Use `/mcp auth` or `/mcp status` to see auth status

**Revoke**: Use `/mcp auth revoke <server>` to clear stored credentials

### Credential Storage

Credentials are stored securely:

1. **Keyring** (preferred): Uses the system keychain (macOS Keychain, Linux Secret Service)
2. **File fallback**: Encrypted file at `~/.silica/mcp_credentials.json`

OAuth tokens are automatically refreshed when they expire.

### Agent Auth Tools

The agent can also manage authentication:

- `mcp_auth(server)` - Initiate authentication
- `mcp_auth_revoke(server)` - Revoke credentials  
- `mcp_auth_status(server)` - Check auth status

## Future Enhancements

- HTTP transport support for remote MCP servers
- MCP resource integration for context
- Server discovery and auto-configuration
