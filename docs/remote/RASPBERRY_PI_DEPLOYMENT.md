# Raspberry Pi Deployment Guide

This guide covers deploying Silica agent workspaces to Raspberry Pi systems running piku.

## Overview

Silica agent workspaces are deployed to remote Raspberry Pi systems via piku. The deployment process automatically handles Python version requirements, including installing Python 3.11 when needed.

## System Requirements

### Remote Raspberry Pi (piku server)
- **Operating System**: Raspberry Pi OS (Debian-based)
- **Python**: 3.11+ (automatically installed if needed)
- **Piku**: Configured and running
- **Network**: SSH access configured

### Local Development Machine
- **Python**: 3.11+ 
- **Silica**: Installed (`pip install pysilica`)
- **Git**: Configured with SSH keys
- **Piku**: Git remote configured

## Deployment Process

### 1. Create Agent Workspace

```bash
# Create workspace (automatically deploys to remote)
silica create -w my-agent

# Create with custom workspace name
silica create -w my-agent
```

This command:
- Creates agent workspace configuration
- Deploys to remote Raspberry Pi via piku
- Includes Python 3.11 setup scripts
- Configures environment automatically

### 2. Automatic Python Setup

The deployment includes these files that handle Python setup on the remote:

- **`setup_python.sh`**: Automatically installs Python 3.11 if needed
- **`verify_setup.py`**: Verifies the installation
- **`.python-version`**: Specifies Python 3.11 requirement
- **`pyproject.toml`**: Defines dependencies with Python 3.11+ requirement

### 3. Remote Setup Process

On the remote Raspberry Pi, the setup process:

1. **Detects System Type**: Identifies Raspberry Pi hardware
2. **Checks Python Version**: Verifies Python 3.11+ availability
3. **Installs Dependencies**: System packages for Python compilation
4. **Installs pyenv**: If Python 3.11 not available
5. **Compiles Python 3.11**: Using pyenv (takes 20-30 minutes)
6. **Creates Virtual Environment**: Isolated Python environment
7. **Installs Silica**: Latest version with dependencies
8. **Verifies Setup**: Ensures everything is working

## Manual Verification

Connect to your remote workspace to verify setup:

```bash
# Connect to remote workspace
silica agent -w my-agent

# Or use piku directly
piku shell my-agent-<repo-name>
```

Once connected, verify the setup:

```bash
# Check Python version
python --version  # Should show Python 3.11.x

# Verify virtual environment
which python  # Should show .venv/bin/python

# Test Silica installation
python -c "import silica; print('Silica installed successfully')"

# Run verification script
python verify_setup.py
```

## Troubleshooting

### Python Version Issues

If you encounter Python version problems:

```bash
# Connect to remote
piku shell my-agent-<repo-name>

# Run setup script manually
./setup_python.sh

# Verify installation
python verify_setup.py
```

### Build Dependencies Missing

If Python compilation fails:

```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install -y build-essential libssl-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
    libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
    libffi-dev liblzma-dev git

# Retry setup
./setup_python.sh
```

### Long Build Times

Python compilation on Raspberry Pi can take 20-30 minutes. This is normal. To monitor progress:

```bash
# Check if pyenv is installing
ps aux | grep python

# Monitor pyenv logs
tail -f ~/.pyenv/logs/python-build.log
```

### Virtual Environment Issues

If virtual environment problems occur:

```bash
# Remove and recreate
rm -rf .venv
uv venv --python python3.11 .venv
source .venv/bin/activate
uv pip install pysilica
```

## Configuration Files

### setup_python.sh
Main setup script that:
- Detects Raspberry Pi systems
- Installs Python 3.11 via pyenv if needed
- Sets up virtual environment
- Installs dependencies

### verify_setup.py
Verification script that checks:
- Python version compatibility
- Virtual environment status
- Silica module availability
- Environment variables
- Workspace configuration

### pyproject.toml
Project configuration with:
- Python 3.11+ requirement
- Silica dependency
- Build system configuration

## Environment Variables

The following environment variables are automatically configured:

- `SILICA_WORKSPACE_NAME`: Workspace identifier
- `SILICA_AGENT_TYPE`: Agent type (hdev, aider, etc.)
- `NGINX_SERVER_NAME`: Hostname routing
- API keys from global configuration

## Performance Considerations

### Raspberry Pi 4 vs Earlier Models

- **Raspberry Pi 4**: Python compilation ~20-30 minutes
- **Raspberry Pi 3**: Python compilation ~45-60 minutes
- **Raspberry Pi Zero**: Not recommended for compilation

### Optimization Tips

1. **Use Raspberry Pi 4**: Faster compilation and better performance
2. **Increase swap**: For compilation process
3. **Use fast SD card**: Class 10 or better
4. **Enable SSH multiplexing**: Faster deployments

### Swap Configuration

For Python compilation, increase swap:

```bash
# Increase swap size
sudo dphys-swapfile swapoff
sudo sed -i 's/CONF_SWAPSIZE=100/CONF_SWAPSIZE=2048/' /etc/dphys-swapfile
sudo dphys-swapfile setup
sudo dphys-swapfile swapon
```

## Security Considerations

### SSH Configuration

Ensure secure SSH setup:

```bash
# Use SSH keys (not passwords)
ssh-keygen -t ed25519 -C "your_email@example.com"

# Configure SSH multiplexing
cat >> ~/.ssh/config << EOF
Host your-pi
    HostName your-pi-ip
    User pi
    ControlMaster auto
    ControlPath ~/.ssh/control-%r@%h:%p
    ControlPersist 10m
EOF
```

### Firewall Configuration

Configure UFW if enabled:

```bash
# Allow SSH
sudo ufw allow ssh

# Allow piku ports
sudo ufw allow 80
sudo ufw allow 443

# Enable firewall
sudo ufw enable
```

## Next Steps

After successful deployment:

1. **Configure API Keys**: Add required API keys via piku
2. **Test Agent**: Verify agent functionality
3. **Monitor Logs**: Check application logs
4. **Set Up Monitoring**: Monitor system resources

For usage examples, see the main [README.md](../../README.md).