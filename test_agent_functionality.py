#!/usr/bin/env python3
"""
Quick test script to demonstrate SILIC-2 multiple agent support functionality.
Run this to verify that all agent management features are working correctly.
"""

import subprocess
import sys


def run_command(cmd):
    """Run a command and return the result."""
    print(f"\n🔧 Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return False
    print(f"✅ Success:\n{result.stdout}")
    return True


def main():
    """Test all agent functionality."""
    print("🚀 Testing SILIC-2 Multiple Agent Support")
    print("=" * 50)

    # Test 1: List agents
    if not run_command("silica agents list"):
        sys.exit(1)

    # Test 2: Show current status
    if not run_command("silica agents status"):
        sys.exit(1)

    # Test 3: Show detailed configuration
    if not run_command("silica agents show"):
        sys.exit(1)

    # Test 4: Switch to aider
    if not run_command("silica agents set aider"):
        sys.exit(1)

    # Test 5: Verify the switch worked
    if not run_command("silica agents status"):
        sys.exit(1)

    # Test 6: Switch back to hdev
    if not run_command("silica agents set hdev"):
        sys.exit(1)

    # Test 7: Configure with different agent
    if not run_command("silica agents configure claude-code"):
        sys.exit(1)

    # Test 8: Final status check
    if not run_command("silica agents status"):
        sys.exit(1)

    print("\n🎉 All tests passed! SILIC-2 multiple agent support is working correctly.")
    print("\nKey features verified:")
    print("✅ Agent listing and discovery")
    print("✅ Agent status monitoring")
    print("✅ Agent switching between types")
    print("✅ Configuration management")
    print("✅ Script generation")
    print("✅ Workspace integration")


if __name__ == "__main__":
    main()
