# Safe Testing Strategy for Workspace Environment Commands

## Overview

This document outlines a comprehensive testing strategy for the new workspace environment commands that ensures we can test functionality thoroughly without risking damage to our current development environment.

## Safety Principles

### 🛡️ **Isolation First**
- All tests run in temporary directories
- No tests should ever touch the current working directory
- Mock all external dependencies (piku, git, file system operations)
- Use environment variables to signal test mode

### 🧪 **Comprehensive Coverage**
- Unit tests for individual functions
- Integration tests for command workflows  
- JSON output validation
- Error handling scenarios
- Edge cases and boundary conditions

### 🔒 **Workspace Protection**
- Never run `silica create` in tests (could destroy current workspace)
- Mock all piku interactions
- Use temporary directories for all file operations
- Patch `os.getcwd()` and `Path.cwd()` in tests

## Testing Categories

### 1. Unit Tests (`test_workspace_environment.py`)

**Safe Functions to Test Directly:**
- `get_workspace_config()` - with mocked file system
- `get_agent_config_dict()` - with mocked agent configs
- JSON output structure validation
- Environment variable parsing
- Configuration file parsing

**Functions Requiring Mocking:**
- `load_environment_variables()` - mock piku ENV files
- `sync_dependencies()` - mock uv commands
- `install_agent()` - mock installation commands
- `check_environment_variables()` - mock environment state

### 2. Integration Tests

**Command Testing:**
```python
# Safe way to test commands
from click.testing import CliRunner
from unittest.mock import patch

@patch('silica.cli.commands.workspace_environment.load_environment_variables')
@patch('silica.cli.commands.workspace_environment.get_workspace_config')
def test_status_command(mock_config, mock_env):
    runner = CliRunner()
    result = runner.invoke(status, ['--json'])
    assert result.exit_code == 0
```

**JSON Output Validation:**
```python
def test_json_output_structure():
    # Mock all dependencies
    with comprehensive_mocks():
        result = runner.invoke(status, ['--json'])
        data = json.loads(result.output)
        
        # Validate structure
        assert 'overall_status' in data
        assert 'components' in data
        assert all expected components are present
```

### 3. End-to-End Testing (Manual)

**Safe Manual Testing in Disposable Environment:**
```bash
# Create a completely separate test repository
cd /tmp
mkdir silica-test-repo
cd silica-test-repo
git init

# Test the new commands
silica create -w test-workspace -a hdev
silica we status
silica we status --json
```

## Test Execution Strategy

### Automated Tests (Safe)
```bash
# Run unit tests
python -m pytest tests/test_workspace_environment.py -v

# Run with coverage
python -m pytest tests/ --cov=silica.cli.commands.workspace_environment

# Run specific test categories
python -m pytest tests/ -m "not slow"  # Quick tests only
python -m pytest tests/ -m "safe"      # All safe tests
```

### Manual Testing Checklist

**Before Manual Testing:**
- [ ] Commit all current work
- [ ] Create a backup of current workspace configuration
- [ ] Test in a completely separate directory/repository

**Test Scenarios:**
1. **Fresh Environment:**
   - [ ] `silica we status` in empty directory
   - [ ] `silica we status --json` produces valid JSON
   - [ ] Error handling for missing workspace config

2. **Mocked Workspace:**
   - [ ] Create fake `workspace_config.json`
   - [ ] Test `silica we status` with various configurations
   - [ ] Validate JSON output contains all expected fields

3. **Command Aliases:**
   - [ ] `silica workspace-environment status`
   - [ ] `silica workspace_environment status`  
   - [ ] `silica we status`
   - [ ] All should produce identical output

## Test Data Generation

### Mock Workspace Configurations
```python
# Valid configuration
valid_config = {
    "agent_type": "hdev",
    "agent_config": {
        "flags": ["--port", "8000"],
        "args": {"debug": True}
    }
}

# Error conditions
invalid_config = {"invalid": "config"}
missing_agent_type = {"agent_config": {}}
```

### Mock Agent Configurations
```python
mock_agent_config = {
    "name": "test-agent",
    "description": "Test agent for testing",
    "install": {
        "commands": ["echo 'install'"],
        "check_command": "echo 'check'"
    },
    "launch": {
        "command": "echo 'run'",
        "default_args": []
    },
    "environment": {
        "required": [],
        "recommended": []
    }
}
```

## Error Scenarios to Test

### 1. Missing Dependencies
- [ ] `uv` not installed
- [ ] Agent not installed
- [ ] Missing workspace configuration

### 2. Invalid Configurations
- [ ] Malformed JSON in `workspace_config.json`
- [ ] Invalid agent type
- [ ] Missing required environment variables

### 3. File System Issues
- [ ] Permission errors
- [ ] Missing directories
- [ ] Corrupt configuration files

## Continuous Integration

### GitHub Actions Safety
```yaml
# .github/workflows/test-workspace-environment.yml
name: Test Workspace Environment Commands

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest pytest-cov
      
      - name: Run safe tests only
        run: |
          # Only run tests marked as safe
          pytest tests/test_workspace_environment.py -m "safe" -v
      
      - name: Validate JSON output
        run: |
          # Test JSON output in isolation
          cd /tmp
          python -c "
          import tempfile, json
          from silica.cli.commands.workspace_environment import _status_impl
          # Test with mocked environment
          "
```

## Recovery Procedures

### If Tests Accidentally Affect Workspace

1. **Stop immediately**
2. **Check git status:** `git status`
3. **Restore from backup:** `git stash` or `git reset --hard`
4. **Review test isolation:** Ensure tests use temporary directories
5. **Update safety measures:** Add more mocking/isolation

### Workspace Backup Before Testing
```bash
# Create safety backup
git add -A
git commit -m "Backup before testing workspace environment commands"
git tag testing-backup-$(date +%Y%m%d-%H%M%S)
```

## Monitoring and Validation

### Health Checks During Testing
```bash
# Verify current workspace is untouched
git status                    # Should show no changes
ls -la .silica/              # Should match expectations
silica workspace list        # Should show expected workspaces
```

### JSON Output Validation
```python
import json
import jsonschema

# Define expected JSON schema
schema = {
    "type": "object",
    "required": ["overall_status", "timestamp", "issues", "components"],
    "properties": {
        "overall_status": {"enum": ["ok", "warning", "error"]},
        "timestamp": {"type": "string"},
        "issues": {"type": "array"},
        "components": {"type": "object"}
    }
}

# Validate output
def validate_status_json(output):
    data = json.loads(output)
    jsonschema.validate(data, schema)
    return data
```

## Conclusion

This testing strategy ensures we can thoroughly validate the new workspace environment commands without risking our development environment. The key is comprehensive mocking, isolated test environments, and careful manual testing in disposable locations.

**Remember:** When in doubt, test in `/tmp` or a completely separate repository first!