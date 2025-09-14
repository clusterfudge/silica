# GitHub CLI Cloning in Remote Workspaces

## Overview

Silica remote workspaces now automatically use GitHub CLI (`gh`) for cloning GitHub repositories with HTTPS scheme when creating remote workspaces. This provides improved authentication handling and ensures consistent HTTPS-based repository access.

## How It Works

### Automatic GitHub CLI Detection and Authentication

When initializing a remote workspace with a GitHub repository, Silica:

1. **Detects GitHub repositories** by examining the repository URL
2. **Sets up GitHub authentication** using tokens from environment variables
3. **Checks for GitHub CLI availability** on the remote system
4. **Uses `gh repo clone`** if available, which automatically uses HTTPS
5. **Falls back to regular `git clone`** if GitHub CLI is not available
6. **Configures git credentials** for ongoing HTTPS authentication

### Implementation Details

The implementation uses a layered approach with comprehensive authentication:

```python
# In silica/remote/utils/github_auth.py
def setup_github_authentication(directory=None, prefer_gh_cli=True):
    """Set up GitHub authentication using the best available method."""
    github_token = get_github_token()  # From GH_TOKEN or GITHUB_TOKEN
    
    # Try GitHub CLI first if available
    if prefer_gh_cli and check_gh_cli_available():
        success = setup_github_cli_auth()  # gh auth login --with-token
        if success:
            return True, "GitHub CLI authentication configured"
    
    # Fall back to direct git credential configuration
    return setup_git_credentials_for_github(directory)

# In silica/remote/utils/git.py  
def clone_repository(repo_url, destination_path, branch="main", use_https=True):
    """Clone a repository using the most appropriate method."""
    
    # For GitHub repositories, try GitHub CLI first
    if is_github_repo(repo_url) and check_gh_cli_available():
        # Use gh CLI which automatically handles HTTPS and authentication
        result = subprocess.run([
            "gh", "repo", "clone", repo_path, destination_path, 
            "--", "--branch", branch
        ])
        
        if result.returncode == 0:
            return True
    
    # Fall back to regular git clone
    git.Repo.clone_from(repo_url, destination_path, branch=branch)

# In silica/remote/antennae/agent_manager.py
def clone_repository(self, repo_url, branch="main"):
    """Clone with authentication setup."""
    if is_github_repo(repo_url):
        # Set up authentication before cloning
        setup_github_authentication()
        
    # Clone using utility function
    success = clone_repo_util(repo_url, code_dir, branch=branch)
    
    if success and is_github_repo(repo_url):
        # Configure git credentials in the cloned repository
        setup_github_authentication(directory=code_dir, prefer_gh_cli=False)
```

### Repository URL Support

The system recognizes GitHub repositories from various URL formats:

- **HTTPS**: `https://github.com/user/repo.git`
- **SSH**: `git@github.com:user/repo.git`
- **Without .git suffix**: Both formats work with or without `.git`

Non-GitHub repositories (GitLab, Bitbucket, self-hosted) use regular git clone directly.

## Benefits

### 1. Comprehensive Authentication
- **GitHub CLI Integration**: Uses existing GitHub CLI authentication when available
- **Token-based Authentication**: Automatically configures git to use GitHub tokens
- **Environment Variable Support**: Works with both `GH_TOKEN` and `GITHUB_TOKEN`
- **Private Repository Access**: Enables cloning and working with private repositories

### 2. HTTPS by Default
- **GitHub CLI HTTPS**: GitHub CLI automatically uses HTTPS scheme
- **Git Credential Configuration**: Sets up HTTPS authentication for regular git operations
- **Consistent Behavior**: Same authentication method across different environments
- **Network Compatibility**: Works with network restrictions that block SSH

### 3. Layered Fallback System
- **Primary**: GitHub CLI with automatic HTTPS and authentication
- **Secondary**: Direct git credentials configuration using tokens
- **Tertiary**: Regular git clone for non-GitHub repositories
- **Graceful Degradation**: Works even when GitHub CLI is not available

### 4. Complete Workflow Support
- **Initial Clone**: Uses best available method for repository cloning
- **Ongoing Operations**: Configures git for push, pull, and other operations
- **Authentication Persistence**: Credentials work for the lifetime of the workspace

## Usage Examples

### Creating a Remote Workspace

```bash
# The GitHub CLI will be used automatically for GitHub repositories
silica remote create --workspace my-agent

# For a specific repository during initialization
silica remote tell -w my-agent "setup with https://github.com/user/repo.git"
```

### Command Behavior

When creating a workspace with a GitHub repository:

```bash
# If gh CLI is available:
gh repo clone user/repo /workspace/code

# If gh CLI is not available (fallback):
git clone https://github.com/user/repo.git /workspace/code
```

### Branch Specification

For non-default branches:

```bash
# With gh CLI:
gh repo clone user/repo /workspace/code -- --branch feature-branch

# With git fallback:
git clone --branch feature-branch https://github.com/user/repo.git /workspace/code
```

## Integration Points

### 1. Remote Workspace Creation
- `silica remote create` uses the new cloning logic
- Automatic GitHub repository detection during initialization
- Seamless HTTPS cloning for GitHub repositories

### 2. Sync Command
- The existing `silica remote sync` command already uses similar logic
- Consistent behavior between creation and synchronization
- Both commands now use the same underlying utilities

### 3. Antennae Webapp
- HTTP initialization endpoints use the new cloning method
- `/initialize` endpoint automatically detects and clones GitHub repositories
- Better error handling and fallback mechanisms

## Configuration

### GitHub CLI Setup

To ensure GitHub CLI is available on remote systems:

```bash
# Install GitHub CLI (varies by system)
# Ubuntu/Debian:
sudo apt install gh

# CentOS/RHEL:
sudo dnf install gh

# Authenticate GitHub CLI
gh auth login
```

### Authentication Process

The system implements a comprehensive authentication workflow:

1. **Token Detection**: Checks for GitHub tokens in `GH_TOKEN` or `GITHUB_TOKEN` environment variables
2. **Method Selection**: Chooses between GitHub CLI and direct git configuration
3. **Global Setup**: Configures GitHub CLI authentication if available
4. **Repository-Specific Setup**: Configures git credentials within each cloned repository
5. **Verification**: Tests authentication against GitHub API or repository access

### Environment Variables

The system respects standard Git and GitHub environment variables:

- `GH_TOKEN` - GitHub personal access token (preferred)
- `GITHUB_TOKEN` - Alternative GitHub token variable (fallback)
- `GIT_*` - Standard Git configuration variables

### Git Configuration

For repositories, the system configures:

```bash
# Sets up credential helper for GitHub HTTPS
git config credential.https://github.com.helper ""
git config credential.https://github.com.username "token"  
git config credential.https://github.com.password "$GH_TOKEN"
```

This ensures that all git operations (clone, push, pull, fetch) can authenticate with GitHub using the token.

## Troubleshooting

### GitHub CLI Not Found

If GitHub CLI is not available, the system falls back to regular git:

```bash
# Check if gh CLI is available
gh --version

# Manual installation if needed
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt update
sudo apt install gh
```

### Authentication Issues

If GitHub CLI authentication fails:

```bash
# Re-authenticate with GitHub
gh auth login

# Check authentication status
gh auth status

# Use token-based authentication
gh auth login --with-token < token.txt
```

### Mixed Repository Types

For projects with multiple remotes or non-GitHub repositories:

```bash
# The system automatically detects repository type
# GitHub repos use gh CLI, others use git directly

# Check repository URL detection
python -c "
from silica.remote.utils.git import is_github_repo
print(is_github_repo('https://github.com/user/repo.git'))  # True
print(is_github_repo('https://gitlab.com/user/repo.git'))  # False
"
```

## Technical Implementation

### Key Functions

- `is_github_repo(url)` - Detects GitHub repositories
- `extract_github_repo_path(url)` - Extracts `user/repo` from GitHub URLs
- `check_gh_cli_available()` - Checks if GitHub CLI is installed
- `clone_repository(url, path, branch)` - Main cloning function with automatic method selection

### Integration Architecture

```
Remote Workspace Creation
├── detect repository URL
├── check if GitHub repository
│   ├── check GitHub CLI availability
│   ├── use gh repo clone (preferred)
│   └── fallback to git clone
└── setup development environment
```

### Error Handling

The implementation includes comprehensive error handling:

1. **GitHub CLI failures** fall back to regular git
2. **Repository path extraction errors** use original URL
3. **Authentication failures** are logged with helpful messages
4. **Network errors** are handled gracefully

## Future Enhancements

### Planned Features

1. **SSH fallback detection** - Automatically detect when HTTPS is not available
2. **Enhanced branch handling** - Better support for complex branching scenarios  
3. **Repository caching** - Local caching of frequently cloned repositories
4. **Authentication management** - Integrated GitHub token management

### Configuration Options

Future versions may include configuration options for:

- Forcing specific clone methods
- Custom GitHub Enterprise URLs
- Repository-specific authentication settings
- Clone behavior customization

## See Also

- [Remote Installation Guide](INSTALLATION.md)
- [Raspberry Pi Deployment](RASPBERRY_PI_DEPLOYMENT.md)
- [GitHub CLI Documentation](https://cli.github.com/manual/)
- [Git Configuration Guide](https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup)