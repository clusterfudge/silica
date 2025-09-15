# GitHub Authentication in Remote Environments

This document describes how GitHub authentication works in Silica remote environments and the comprehensive fixes implemented to ensure seamless git operations.

## Problem Overview

Previously, remote Silica environments would prompt for GitHub credentials when attempting git operations, showing errors like:

```
Password for 'https://token@github.com'
```

This occurred because:
1. GitHub tokens were not properly propagated to remote environments
2. GitHub CLI authentication wasn't configured in remote workspaces  
3. Git credential helpers weren't set up for HTTPS authentication

## Solution Architecture

The fix implements a multi-layered GitHub authentication approach:

### 1. Token Propagation During Workspace Creation

**Remote Workspace Creation** (`silica/remote/cli/commands/create.py`):
- Automatically retrieves GitHub tokens from environment (`GH_TOKEN`, `GITHUB_TOKEN`)
- Falls back to GitHub CLI (`gh auth token`) if environment variables aren't set
- Propagates both `GH_TOKEN` and `GITHUB_TOKEN` to remote environment via piku config
- Displays clear status messages about GitHub authentication configuration

**Local Workspace Creation**:
- Enhanced tmux session creation to pass GitHub tokens via environment variables
- Ensures tokens are available for agent processes running in tmux

### 2. Remote Environment Setup

**Setup Script Enhancement** (`silica/remote/utils/templates/setup_python.sh`):
- Automatic GitHub CLI installation on Debian/Ubuntu systems
- GitHub authentication setup using available tokens
- Fallback to direct git credential configuration if GitHub CLI unavailable
- Integration with existing Python/dependency setup workflow

**Functions added**:
- `install_github_cli()` - Installs GitHub CLI via package manager
- `setup_github_auth()` - Configures authentication using available methods

### 3. Workspace Environment Integration

**Environment Setup** (`silica/remote/cli/commands/workspace_environment.py`):
- GitHub authentication setup integrated into workspace initialization
- Authentication verification to ensure setup worked correctly
- Clear error messages and fallback strategies

**Agent Manager Enhancement** (`silica/remote/antennae/agent_manager.py`):
- GitHub authentication setup before repository cloning
- Enhanced tmux session creation with proper environment variable propagation
- Git credential configuration in cloned repositories

### 4. Enhanced Authentication Utilities

**GitHub Auth Utils** (`silica/remote/utils/github_auth.py`):
- Enhanced `setup_github_authentication()` with CLI token retrieval fallback
- Improved error handling and fallback strategies
- Support for both GitHub CLI and direct git credential approaches
- Automatic SSH-to-HTTPS URL conversion for GitHub repositories

## Authentication Flow

### During Remote Workspace Creation

1. **Token Detection**:
   ```python
   # Check environment variables first
   github_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
   
   # Fall back to GitHub CLI if needed
   if not github_token:
       result = subprocess.run(["gh", "auth", "token"], ...)
       github_token = result.stdout.strip()
   ```

2. **Remote Environment Configuration**:
   ```bash
   # Via piku config:set
   piku config:set GH_TOKEN=<token> GITHUB_TOKEN=<token>
   ```

3. **Setup Script Execution**:
   ```bash
   # During remote environment setup
   install_github_cli
   setup_github_auth  # Uses tokens from environment
   ```

### During Repository Operations

1. **Pre-Clone Authentication Setup**:
   ```python
   if is_github_repo(repo_url):
       success, message = setup_github_authentication()
   ```

2. **Multi-Method Authentication**:
   - **Primary**: GitHub CLI authentication with git integration
   - **Fallback**: Direct git credential helper configuration
   - **Repository-specific**: Git config in cloned directories

3. **Git Configuration**:
   ```bash
   # GitHub CLI approach
   gh auth login --with-token
   gh auth setup-git
   
   # Direct approach
   git config credential.https://github.com.helper ""
   git config credential.https://github.com.username "token"
   git config credential.https://github.com.password "$GH_TOKEN"
   ```

## Testing

Comprehensive test suite added in `tests/remote/test_github_auth_remote_fix.py`:

- **Token Propagation Tests**: Verify tokens are passed to remote environments
- **Workspace Environment Tests**: Confirm authentication setup integration
- **Enhanced Auth Utils Tests**: Validate fallback and CLI token retrieval
- **Local Workspace Tests**: Check tmux environment variable passing
- **Agent Manager Tests**: Ensure repository operations include auth setup

## Usage Examples

### Creating Remote Workspace with GitHub Repository

```bash
# GitHub token automatically detected and propagated
silica remote create --workspace my-agent

# Repository initialization with authentication
silica remote tell -w my-agent "setup with https://github.com/user/repo.git"
```

### Manual Authentication Verification

In remote environment:
```bash
# Check GitHub CLI status
gh auth status

# Test repository access
git ls-remote https://github.com/user/repo.git

# Verify environment variables
echo $GH_TOKEN
```

### Troubleshooting

If authentication issues persist:

1. **Check Token Availability**:
   ```bash
   # Local environment
   gh auth token
   echo $GH_TOKEN
   
   # Remote environment (via piku)
   piku shell my-agent
   echo $GH_TOKEN
   ```

2. **Manual GitHub CLI Setup**:
   ```bash
   # In remote environment
   gh auth login --with-token < token.txt
   gh auth setup-git
   ```

3. **Direct Git Configuration**:
   ```bash
   git config credential.https://github.com.helper ""
   git config credential.https://github.com.username "token"
   git config credential.https://github.com.password "$GH_TOKEN"
   ```

## Backward Compatibility

- Existing workspaces continue to work without changes
- New authentication setup is additive and doesn't break existing configurations
- Fallback mechanisms ensure functionality even if preferred methods fail
- Both `GH_TOKEN` and `GITHUB_TOKEN` environment variables supported

## Security Considerations

- Tokens are transmitted securely via piku's configuration system
- Environment variables are properly scoped to workspace processes
- No tokens logged or exposed in plain text output
- GitHub CLI integration uses standard authentication flows

## Future Enhancements

Potential improvements identified:
1. Support for GitHub Enterprise Server URLs
2. Repository-specific authentication tokens
3. Automatic token refresh mechanisms
4. SSH key-based authentication options
5. Integration with other Git hosting providers

## Related Documentation

- [GitHub CLI Cloning](../remote/GITHUB_CLI_CLONING.md)
- [Remote Installation Guide](../remote/INSTALLATION.md)
- [Workspace Environment Setup](workspace_environment.md)