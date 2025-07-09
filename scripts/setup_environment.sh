#!/bin/bash
"""
Silica Environment Setup Script

This script helps set up the Python environment for Silica on various systems,
especially useful for Raspberry Pi where Python 3.11+ needs to be installed.
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
        print_success "Dependencies installed"
    elif command -v yum &> /dev/null; then
        sudo yum groupinstall -y "Development Tools"
        sudo yum install -y zlib-devel bzip2 bzip2-devel readline-devel sqlite \
            sqlite-devel openssl-devel xz xz-devel libffi-devel
        print_success "Dependencies installed"
    else
        print_warning "Package manager not recognized. Please install build dependencies manually."
    fi
}

# Install pyenv
install_pyenv() {
    print_status "Installing pyenv..."
    
    if [ ! -d "$HOME/.pyenv" ]; then
        curl -L https://github.com/pyenv/pyenv-installer/raw/master/bin/pyenv-installer | bash
        
        # Add pyenv to shell profile
        shell_profile=""
        if [ -f "$HOME/.bashrc" ]; then
            shell_profile="$HOME/.bashrc"
        elif [ -f "$HOME/.zshrc" ]; then
            shell_profile="$HOME/.zshrc"
        elif [ -f "$HOME/.profile" ]; then
            shell_profile="$HOME/.profile"
        fi
        
        if [ -n "$shell_profile" ]; then
            echo 'export PYENV_ROOT="$HOME/.pyenv"' >> "$shell_profile"
            echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> "$shell_profile"
            echo 'eval "$(pyenv init --path)"' >> "$shell_profile"
            echo 'eval "$(pyenv init -)"' >> "$shell_profile"
            
            print_success "pyenv installed and configured in $shell_profile"
            print_warning "Please restart your shell or run: source $shell_profile"
        else
            print_warning "Could not find shell profile. Please configure pyenv manually."
        fi
        
        # Set up pyenv for current session
        export PYENV_ROOT="$HOME/.pyenv"
        export PATH="$PYENV_ROOT/bin:$PATH"
        eval "$(pyenv init --path)" 2>/dev/null || true
        eval "$(pyenv init -)" 2>/dev/null || true
    else
        print_success "pyenv already installed"
    fi
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
        print_status "This may take a while on Raspberry Pi..."
        pyenv install 3.11.9
        print_success "Python 3.11.9 installed"
    fi
    
    # Set as global version
    pyenv global 3.11.9
    print_success "Python 3.11.9 set as global version"
}

# Install uv package manager
install_uv() {
    print_status "Installing uv package manager..."
    
    if command -v uv &> /dev/null; then
        print_success "uv already installed"
    else
        curl -LsSf https://astral.sh/uv/install.sh | sh
        print_success "uv installed"
        print_warning "Please restart your shell or run: source ~/.bashrc"
    fi
}

# Create virtual environment and install Silica
install_silica() {
    print_status "Creating virtual environment and installing Silica..."
    
    # Create environment directory
    env_dir="$HOME/silica-env"
    
    if [ -d "$env_dir" ]; then
        print_warning "Environment directory $env_dir already exists"
        read -p "Remove and recreate? (y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "$env_dir"
        else
            print_status "Using existing environment"
        fi
    fi
    
    # Create virtual environment
    if [ ! -d "$env_dir" ]; then
        if command -v uv &> /dev/null; then
            uv venv --python 3.11 "$env_dir"
        else
            python3 -m venv "$env_dir"
        fi
        print_success "Virtual environment created at $env_dir"
    fi
    
    # Activate and install Silica
    source "$env_dir/bin/activate"
    
    if command -v uv &> /dev/null; then
        uv pip install pysilica
    else
        pip install pysilica
    fi
    
    print_success "Silica installed successfully"
    
    # Create convenience script
    cat > "$HOME/use_silica.sh" << 'EOF'
#!/bin/bash
# Convenience script to use Silica with the correct environment
source "$HOME/silica-env/bin/activate"
silica "$@"
EOF
    
    chmod +x "$HOME/use_silica.sh"
    print_success "Convenience script created at $HOME/use_silica.sh"
}

# Verify installation
verify_installation() {
    print_status "Verifying installation..."
    
    # Activate environment
    source "$HOME/silica-env/bin/activate"
    
    # Run verification script if available
    if [ -f "scripts/verify_installation.py" ]; then
        python scripts/verify_installation.py
    else
        # Basic verification
        if python -c "import silica; print('✅ Silica imports successfully')" 2>/dev/null; then
            print_success "Silica verification passed"
        else
            print_error "Silica verification failed"
            return 1
        fi
    fi
}

# Main setup function
main() {
    echo "🔧 Silica Environment Setup"
    echo "=========================="
    
    # Check if we're on Raspberry Pi
    if is_raspberry_pi; then
        print_status "Detected Raspberry Pi system"
        raspberry_pi=true
    else
        print_status "Standard Linux/Unix system detected"
        raspberry_pi=false
    fi
    
    # Check current Python version
    if ! check_python_version; then
        print_status "Python 3.11+ required. Setting up pyenv installation..."
        
        install_python_build_deps
        install_pyenv
        install_python311
        
        print_warning "Please restart your shell or run 'source ~/.bashrc' then re-run this script"
        exit 0
    fi
    
    # Install uv if not present
    install_uv
    
    # Install Silica
    install_silica
    
    # Verify installation
    verify_installation
    
    echo
    print_success "Setup complete! 🎉"
    echo
    echo "To use Silica:"
    echo "  • Run: source ~/silica-env/bin/activate"
    echo "  • Or use: ~/use_silica.sh <command>"
    echo "  • Example: ~/use_silica.sh --help"
    echo
    echo "Next steps:"
    echo "  • Run 'silica create' to create your first workspace"
    echo "  • See README.md for usage examples"
}

# Run main function
main "$@"