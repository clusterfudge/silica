# Silica Installation Guide

## System Requirements

- **Python**: 3.11 or higher (required)
- **Operating System**: Linux, macOS, or Windows (with WSL)
- **Package Manager**: `uv` (recommended) or `pip`

## Quick Installation

If you already have Python 3.11+ installed:

```bash
# Using uv (recommended)
uv pip install pysilica

# Using pip
pip install pysilica
```

## Raspberry Pi Installation

Raspberry Pi OS typically comes with Python 3.9.x, but Silica requires Python 3.11+. Follow these steps to install the correct Python version:

### Option 1: Using pyenv (Recommended)

1. **Install pyenv dependencies**:
   ```bash
   sudo apt update
   sudo apt install -y make build-essential libssl-dev zlib1g-dev \
   libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
   libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
   libffi-dev liblzma-dev git
   ```

2. **Install pyenv**:
   ```bash
   curl https://pyenv.run | bash
   ```

3. **Add pyenv to your shell profile**:
   ```bash
   echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
   echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
   echo 'eval "$(pyenv init --path)"' >> ~/.bashrc
   echo 'eval "$(pyenv init -)"' >> ~/.bashrc
   source ~/.bashrc
   ```

4. **Install Python 3.11**:
   ```bash
   pyenv install 3.11.9
   pyenv global 3.11.9
   ```

5. **Verify Python version**:
   ```bash
   python --version  # Should show Python 3.11.9
   ```

6. **Install uv package manager**:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   source ~/.bashrc
   ```

7. **Install Silica**:
   ```bash
   uv pip install pysilica
   ```

### Option 2: Using Docker

If you prefer containerized installation:

1. **Create a Dockerfile**:
   ```dockerfile
   FROM python:3.11-slim
   
   RUN pip install uv
   RUN uv pip install pysilica
   
   WORKDIR /workspace
   CMD ["silica", "--help"]
   ```

2. **Build and run**:
   ```bash
   docker build -t silica .
   docker run -it silica
   ```

### Option 3: Manual Python Build

If pyenv doesn't work for your system:

1. **Install build dependencies** (same as Option 1, step 1)

2. **Download and build Python 3.11**:
   ```bash
   cd /tmp
   wget https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
   tar -xzf Python-3.11.9.tgz
   cd Python-3.11.9
   ./configure --enable-optimizations --prefix=/usr/local
   make -j4
   sudo make altinstall
   ```

3. **Create a virtual environment**:
   ```bash
   python3.11 -m venv silica-env
   source silica-env/bin/activate
   ```

4. **Install Silica**:
   ```bash
   pip install pysilica
   ```

## Installation Verification

After installation, verify that Silica is working correctly:

```bash
# Check Silica version
silica --version

# View available commands
silica --help

# Test CLI functionality
silica config list
```

### Automated Verification

Use the included verification script to check your installation:

```bash
# If you have the source code
python scripts/verify_installation.py

# Or download and run directly
curl -sSL https://raw.githubusercontent.com/FitzSean/silica/main/scripts/verify_installation.py | python
```

## Automated Setup (Raspberry Pi)

For Raspberry Pi users, we provide an automated setup script:

```bash
# Download and run the setup script
curl -sSL https://raw.githubusercontent.com/FitzSean/silica/main/scripts/setup_environment.sh | bash

# Or if you have the source code
chmod +x scripts/setup_environment.sh
./scripts/setup_environment.sh
```

This script will:
- Detect your system type (Raspberry Pi vs standard Linux)
- Install Python 3.11 if needed using pyenv
- Set up a virtual environment
- Install uv package manager
- Install Silica and verify the installation

## Common Issues and Solutions

### Issue: "No solution found when resolving dependencies"

**Problem**: You're using Python < 3.11

**Solution**: 
- Check your Python version: `python --version`
- Follow the Raspberry Pi installation steps above
- Use `pyenv` to install Python 3.11+

### Issue: "pysilica not found" after installation

**Problem**: The package is installed but not in your PATH

**Solution**:
- Ensure your virtual environment is activated
- Check that the installation directory is in your PATH
- Try running `python -m silica.cli.main --help`

### Issue: Import errors for "silica" module

**Problem**: The package name is `pysilica` but imports as `silica`

**Solution**:
- Install with: `pip install pysilica`
- Import with: `import silica`
- CLI command: `silica`

### Issue: Permission denied during installation

**Problem**: Insufficient permissions for system-wide installation

**Solution**:
- Use virtual environments (recommended)
- Or install with `--user` flag: `pip install --user pysilica`

## Environment Management

### Using uv (Recommended)

```bash
# Create environment with specific Python version
uv venv --python 3.11 silica-env

# Activate environment
source silica-env/bin/activate

# Install Silica
uv pip install pysilica
```

### Using pip and venv

```bash
# Create environment
python3.11 -m venv silica-env

# Activate environment
source silica-env/bin/activate

# Install Silica
pip install pysilica
```

## Development Installation

For development work:

```bash
# Clone the repository
git clone https://github.com/FitzSean/silica.git
cd silica

# Create development environment
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install in development mode
uv pip install -e .

# Install development dependencies
uv pip install -e ".[dev]"
```

## Next Steps

After installation, see the main [README.md](../README.md) for usage instructions and examples.

## Support

If you encounter issues:

1. Check the [Common Issues](#common-issues-and-solutions) section above
2. Verify your Python version meets requirements
3. Ensure you're using the correct package name (`pysilica` not `silica`)
4. Create an issue on the project repository