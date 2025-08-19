#!/usr/bin/env python3
"""
Agent Workspace Setup Verification Script

This script verifies that the agent workspace is properly set up
on the remote Raspberry Pi system.
"""

import sys
import subprocess
import platform
import os
from pathlib import Path


def check_python_version():
    """Check if Python version meets requirements."""
    print("🐍 Checking Python version...")
    version = sys.version_info
    print(f"   Python {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("   ❌ ERROR: Python 3.11 or higher is required")
        return False
    else:
        print("   ✅ Python version meets requirements")
        return True


def check_virtual_environment():
    """Check if we're in a virtual environment."""
    print("\n🔒 Checking virtual environment...")

    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        print("   ✅ Running in virtual environment")
        print(f"   📁 Environment: {sys.prefix}")
        return True
    else:
        print("   ❌ Not running in virtual environment")
        print("   💡 Run: source .venv/bin/activate")
        return False


def check_silica_import():
    """Check if silica module can be imported."""
    print("\n📦 Checking Silica module import...")
    try:
        print("   ✅ Silica module imports successfully")

        # Check if version is available
        try:
            from silica._version import __version__

            print(f"   📋 Version: {__version__}")
        except ImportError:
            print("   ⚠️  Version information not available")

        return True
    except ImportError as e:
        print(f"   ❌ ERROR: Cannot import silica module: {e}")
        return False


def check_uv_availability():
    """Check if uv package manager is available."""
    print("\n📦 Checking uv package manager...")
    try:
        result = subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, timeout=5
        )

        if result.returncode == 0:
            print("   ✅ uv is available")
            if result.stdout.strip():
                print(f"   📋 {result.stdout.strip()}")
            return True
        else:
            print("   ❌ uv command failed")
            return False

    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("   ❌ uv not found")
        return False


def check_pyenv_setup():
    """Check if pyenv is properly set up."""
    print("\n🔧 Checking pyenv setup...")

    pyenv_root = os.path.expanduser("~/.pyenv")
    if Path(pyenv_root).exists():
        print("   ✅ pyenv directory exists")

        # Check if Python 3.11 is installed
        try:
            result = subprocess.run(
                ["pyenv", "versions"], capture_output=True, text=True, timeout=5
            )

            if "3.11" in result.stdout:
                print("   ✅ Python 3.11 available in pyenv")
                return True
            else:
                print("   ⚠️  Python 3.11 not found in pyenv")
                return False

        except (subprocess.TimeoutExpired, FileNotFoundError):
            print("   ❌ pyenv command not available")
            return False
    else:
        print("   ⚠️  pyenv not installed")
        return False


def check_workspace_files():
    """Check if required workspace files exist."""
    print("\n📁 Checking workspace files...")

    required_files = [
        "pyproject.toml",
        ".python-version",
        "Procfile",
        "setup_python.sh",
        "verify_setup.py",
    ]

    all_good = True
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"   ✅ {file_path}")
        else:
            print(f"   ❌ {file_path} missing")
            all_good = False

    return all_good


def check_raspberry_pi():
    """Check if running on Raspberry Pi."""
    print("\n🥧 Checking system type...")

    # Check for Raspberry Pi
    is_pi = False
    if Path("/proc/device-tree/model").exists():
        try:
            with open("/proc/device-tree/model", "r") as f:
                model = f.read()
                if "Raspberry Pi" in model:
                    is_pi = True
                    print(f"   🥧 Running on: {model.strip()}")
        except Exception:
            pass

    if not is_pi:
        print(f"   💻 System: {platform.system()} {platform.machine()}")

    return is_pi


def check_workspace_configuration():
    """Check if workspace is properly configured."""
    print("\n⚙️ Checking workspace configuration...")

    # Check Procfile
    if Path("Procfile").exists():
        print("   ✅ Procfile exists")
        return True
    else:
        print("   ❌ Procfile missing")
        return False


def main():
    """Main verification function."""
    print("🔍 Agent Workspace Setup Verification")
    print("=" * 45)

    # System information
    check_raspberry_pi()

    # Core checks
    checks = [
        check_python_version(),
        check_virtual_environment(),
        check_silica_import(),
        check_workspace_files(),
        check_workspace_configuration(),
    ]

    # Optional checks (don't fail if these don't pass)
    optional_checks = [
        check_uv_availability(),
        check_pyenv_setup(),
    ]

    print("\n" + "=" * 45)

    if all(checks):
        print("🎉 Core setup verification passed!")

        if any(optional_checks):
            print("✅ Optional components are also working")
        else:
            print("⚠️  Some optional components may not be available")

        print("\n🚀 Agent workspace is ready!")
        print("To start the agent:")
        print("  source .venv/bin/activate")
        print("  uv run silica we run")

        return 0
    else:
        print("❌ Setup verification failed!")
        print("\n🔧 To fix issues:")
        print("  1. Run: ./setup_python.sh")
        print("  2. Activate environment: source .venv/bin/activate")
        print("  3. Run this script again")

        return 1


if __name__ == "__main__":
    sys.exit(main())
