## 🚀 SILIC-2: Multiple Agent Support Implementation

This PR implements comprehensive support for multiple AI coding agents while maintaining the existing loose coupling architecture, plus adds global default agent configuration for improved user experience.

## 📋 Summary

### Core Features
- **Multiple Agent Support**: Added support for 5 different AI coding agents
- **Global Default Configuration**: Users can set a preferred default agent globally
- **Comprehensive CLI Interface**: Full command suite for agent management
- **Loose Coupling Maintained**: Preserves environment variables and tmux approach
- **Backward Compatibility**: All existing functionality works unchanged

## 🤖 Supported Agents

| Agent | Command | Description | Dependencies |
|-------|---------|-------------|--------------|
| **hdev** | `hdev` | Heare Developer - autonomous coding agent | heare-developer |
| **claude-code** | `claude-code` | Claude Code - Anthropic's coding assistant | claude-code |
| **openai-codex** | `openai-codex` | OpenAI Codex - AI coding assistant | openai-codex |
| **cline** | `cline` | Cline - AI coding assistant with VS Code integration | cline |
| **aider** | `aider` | AI pair programming in your terminal | aider-chat |

## 🔧 New Commands Added

### Agent Management
```bash
# List all supported agent types with details
silica agents list

# Show agent configuration across all workspaces
silica agents status

# Show detailed agent config for specific workspace
silica agents show [-w workspace]

# Change agent type for workspace
silica agents set <agent> [-w workspace]

# Configure agent with custom settings
silica agents configure <agent> [-w workspace]
```

### Global Default Agent
```bash
# Set global default agent for new workspaces
silica agents set-default <agent>
silica config set-default-agent <agent>  # alternative

# View current global default agent
silica agents get-default
silica config get default_agent  # alternative

# Setup wizard now includes default agent configuration
silica config setup
```

### Workspace Creation
```bash
# Create workspace using global default agent
silica create

# Create workspace with specific agent (overrides global default)
silica create -a <agent>

# Create named workspace with specific agent
silica create -w <name> -a <agent>
```

## 🏗️ Architecture & Implementation

### Agent Configuration System (`silica/utils/agents.py`)
- **AgentConfig dataclass**: Structured configuration for each agent type
- **SUPPORTED_AGENTS registry**: Centralized agent definitions
- **Dynamic command generation**: Configurable flags and arguments per agent
- **Script template system**: Parameterized AGENT.sh generation

### Workspace Configuration Schema
- **Added `agent_type`**: Specifies which agent to use
- **Added `agent_config`**: Custom flags and arguments per workspace
- **Automatic migration**: Existing workspaces default to hdev
- **Per-workspace customization**: Independent agent configuration

### Global Configuration Enhancement
- **Added `default_agent`**: Global default agent setting
- **Setup wizard integration**: Configure default during initial setup
- **Priority resolution**: Flag → Global default → System fallback
- **Multiple interfaces**: Both config and agents commands

### Template System
- **Parameterized AGENT.sh**: Template with `{agent_type}` and `{agent_command}` placeholders
- **Shell variable escaping**: Proper handling of bash variables with double braces
- **Dynamic generation**: Creates agent-specific startup scripts

## 🔄 Agent Priority Resolution

When creating workspaces, agent selection follows this priority order:

1. **`-a/--agent` flag** (highest priority - explicit user choice)
2. **Global `default_agent` config** (user's preferred default)  
3. **Fallback to `hdev`** (lowest priority - system default)

## 🔗 Loose Coupling Maintained

✅ **Environment Variables**: Preserved existing ENV var approach  
✅ **Tmux Integration**: Maintains tmux send-keys pattern  
✅ **Agent Execution**: Each agent runs via `uv run <agent-command>`  
✅ **Configuration Storage**: Agent settings in workspace config files  
✅ **No Tight Integration**: Easy to add new agents without core changes  

## 📁 Files Changed

### New Files
- `silica/utils/agents.py` - Agent configuration system
- `silica/cli/commands/agents.py` - Agent management commands
- `silica/utils/templates/AGENT.sh.template` - Parameterized agent script template
- `test_agent_functionality.py` - Comprehensive test script

### Modified Files
- `silica/config/__init__.py` - Added default_agent to global config
- `silica/config/multi_workspace.py` - Workspace config with agent settings
- `silica/cli/commands/create.py` - Agent selection during workspace creation
- `silica/cli/commands/config.py` - Global default agent configuration
- `silica/cli/main.py` - Register agents command group
- `README.md` - Updated documentation with agent management

## 🧪 Testing & Quality Assurance

### Automated Testing
✅ **All existing tests pass** (7/7)  
✅ **Pre-commit hooks pass** (autoflake, ruff, ruff-format)  
✅ **Comprehensive test script** (`test_agent_functionality.py`)  

### Manual Testing Verification
✅ **Agent listing and discovery**  
✅ **Agent status monitoring**  
✅ **Agent switching between types**  
✅ **Configuration management**  
✅ **Script generation**  
✅ **Workspace integration**  
✅ **Global default agent management**  

### Backward Compatibility
✅ **Existing workspaces automatically use hdev**  
✅ **Configuration migration handled transparently**  
✅ **All existing commands work unchanged**  
✅ **No breaking changes**  

## 📖 Usage Examples

### Basic Agent Management
```bash
# List available agents
silica agents list

# Set global default to aider
silica agents set-default aider

# Create workspace using global default
silica create -w my-project

# Override for specific workspace
silica create -w special-project -a claude-code

# Switch existing workspace to different agent
silica agents set cline -w my-project

# View agent status across all workspaces
silica agents status
```

### Advanced Configuration
```bash
# Configure agent with custom settings
silica agents configure aider -w my-project

# View detailed agent configuration
silica agents show -w my-project

# Setup silica with preferred default agent
silica config setup
```

## 🎯 Benefits Delivered

### For Users
- **Simplified Workflow**: Set preferred agent once, use everywhere
- **Flexible Override**: Easy to use different agents per project
- **Rich CLI Interface**: Comprehensive agent management commands
- **Seamless Migration**: Existing setups continue to work

### For Maintainers  
- **Extensible Architecture**: Easy to add new agents
- **Clean Separation**: Agent logic isolated in dedicated module
- **Consistent Patterns**: Unified configuration and command structure
- **Comprehensive Testing**: Full test coverage for new functionality

## 🔄 Migration Path

### For Existing Users
1. **No action required**: Existing workspaces continue using hdev
2. **Optional**: Run `silica config setup` to configure global default
3. **Optional**: Use `silica agents set <agent>` to switch workspaces

### For New Users
1. **Run setup**: `silica config setup` includes agent selection
2. **Create workspaces**: `silica create` uses your preferred default
3. **Customize as needed**: Override defaults for specific projects

## 🚀 Ready for Review

This implementation provides a comprehensive multi-agent system that:
- ✅ Meets all SILIC-2 requirements
- ✅ Adds requested global default functionality  
- ✅ Maintains backward compatibility
- ✅ Preserves loose coupling architecture
- ✅ Includes comprehensive testing
- ✅ Provides excellent user experience

The feature is ready for production use and can be extended easily to support additional agents in the future.