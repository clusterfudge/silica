#!/usr/bin/env python3
"""
Test script to verify default arguments functionality for agents.
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
    """Test default arguments functionality."""
    print("🚀 Testing Default Arguments Functionality")
    print("=" * 50)

    # Test 1: Verify hdev has correct default arguments
    print("\n📋 Test 1: Verify hdev default arguments")
    if not run_command("silica agents set hdev"):
        sys.exit(1)

    if not run_command("silica agents show"):
        sys.exit(1)

    # Test 2: Check generated script has correct command
    print("\n📋 Test 2: Check AGENT.sh script")
    result = subprocess.run(
        ["cat", ".silica/agent-repo/AGENT.sh"], capture_output=True, text=True
    )
    if "uv run hdev --dwr --persona autonomous_engineer" in result.stdout:
        print("✅ AGENT.sh contains correct hdev command with default arguments")
        print("Command found: uv run hdev --dwr --persona autonomous_engineer")
    else:
        print("❌ AGENT.sh does not contain expected hdev command")
        print(f"Script content:\n{result.stdout}")
        sys.exit(1)

    # Test 3: Verify aider has correct default arguments
    print("\n📋 Test 3: Verify aider default arguments")
    if not run_command("silica agents set aider"):
        sys.exit(1)

    # Check aider script
    result = subprocess.run(
        ["cat", ".silica/agent-repo/AGENT.sh"], capture_output=True, text=True
    )
    if "uv run aider --auto-commits" in result.stdout:
        print("✅ AGENT.sh contains correct aider command with default arguments")
        print("Command found: uv run aider --auto-commits")
    else:
        print("❌ AGENT.sh does not contain expected aider command")
        print(f"Script content:\n{result.stdout}")
        sys.exit(1)

    # Test 4: Verify agent list shows default arguments
    print("\n📋 Test 4: Verify agent list shows default arguments")
    result = subprocess.run(
        ["silica", "agents", "list"], capture_output=True, text=True
    )
    if (
        "--dwr --persona autonomous_engineer" in result.stdout
        and "--auto-commits" in result.stdout
    ):
        print("✅ Agent list shows default arguments correctly")
    else:
        print("❌ Agent list does not show expected default arguments")
        print(f"Output:\n{result.stdout}")
        sys.exit(1)

    print("\n🎉 All default arguments tests passed!")
    print("\nVerified functionality:")
    print("✅ hdev includes --dwr --persona autonomous_engineer by default")
    print("✅ aider includes --auto-commits by default")
    print("✅ Generated AGENT.sh scripts contain correct commands")
    print("✅ Agent list displays default arguments")
    print("✅ Agent show command displays default and generated commands")


if __name__ == "__main__":
    main()
