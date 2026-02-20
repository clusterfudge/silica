#!/usr/bin/env python3
"""E2E Test: Full coordinator workflow using coordinator tools."""

import os
import sys
import time
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from worker_utils import kill_tmux_session
from silica.developer.coordination.session import CoordinationSession


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def get_configured_deaddrop():
    from deadrop import Deaddrop
    from deadrop.config import GlobalConfig

    if not GlobalConfig.exists():
        raise RuntimeError("Deaddrop not configured")

    config = GlobalConfig.load()
    return Deaddrop.remote(url=config.url, bearer_token=config.bearer_token)


def spawn_worker_process(session_name: str, invite_url: str, agent_id: str) -> bool:
    script_dir = os.path.dirname(__file__)
    silica_dir = os.path.dirname(os.path.dirname(script_dir))

    subprocess.run(["tmux", "kill-session", "-t", session_name], capture_output=True)

    cmd = f"DEADDROP_INVITE_URL='{invite_url}' COORDINATION_AGENT_ID='{agent_id}' uv run python scripts/e2e/minimal_worker.py; echo 'WORKER_EXITED'; sleep 60"
    result = subprocess.run(
        ["tmux", "new-session", "-d", "-s", session_name, "-c", silica_dir, cmd],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def main():
    print("=" * 60)
    print("E2E Test: Full Coordinator Workflow")
    print("=" * 60)

    deaddrop = get_configured_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    sessions = []

    # Create session
    log("Step 1: Creating coordination session...")
    session = CoordinationSession.create_session(
        deaddrop=deaddrop,
        display_name="E2E Coordinator Test",
    )
    log(f"✓ Session: {session.session_id}")

    from silica.developer.tools import coordination as coord_tools

    coord_tools.set_current_session(session)

    try:
        # Spawn workers using the tool
        log("Step 2: Creating workers via spawn_agent tool...")
        spawn_result_1 = coord_tools.spawn_agent(
            workspace_name="w1", display_name="Worker Alpha"
        )
        spawn_result_2 = coord_tools.spawn_agent(
            workspace_name="w2", display_name="Worker Beta"
        )

        def extract(result):
            invite_url = agent_id = None
            for line in result.split("\n"):
                if "DEADDROP_INVITE_URL" in line and "`: " in line:
                    invite_url = line.split("`: ", 1)[1].strip()
                if "Agent ID:" in line:
                    agent_id = line.split(": ", 1)[1].strip()
            return invite_url, agent_id

        invite_url_1, agent_id_1 = extract(spawn_result_1)
        invite_url_2, agent_id_2 = extract(spawn_result_2)

        log(f"✓ Worker Alpha: {agent_id_1}")
        log(f"✓ Worker Beta: {agent_id_2}")

        # Spawn actual processes
        log("Step 3: Spawning worker processes...")
        sessions.extend(["e2e-w1", "e2e-w2"])
        spawn_worker_process("e2e-w1", invite_url_1, agent_id_1)
        spawn_worker_process("e2e-w2", invite_url_2, agent_id_2)
        log("✓ Processes spawned")

        # Poll for Idle messages
        log("Step 4: Polling for worker Idle messages...")
        idle_agents = set()
        timeout = 30
        start = time.time()

        while time.time() - start < timeout and len(idle_agents) < 2:
            poll_result = coord_tools.poll_messages(include_room=True)

            if "No new messages" not in poll_result:
                # Check for each agent's Idle
                for agent_id in [agent_id_1, agent_id_2]:
                    if agent_id in poll_result and agent_id not in idle_agents:
                        idle_agents.add(agent_id)
                        log(f"✓ Got Idle from {agent_id}")
            time.sleep(1)

        if len(idle_agents) < 2:
            log(f"FAILED: Only {len(idle_agents)}/2 workers reported")
            return False

        # Check agent states
        log("Step 5: Checking agent states via list_agents...")
        agents_list = coord_tools.list_agents(show_details=True)
        log(f"Agents:\n{agents_list}")

        # Assign task
        log("Step 6: Assigning task via message_agent...")
        coord_tools.message_agent(
            agent_id=agent_id_1,
            message_type="task",
            task_id="e2e-task-001",
            description="Test task",
        )
        log("✓ Task assigned")

        # Poll for completion
        log("Step 7: Polling for task results...")
        received_ack = False
        received_result = False
        progress_count = 0
        timeout = 60
        start = time.time()

        while time.time() - start < timeout:
            poll_result = coord_tools.poll_messages(include_room=True)
            result_lower = poll_result.lower()

            if "no new messages" in result_lower:
                time.sleep(1)
                continue

            # Check for task_ack
            if "task_ack" in result_lower and not received_ack:
                log("✓ TaskAck received")
                received_ack = True

            # Check for progress
            if "progress" in result_lower and "type" in result_lower:
                progress_count += 1
                log(f"✓ Progress #{progress_count}")

            # Check for result (type: result)
            if "type:** result" in result_lower:
                log("✓ Result received")
                received_result = True

            if received_ack and received_result and progress_count >= 2:
                break
            time.sleep(1)

        if not received_ack or not received_result:
            log(
                f"FAILED: ack={received_ack}, result={received_result}, progress={progress_count}"
            )
            return False

        # Get final state
        log("Step 8: Getting session state...")
        state = coord_tools.get_session_state()
        log(f"State:\n{state}")

        # Terminate
        log("Step 9: Terminating workers...")
        coord_tools.terminate_agent(agent_id_1, reason="Test complete")
        coord_tools.terminate_agent(agent_id_2, reason="Test complete")
        log("✓ Workers terminated")

        print()
        print("=" * 60)
        print("✓ Full Coordinator Workflow Test PASSED!")
        print("=" * 60)
        return True

    finally:
        for s in sessions:
            kill_tmux_session(s)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
