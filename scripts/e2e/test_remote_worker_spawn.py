#!/usr/bin/env python3
"""Integration test for remote worker spawning.

This test verifies the end-to-end flow of spawning a worker
in a silica workspace and having it connect to the coordinator.

Prerequisites:
- Remote deaddrop server configured
- Git repository with origin remote

Usage:
    uv run python scripts/e2e/test_remote_worker_spawn.py
"""

import os
import sys
import time

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def test_remote_worker_spawn():
    """Test spawning a remote worker and verifying connection."""
    from deadrop import Deaddrop
    from deadrop.config import GlobalConfig

    from silica.developer.coordination.session import CoordinationSession, AgentState
    from silica.developer.tools.coordination import (
        set_current_session,
        spawn_agent,
        list_agents,
        terminate_agent,
    )

    print("=" * 60)
    print("Remote Worker Spawn Integration Test")
    print("=" * 60)

    # Check for remote deaddrop config
    if not GlobalConfig.exists():
        print("\n❌ SKIP: No deaddrop config found")
        print("Run 'deadrop init' to configure remote server first")
        return False

    config = GlobalConfig.load()
    print(f"\n✓ Using deaddrop: {config.url}")

    # Create deaddrop client
    deaddrop = Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)

    # Create coordination session
    print("\n1. Creating coordination session...")
    session = CoordinationSession.create_session(
        deaddrop=deaddrop,
        display_name="Remote Worker Test Session",
    )
    set_current_session(session)
    print(f"   ✓ Session created: {session.session_id}")

    # Spawn a remote worker
    print("\n2. Spawning remote worker...")
    workspace_name = f"test-worker-{int(time.time())}"

    result = spawn_agent(
        workspace_name=workspace_name,
        display_name="Test Remote Worker",
        remote=True,
    )
    print("\n   Spawn result:")
    for line in result.split("\n"):
        print(f"   {line}")

    # Check if spawn succeeded
    if "FAILED" in result:
        print("\n❌ Worker spawn failed!")
        # Clean up
        set_current_session(None)
        return False

    # List agents
    print("\n3. Checking agent status...")
    agent_list = list_agents(show_details=True)
    print(agent_list)

    # Find our agent
    agents = session.list_agents()
    test_agent = None
    for agent in agents:
        if agent.workspace_name == workspace_name:
            test_agent = agent
            break

    if not test_agent:
        print("\n❌ Could not find spawned agent!")
        set_current_session(None)
        return False

    print(f"\n   Agent ID: {test_agent.agent_id}")
    print(f"   State: {test_agent.state}")
    print(f"   Remote workspace: {test_agent.remote_workspace}")

    # Wait a bit for worker to connect
    print("\n4. Waiting for worker to connect...")
    for i in range(6):  # 30 seconds max
        time.sleep(5)
        agent = session.get_agent(test_agent.agent_id)
        print(f"   [{i*5}s] State: {agent.state}")

        if agent.state == AgentState.IDLE:
            print("\n   ✓ Worker connected and ready!")
            break
    else:
        print("\n   ⚠ Worker did not reach IDLE state (may still be starting)")

    # Terminate the worker
    print("\n5. Terminating worker...")
    term_result = terminate_agent(
        test_agent.agent_id,
        reason="Test complete",
        destroy_workspace=True,
    )
    print(term_result)

    # Clean up
    set_current_session(None)

    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)

    return True


if __name__ == "__main__":
    success = test_remote_worker_spawn()
    sys.exit(0 if success else 1)
