#!/usr/bin/env python3
# Remove the env-status command from agents.py

# Read the file
with open("silica/cli/commands/agents.py", "r") as f:
    content = f.read()

# Find the start of the env-status command
env_status_start = content.find('@agents.command("env-status")')
if env_status_start != -1:
    # Remove everything from that point to the end
    new_content = content[:env_status_start].rstrip() + "\n"

    # Write the modified file
    with open("silica/cli/commands/agents.py", "w") as f:
        f.write(new_content)

    print("Removed env-status command successfully")
else:
    print("env-status command not found")
