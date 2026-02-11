#!/usr/bin/env python3
"""Live coordinator E2E test.

This script:
1. Creates a coordination session
2. Launches the coordinator in tmux
3. Sends it a task to accomplish using workers
4. Monitors progress

Run with: uv run python scripts/e2e/test_coordinator_live.py
"""

import os
import sys
import time
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)


def run_cmd(cmd, check=True):
    """Run a shell command."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Command failed: {cmd}")
        print(f"stderr: {result.stderr}")
    return result


def tmux_send(session, text, enter=True):
    """Send text to a tmux session."""
    # Escape special characters
    escaped = text.replace("'", "'\"'\"'")
    cmd = f"tmux send-keys -t {session} '{escaped}'"
    if enter:
        cmd += " Enter"
    run_cmd(cmd, check=False)


def tmux_capture(session, lines=50):
    """Capture tmux pane content."""
    result = run_cmd(f"tmux capture-pane -t {session} -p -S -{lines}", check=False)
    return result.stdout


def main():
    print("=" * 70)
    print("Live Coordinator E2E Test")
    print("=" * 70)
    print()

    session_name = "coord-live-test"
    silica_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    # Kill existing session
    run_cmd(f"tmux kill-session -t {session_name}", check=False)

    # The task we want the coordinator to accomplish
    task = """I need you to coordinate workers to accomplish this task:

Create two simple Python utility functions:
1. A function called `is_prime(n)` that checks if a number is prime
2. A function called `fibonacci(n)` that returns the nth fibonacci number

Spawn TWO separate workers - one for each function. Have them implement the functions
and report back. Once both workers complete, summarize what was created.

IMPORTANT: You are the COORDINATOR. Do NOT implement the functions yourself.
Spawn workers and delegate the implementation to them. Your job is to:
1. spawn_agent for worker 1 (prime checker)
2. spawn_agent for worker 2 (fibonacci) 
3. Wait for them to be IDLE
4. Assign tasks with message_agent
5. Poll for results
6. Report back to me what they created

Start now by spawning the first worker."""

    log("Starting coordinator in tmux...")

    # Start coordinator
    cmd = f"cd {silica_dir} && uv run silica coordinator new --name 'Live E2E Test'"
    run_cmd(f"tmux new-session -d -s {session_name} '{cmd}'")

    log(f"Coordinator started in tmux session: {session_name}")
    log("Waiting for coordinator to initialize...")

    # Wait for coordinator to be ready (look for the prompt)
    ready = False
    for i in range(30):
        time.sleep(2)
        output = tmux_capture(session_name)
        if (
            "What would you like to coordinate?" in output
            or "ready to help" in output.lower()
        ):
            ready = True
            break
        if "Coordinator Agent Active" in output:
            log("Coordinator agent active, waiting for prompt...")

    if not ready:
        log("WARNING: Coordinator may not be fully ready, proceeding anyway...")
        log("Last output:")
        print(tmux_capture(session_name, lines=30))
    else:
        log("✓ Coordinator ready!")

    # Send the task
    log("Sending task to coordinator...")
    time.sleep(2)
    tmux_send(session_name, task)

    log("")
    log("=" * 70)
    log("Task sent! The coordinator should now:")
    log("  1. Spawn worker agents")
    log("  2. Assign tasks to workers")
    log("  3. Monitor progress")
    log("  4. Report results")
    log("=" * 70)
    log("")
    log(f"Watch progress: tmux attach -t {session_name}")
    log(f"Kill session:   tmux kill-session -t {session_name}")
    log("")
    log("Monitoring for 5 minutes...")

    # Monitor for a while
    start_time = time.time()
    max_duration = 300  # 5 minutes
    last_output_len = 0

    spawn_count = 0
    task_assigned = False
    results_received = False

    while time.time() - start_time < max_duration:
        time.sleep(10)
        output = tmux_capture(session_name, lines=100)

        # Check for progress indicators
        if "spawn_agent" in output.lower():
            new_spawns = output.lower().count("spawn_agent")
            if new_spawns > spawn_count:
                spawn_count = new_spawns
                log(f"✓ Detected spawn_agent call (count: {spawn_count})")

        if "message_agent" in output.lower() and not task_assigned:
            task_assigned = True
            log("✓ Detected task assignment via message_agent")

        if "result" in output.lower() and "success" in output.lower():
            if not results_received:
                results_received = True
                log("✓ Detected task results")

        # Print new output
        if len(output) > last_output_len:
            new_content = output[-(len(output) - last_output_len) :]
            if new_content.strip():
                elapsed = int(time.time() - start_time)
                log(f"[+{elapsed}s] New activity detected")
            last_output_len = len(output)

        # Check if coordinator seems done
        if spawn_count >= 2 and results_received:
            log("")
            log("=" * 70)
            log("✓ Coordinator appears to have completed the task!")
            log("=" * 70)
            break

    # Final status
    log("")
    log("Final session output (last 50 lines):")
    log("-" * 70)
    print(tmux_capture(session_name, lines=50))
    log("-" * 70)

    log("")
    log("Test monitoring complete.")
    log(f"Session '{session_name}' is still running.")
    log(f"Attach with: tmux attach -t {session_name}")


if __name__ == "__main__":
    main()
