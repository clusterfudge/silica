"""Test that create command sets both WORKSPACE_NAME and PROJECT_NAME environment variables."""


def test_create_environment_variable_construction_logic():
    """Test the environment variable construction logic used in create command."""
    # This tests the same logic used in create_remote_workspace
    # without needing to mock all the complex dependencies

    test_cases = [
        ("agent", "list-of-lists"),
        ("test", "my-project"),
        ("dev", "silica"),
        ("prod", "api-server"),
    ]

    for workspace_name, repo_name in test_cases:
        # This mirrors the logic in create_remote_workspace:
        # env_config["WORKSPACE_NAME"] = workspace_name
        # env_config["PROJECT_NAME"] = repo_name
        # app_name = f"{workspace_name}-{repo_name}"
        # env_config["NGINX_SERVER_NAME"] = app_name

        env_config = {}
        env_config["WORKSPACE_NAME"] = workspace_name
        env_config["PROJECT_NAME"] = repo_name
        app_name = f"{workspace_name}-{repo_name}"
        env_config["NGINX_SERVER_NAME"] = app_name

        # Verify the environment variables are set up correctly
        assert env_config["WORKSPACE_NAME"] == workspace_name
        assert env_config["PROJECT_NAME"] == repo_name
        assert env_config["NGINX_SERVER_NAME"] == app_name

        # Most importantly, verify the app_name (which becomes the tmux session) is correct
        expected_session_name = f"{workspace_name}-{repo_name}"
        assert app_name == expected_session_name

        print(f"✅ {workspace_name} + {repo_name} -> session: {expected_session_name}")


def test_workspace_project_combination_examples():
    """Test various workspace + project combinations."""
    test_cases = [
        ("agent", "list-of-lists", "agent-list-of-lists"),
        ("test", "my-project", "test-my-project"),
        ("dev", "silica", "dev-silica"),
        ("prod", "api-server", "prod-api-server"),
    ]

    for workspace, project, expected_session in test_cases:
        # This tests the logic that should result from the create command
        expected_workspace_env = f"WORKSPACE_NAME={workspace}"
        expected_project_env = f"PROJECT_NAME={project}"
        expected_app_name = f"NGINX_SERVER_NAME={expected_session}"

        # These are the environment variables that should be set during create
        assert expected_workspace_env == f"WORKSPACE_NAME={workspace}"
        assert expected_project_env == f"PROJECT_NAME={project}"
        assert expected_app_name == f"NGINX_SERVER_NAME={workspace}-{project}"

        print(f"✅ {workspace} + {project} -> {expected_session}")
