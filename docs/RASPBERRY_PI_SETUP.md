# Raspberry Pi Setup Guide

This guide helps you set up Silica on Raspberry Pi and other ARM-based systems where the default Python version may be too old.

## Common Issues

### Python Version Compatibility

Silica requires Python 3.11 or newer, but many Raspberry Pi systems come with older Python versions (3.7 or earlier) that don't support the features required by modern tools like `uv`.

**Symptoms:**
- Error: `Python executable does not support -I flag`
- Agent sessions fail to launch
- `uv` commands fail with Python interpreter errors

## Quick Diagnosis

Run the built-in diagnostic tool to check your Python environment:

```bash
si python-check
```

This will show you:
- Available Python versions on your system
- Which versions are compatible with Silica
- Whether `uv` can work with your current setup

For installation help:
```bash
si python-check --help-install
```

To automatically configure the environment:
```bash
si python-check --fix
```

## Python Installation Options

### Option 1: Using pyenv (Recommended)

Pyenv allows you to install and manage multiple Python versions easily:

```bash
# Install pyenv
curl https://pyenv.run | bash

# Add to your shell configuration (~/.bashrc or ~/.zshrc)
export PATH="$HOME/.pyenv/bin:$PATH"
eval "$(pyenv init -)"

# Restart your shell or run:
source ~/.bashrc

# Install Python 3.11
pyenv install 3.11.7
pyenv global 3.11.7

# Verify installation
python --version
```

### Option 2: System Package Manager

For Raspberry Pi OS and other Debian-based systems:

```bash
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-pip
```

Note: The deadsnakes PPA may not be available for all ARM architectures. In that case, use pyenv or build from source.

### Option 3: Building from Source

If package managers don't have Python 3.11+ for your architecture:

```bash
# Install build dependencies
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev \
    libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
    libncurses5-dev libncursesw5-dev xz-utils tk-dev libffi-dev \
    liblzma-dev python3-openssl git

# Download and build Python 3.11
wget https://www.python.org/ftp/python/3.11.7/Python-3.11.7.tgz
tar xzf Python-3.11.7.tgz
cd Python-3.11.7
./configure --enable-optimizations
make -j$(nproc)
sudo make altinstall

# Verify installation
python3.11 --version
```

## Configuring UV

Once you have Python 3.11+ installed, you need to tell `uv` to use it:

### Manual Configuration

```bash
# Find your Python 3.11 installation
which python3.11

# Set UV_PYTHON environment variable
export UV_PYTHON=/usr/local/bin/python3.11

# Make it permanent by adding to ~/.bashrc or ~/.profile
echo 'export UV_PYTHON=/usr/local/bin/python3.11' >> ~/.bashrc
```

### Automatic Configuration

Silica can detect and configure the appropriate Python automatically:

```bash
si python-check --fix
```

This will:
1. Search for suitable Python installations
2. Test compatibility with `uv`
3. Set the `UV_PYTHON` environment variable
4. Provide instructions for making the change permanent

## Verification

After installation and configuration:

1. **Check Python version:**
   ```bash
   python3.11 --version
   # Should show 3.11.x or newer
   ```

2. **Verify UV configuration:**
   ```bash
   echo $UV_PYTHON
   # Should show path to your Python 3.11+ installation
   ```

3. **Test UV functionality:**
   ```bash
   uv --version
   uv python list
   ```

4. **Run Silica diagnostic:**
   ```bash
   si python-check
   # Should show all green checkmarks
   ```

5. **Test agent launch:**
   ```bash
   si workspace environment run
   ```

## Troubleshooting

### "No suitable Python found" Error

If the automatic detection doesn't work:

1. **Manually find Python installations:**
   ```bash
   # Check common locations
   ls /usr/bin/python*
   ls /usr/local/bin/python*
   ls ~/.pyenv/versions/*/bin/python*
   
   # Test each one
   /path/to/python --version
   ```

2. **Manually set UV_PYTHON:**
   ```bash
   export UV_PYTHON=/path/to/your/python3.11
   si python-check
   ```

### UV Still Uses Wrong Python

If `uv` ignores your `UV_PYTHON` setting:

1. **Check for virtual environment conflicts:**
   ```bash
   # Deactivate any active virtual environments
   deactivate
   
   # Or use uv run with explicit Python
   uv run --python $UV_PYTHON si python-check
   ```

2. **Clear UV cache:**
   ```bash
   rm -rf ~/.cache/uv
   ```

### Build Errors When Installing Python

If building Python from source fails:

1. **Install missing dependencies:**
   ```bash
   sudo apt install -y build-essential zlib1g-dev libncurses5-dev \
       libgdbm-dev libnss3-dev libssl-dev libreadline-dev libffi-dev \
       libsqlite3-dev wget libbz2-dev
   ```

2. **For ARM-specific issues:**
   ```bash
   # Configure with explicit architecture
   ./configure --build=arm-linux-gnueabihf --enable-optimizations
   ```

## Performance Notes

- Building Python from source on Raspberry Pi can take 30+ minutes
- Consider using a faster machine to cross-compile if building frequently
- pyenv installations are generally faster than building from source
- The `--enable-optimizations` flag makes Python faster but takes longer to build

## Support

If you continue to have issues:

1. Run `si python-check` and share the output
2. Include your Raspberry Pi model and OS version
3. Show the error message you're receiving
4. Check the [GitHub issues](https://github.com/your-repo/silica/issues) for similar problems