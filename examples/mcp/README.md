# MCP Server Configuration Examples

This directory contains example MCP server configurations for use with Silica.

## Usage

Copy the desired configuration to one of these locations:

1. **Global** (all personas): `~/.silica/mcp_servers.json`
2. **Per-persona**: `~/.silica/personas/{persona}/mcp_servers.json`
3. **Per-project**: `.silica/mcp_servers.json` in your project root

## Examples

### sqlite_server.json

Connect to a SQLite database. Useful for:
- Data analysis and reporting
- Local database operations
- Testing database queries

Requirements:
- Install: `uvx mcp-server-sqlite --help` to verify it's available

### filesystem_server.json

Secure filesystem access within specified directories. Useful for:
- File management tasks
- Reading/writing project files
- Log file analysis

Requirements:
- Install: `npm install -g @modelcontextprotocol/server-filesystem`
- Or use npx (included in example)

### github_server.json

GitHub API access. Useful for:
- Repository management
- Issue and PR operations
- Code search

Requirements:
- Set `GITHUB_TOKEN` environment variable with a Personal Access Token
- Required scopes depend on operations (repo, read:org, etc.)

### combined_example.json

Shows how to configure multiple servers together with different settings.

## Environment Variables

All examples use `${VAR}` syntax for environment variables. Make sure to:

1. Set required variables before starting Silica
2. Or use `${VAR:-default}` syntax for optional variables with defaults

## Testing Your Configuration

After adding a configuration:

1. Start Silica
2. Run `/mcp status` to see server status
3. Run `/mcp tools` to list available tools
4. Try invoking a tool to verify it works
