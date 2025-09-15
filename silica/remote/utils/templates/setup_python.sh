#!/bin/bash
"""
Python 3.11 Setup Script for Raspberry Pi Agent Workspace

This script is deployed as part of the agent workspace and handles
Python 3.11 installation on the remote Raspberry Pi system.
"""

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running on Raspberry Pi
is_raspberry_pi() {
    if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model; then
        return 0
    elif [ -f /sys/firmware/devicetree/base/model ] && grep -q "Raspberry Pi" /sys/firmware/devicetree/base/model; then
        return 0
    else
        return 1
    fi
}

# Check Python version
check_python_version() {
    print_status "Checking Python version..."
    
    if command -v python3 &> /dev/null; then
        python_version=$(python3 --version 2>&1 | cut -d' ' -f2)
        major=$(echo "$python_version" | cut -d'.' -f1)
        minor=$(echo "$python_version" | cut -d'.' -f2)
        
        echo "Found Python $python_version"
        
        if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
            print_success "Python version meets requirements (3.11+)"
            return 0
        else
            print_warning "Python version $python_version is below 3.11 requirement"
            return 1
        fi
    else
        print_error "Python3 not found"
        return 1
    fi
}

# Install system dependencies for building Python
install_python_build_deps() {
    print_status "Installing Python build dependencies..."
    
    if command -v apt-get &> /dev/null; then
        sudo apt-get update
        sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
            libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
            libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
            libffi-dev liblzma-dev git
        print_success "Build dependencies installed"
    else
        print_error "apt-get not found. This script requires Debian/Ubuntu-based systems."
        return 1
    fi
}

# Install pyenv
install_pyenv() {
    print_status "Installing pyenv..."
    
    if [ ! -d "$HOME/.pyenv" ]; then
        curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
        
        # Add pyenv to shell profiles
        for profile in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
            if [ -f "$profile" ]; then
                if ! grep -q "PYENV_ROOT" "$profile"; then
                    echo 'export PYENV_ROOT="$HOME/.pyenv"' >> "$profile"
                    echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> "$profile"
                    echo 'eval "$(pyenv init --path)"' >> "$profile"
                    echo 'eval "$(pyenv init -)"' >> "$profile"
                fi
            fi
        done
        
        print_success "pyenv installed"
    else
        print_success "pyenv already installed"
    fi
    
    # Set up pyenv for current session
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init --path)" 2>/dev/null || true
    eval "$(pyenv init -)" 2>/dev/null || true
}

# Install Python 3.11 using pyenv
install_python311() {
    print_status "Installing Python 3.11.9 using pyenv..."
    
    # Set up pyenv environment
    export PYENV_ROOT="$HOME/.pyenv"
    export PATH="$PYENV_ROOT/bin:$PATH"
    eval "$(pyenv init --path)" 2>/dev/null || true
    eval "$(pyenv init -)" 2>/dev/null || true
    
    if pyenv versions | grep -q "3.11.9"; then
        print_success "Python 3.11.9 already installed"
    else
        print_status "Installing Python 3.11.9 (this may take 20-30 minutes on Raspberry Pi)..."
        pyenv install 3.11.9
        print_success "Python 3.11.9 installed"
    fi
    
    # Set as local version for this directory
    pyenv local 3.11.9
    print_success "Python 3.11.9 set as local version"
}

# Install uv package manager
install_uv() {
    print_status "Installing uv package manager..."
    
    if command -v uv &> /dev/null; then
        print_success "uv already installed"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        
        # Add uv to current session
        export PATH="$HOME/.local/bin:$PATH"
        
        print_success "uv installed"
    fi
}

# Install GitHub CLI
install_github_cli() {
    print_status "Installing GitHub CLI..."
    
    if command -v gh &> /dev/null; then
        print_success "GitHub CLI already installed"
        return
    fi
    
    # Install GitHub CLI for Debian/Ubuntu systems
    if command -v apt-get &> /dev/null; then
        curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
            && sudo chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
            && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
            && sudo apt update \
            && sudo apt install gh -y
        
        if command -v gh &> /dev/null; then
            print_success "GitHub CLI installed"
        else
            print_warning "GitHub CLI installation may have failed"
        fi
    else
        print_warning "Cannot install GitHub CLI - apt-get not found"
        print_warning "Install manually: https://github.com/cli/cli#installation"
    fi
}

# Set up GitHub authentication if tokens are available
setup_github_auth() {
    print_status "Setting up GitHub authentication..."
    
    # Check for GitHub tokens
    if [ -n "$GH_TOKEN" ] || [ -n "$GITHUB_TOKEN" ]; then
        if command -v gh &> /dev/null; then
            print_status "Configuring GitHub CLI authentication..."
            
            # Use the available token
            GITHUB_TOKEN_TO_USE="${GH_TOKEN:-$GITHUB_TOKEN}"
            
            # Set up GitHub CLI authentication
            echo "$GITHUB_TOKEN_TO_USE" | gh auth login --with-token >/dev/null 2>&1
            
            if [ $? -eq 0 ]; then
                # Set up git integration
                gh auth setup-git >/dev/null 2>&1
                print_success "GitHub CLI authentication configured"
            else
                print_warning "GitHub CLI authentication setup failed"
            fi
        else
            print_warning "GitHub CLI not available - using direct git credentials"
            
            # Set up git credentials directly
            git config --global credential.https://github.com.helper ""
            git config --global credential.https://github.com.username "token"
            git config --global credential.https://github.com.password "${GH_TOKEN:-$GITHUB_TOKEN}"
            
            print_success "Git credentials configured for GitHub"
        fi
    else
        print_warning "No GitHub tokens found in environment variables"
        print_warning "Set GH_TOKEN or GITHUB_TOKEN for automatic GitHub authentication"
    fi
}

# Set up virtual environment
setup_venv() {
    print_status "Setting up virtual environment..."
    
    # Ensure we have the right Python version
    if ! python3 --version | grep -q "3.11"; then
        print_error "Python 3.11 not available. Setup may have failed."
        return 1
    fi
    
    # Create virtual environment if it doesn't exist
    if [ ! -d ".venv" ]; then
        if command -v uv &> /dev/null; then
            uv venv --python python3
        else
            python3 -m venv .venv
        fi
        print_success "Virtual environment created"
    else
        print_success "Virtual environment already exists"
    fi
    
    # Activate virtual environment
    source .venv/bin/activate
    
    # Install dependencies
    if [ -f "pyproject.toml" ]; then
        if command -v uv &> /dev/null; then
            uv pip install -e .
        else
            pip install -e .
        fi
        print_success "Dependencies installed from pyproject.toml"
    elif [ -f "requirements.txt" ]; then
        if command -v uv &> /dev/null; then
            uv pip install -r requirements.txt
        else
            pip install -r requirements.txt
        fi
        print_success "Dependencies installed from requirements.txt"
    fi
    
    # Ensure pysilica is installed
    if command -v uv &> /dev/null; then
        uv pip install pysilica
    else
        pip install pysilica
    fi
    print_success "Silica installed"
}

# Verify installation
verify_setup() {
    print_status "Verifying setup..."
    
    # Activate virtual environment
    source .venv/bin/activate
    
    # Check Python version
    python_version=$(python --version 2>&1)
    if echo "$python_version" | grep -q "3.11"; then
        print_success "Python version: $python_version"
    else
        print_error "Python version check failed: $python_version"
        return 1
    fi
    
    # Check if pysilica is available
    if python -c "import silica" 2>/dev/null; then
        print_success "Silica module imports successfully"
    else
        print_warning "Silica module not found, installing..."
        if command -v uv &> /dev/null; then
            uv pip install pysilica
        else
            pip install pysilica
        fi
    fi
    
    # Test CLI
    if python -m silica.cli.main --version &>/dev/null; then
        print_success "Silica CLI working"
    else
        print_error "Silica CLI not working"
        return 1
    fi
}

# Main setup function
main() {
    echo "🔧 Python 3.11 Setup for Raspberry Pi Agent Workspace"
    echo "====================================================="
    
    # Check if we're on Raspberry Pi
    if is_raspberry_pi; then
        print_status "Detected Raspberry Pi system"
    else
        print_status "Non-Raspberry Pi system detected"
    fi
    
    # Check current Python version
    if check_python_version; then
        print_status "Python 3.11+ already available, skipping installation"
    else
        print_status "Python 3.11+ not available, installing via pyenv..."
        
        install_python_build_deps
        install_pyenv
        install_python311
        
        print_warning "Reloading shell environment..."
        exec "$SHELL"
    fi
    
    # Install uv
    install_uv
    
    # Install GitHub CLI (useful for authentication)
    install_github_cli
    
    # Set up GitHub authentication
    setup_github_auth
    
    # Set up virtual environment
    setup_venv
    
    # Verify setup
    verify_setup
    
    echo
    print_success "Setup complete! 🎉"
    echo
    echo "To activate the environment:"
    echo "  source .venv/bin/activate"
    echo
    echo "To run the agent:"
    echo "  uv run silica remote antennae --port \$PORT"
}

# Run main function
main "$@"