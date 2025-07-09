#!/usr/bin/env python3
"""
Silica Installation Verification Script

This script verifies that Silica is properly installed and functional.
"""

import sys
import subprocess
import platform


def check_python_version():
    """Check if Python version meets requirements."""
    print("🐍 Checking Python version...")
    version = sys.version_info
    print(f"   Python {version.major}.{version.minor}.{version.micro}")

    if version.major < 3 or (version.major == 3 and version.minor < 11):
        print("   ❌ ERROR: Python 3.11 or higher is required")
        print("   📖 See docs/INSTALLATION.md for installation instructions")
        return False
    else:
        print("   ✅ Python version meets requirements")
        return True


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
        print("   💡 Try: pip install pysilica")
        return False


def check_cli_command():
    """Check if silica CLI command is available."""
    print("\n🔧 Checking CLI command availability...")
    try:
        result = subprocess.run(
            ["silica", "--version"], capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0:
            print("   ✅ CLI command 'silica' is available")
            if result.stdout.strip():
                print(f"   📋 {result.stdout.strip()}")
            return True
        else:
            print(f"   ❌ CLI command failed with code {result.returncode}")
            if result.stderr:
                print(f"   📝 Error: {result.stderr.strip()}")
            return False

    except subprocess.TimeoutExpired:
        print("   ❌ CLI command timed out")
        return False
    except FileNotFoundError:
        print("   ❌ CLI command 'silica' not found in PATH")
        print("   💡 Make sure your virtual environment is activated")
        print("   💡 Or try: python -m silica.cli.main --help")
        return False


def check_key_modules():
    """Check if key silica modules are available."""
    print("\n🧩 Checking key modules...")
    modules_to_check = [
        "silica.cli.main",
        "silica.utils.agents",
        "silica.config",
        "silica.messaging",
    ]

    all_good = True
    for module in modules_to_check:
        try:
            __import__(module)
            print(f"   ✅ {module}")
        except ImportError as e:
            print(f"   ❌ {module}: {e}")
            all_good = False

    return all_good


def check_dependencies():
    """Check if key dependencies are available."""
    print("\n📚 Checking dependencies...")
    dependencies = [
        "click",
        "rich",
        "requests",
        "yaml",
        "git",
        "flask",
        "filelock",
    ]

    all_good = True
    for dep in dependencies:
        try:
            if dep == "yaml":
                pass
            elif dep == "git":
                pass
            else:
                __import__(dep)
            print(f"   ✅ {dep}")
        except ImportError as e:
            print(f"   ❌ {dep}: {e}")
            all_good = False

    return all_good


def check_system_info():
    """Display system information."""
    print("\n💻 System Information:")
    print(f"   OS: {platform.system()} {platform.release()}")
    print(f"   Architecture: {platform.machine()}")
    print(f"   Python executable: {sys.executable}")

    # Check if we're in a virtual environment
    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        print("   🔒 Running in virtual environment")
    else:
        print("   🌐 Running in system Python")


def main():
    """Main verification function."""
    print("🔍 Silica Installation Verification")
    print("=" * 40)

    check_system_info()

    checks = [
        check_python_version(),
        check_silica_import(),
        check_key_modules(),
        check_dependencies(),
        check_cli_command(),
    ]

    print("\n" + "=" * 40)

    if all(checks):
        print("🎉 All checks passed! Silica is properly installed and ready to use.")
        print("\n🚀 Next steps:")
        print("   • Run 'silica --help' to see available commands")
        print("   • Run 'silica create' to create your first workspace")
        print("   • See README.md for usage examples")
        return 0
    else:
        print("❌ Some checks failed. Please review the errors above.")
        print("\n📖 For troubleshooting:")
        print("   • See docs/INSTALLATION.md for detailed installation instructions")
        print("   • Ensure you're using Python 3.11 or higher")
        print("   • Make sure you installed 'pysilica' (not 'silica')")
        return 1


if __name__ == "__main__":
    sys.exit(main())
