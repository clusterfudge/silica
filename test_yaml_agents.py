#!/usr/bin/env python3
"""Test script for the new YAML-based agent system."""

from silica.utils.agent_yaml import (
    load_agent_config,
    list_built_in_agents,
    generate_launch_command,
)
from silica.utils.yaml_agents import (
    validate_agent_type,
    get_default_workspace_agent_config,
    generate_agent_runner_script,
)


def test_yaml_system():
    """Test the YAML-based agent system."""
    print("=== Testing YAML-based Agent System ===\n")

    # Test 1: List built-in agents
    print("1. Testing agent discovery:")
    agents = list_built_in_agents()
    print(f"   Found agents: {agents}")
    assert len(agents) > 0, "Should find at least one agent"
    print("   ✓ Agent discovery works\n")

    # Test 2: Load agent configurations
    print("2. Testing agent configuration loading:")
    for agent_name in agents:
        config = load_agent_config(agent_name)
        assert config is not None, f"Should load config for {agent_name}"
        assert config.name == agent_name, f"Name should match for {agent_name}"
        assert config.description, f"Should have description for {agent_name}"
        assert config.launch_command, f"Should have launch command for {agent_name}"
        print(f"   ✓ {agent_name}: {config.description}")
    print("   ✓ All agent configs loaded successfully\n")

    # Test 3: Test agent validation
    print("3. Testing agent validation:")
    assert validate_agent_type("hdev"), "hdev should be valid"
    assert not validate_agent_type("nonexistent"), "nonexistent should be invalid"
    print("   ✓ Agent validation works\n")

    # Test 4: Test workspace configuration generation
    print("4. Testing workspace configuration:")
    for agent_name in agents:
        workspace_config = get_default_workspace_agent_config(agent_name)
        assert workspace_config["agent_type"] == agent_name
        assert "agent_config" in workspace_config
        print(f"   ✓ {agent_name} workspace config generated")
    print("   ✓ Workspace configuration generation works\n")

    # Test 5: Test launch command generation
    print("5. Testing launch command generation:")
    for agent_name in agents:
        config = load_agent_config(agent_name)
        workspace_config = {"agent_config": {"flags": [], "args": {}}}
        command = generate_launch_command(config, workspace_config)
        assert command.startswith(
            "uv run"
        ), f"Command should start with 'uv run' for {agent_name}"
        print(f"   ✓ {agent_name}: {command}")
    print("   ✓ Launch command generation works\n")

    # Test 6: Test agent runner script generation
    print("6. Testing agent runner script generation:")
    test_workspace = "test-workspace"
    test_config = get_default_workspace_agent_config("hdev")
    script = generate_agent_runner_script(test_workspace, test_config)
    assert "#!/usr/bin/env python3" in script, "Should be a Python script"
    assert test_workspace in script, "Should include workspace name"
    assert "hdev" in script, "Should include agent type"
    print("   ✓ Agent runner script generation works\n")

    print("=== All tests passed! ===")


if __name__ == "__main__":
    test_yaml_system()
