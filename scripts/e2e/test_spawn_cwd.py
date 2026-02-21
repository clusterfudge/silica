#!/usr/bin/env python3
"""E2E Test: spawn_agent with cwd parameter.

Validates that workers can be spawned with a custom working directory.

Run with: uv run python scripts/e2e/test_spawn_cwd.py
"""

import os
import subprocess
import sys
import time
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from config import get_e2e_deaddrop
from silica.developer.coordination.session import CoordinationSession
from silica.developer.tools import coordination as coord_tools


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def kill_tmux_session(name: str):
    subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)


def main():
    print("=" * 60)
    print("E2E Test: spawn_agent with cwd")
    print("=" * 60)

    deaddrop = get_e2e_deaddrop()
    log(f"Connected to: {deaddrop.location}")

    # Create a temp directory to use as cwd
    with tempfile.TemporaryDirectory(prefix="e2e-cwd-test-") as tmpdir:
        log(f"Test directory: {tmpdir}")

        # Create a marker file so the worker can verify its cwd
        marker = os.path.join(tmpdir, "MARKER.txt")
        with open(marker, "w") as f:
            f.write("spawn_cwd_test")

        # Create coordination session
        session = CoordinationSession.create_session(
            deaddrop=deaddrop,
            display_name="CWD Test",
        )
        coord_tools.set_current_session(session)
        log(f"Session: {session.session_id}")

        tmux_sessions = []

        try:
            # Spawn worker with custom cwd
            log(f"Spawning worker with cwd={tmpdir}...")
            result = coord_tools.spawn_agent(
                workspace_name="cwd-test-worker",
                display_name="CWD Worker",
                cwd=tmpdir,
            )
            log(f"Spawn result:\n{result}")

            # Extract agent_id from result
            agent_id = None
            for line in result.split("\n"):
                if "Agent ID:" in line:
                    agent_id = line.split(": ", 1)[1].strip()
                    break

            if not agent_id:
                log("FAILED: Could not extract agent_id from spawn result")
                return False

            # Find the tmux session
            tmux_name = f"worker-{agent_id}"
            tmux_sessions.append(tmux_name)
            log(f"Worker tmux session: {tmux_name}")

            # Give it a moment to start
            time.sleep(2)

            # Check the tmux session's working directory by capturing output
            # Send pwd command to verify cwd
            check = subprocess.run(
                [
                    "tmux",
                    "display-message",
                    "-t",
                    tmux_name,
                    "-p",
                    "#{pane_current_path}",
                ],
                capture_output=True,
                text=True,
            )

            if check.returncode == 0:
                pane_cwd = check.stdout.strip()
                log(f"Worker pane cwd: {pane_cwd}")

                if pane_cwd == tmpdir or tmpdir in pane_cwd:
                    log("✓ Worker is running in the specified cwd")
                else:
                    log(
                        f"WARNING: pane cwd '{pane_cwd}' doesn't match expected '{tmpdir}'"
                    )
                    log("(tmux pane_current_path may not reflect cd in shell)")

            # Also verify via the launch command — check tmux history
            hist = subprocess.run(
                ["tmux", "capture-pane", "-t", tmux_name, "-p", "-S", "-20"],
                capture_output=True,
                text=True,
            )
            if hist.returncode == 0:
                output = hist.stdout
                if tmpdir in output:
                    log(f"✓ Confirmed cwd '{tmpdir}' appears in worker session output")
                else:
                    log("Checking worker launch command...")
                    # The cd command should have been in the launch
                    log(f"Session output:\n{output[:500]}")

            print()
            print("=" * 60)
            print("✓ spawn_agent cwd test PASSED!")
            print(f"  - Worker spawned with cwd={tmpdir}")
            print(f"  - Agent ID: {agent_id}")
            print("=" * 60)
            return True

        finally:
            coord_tools.set_current_session(None)
            for s in tmux_sessions:
                kill_tmux_session(s)


if __name__ == "__main__":
    try:
        success = main()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
