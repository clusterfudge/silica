"""Example usage of Silica utility functions."""

from silica.utils.piku import run_in_silica_dir, run_piku_in_silica, get_app_name


def example_silica_commands():
    """Examples of using the silica utility functions."""

    print("Example 1: Running a generic command in the .silica directory")
    result = run_in_silica_dir("ls -la", capture_output=True)
    print(f"Directory contents:\n{result.stdout}")

    print("\nExample 2: Running a direct Piku command")
    # Get the app name for the current repository
    app_name = get_app_name()
    workspace_name = "agent"  # Default workspace name
    result = run_piku_in_silica(
        f"status {app_name}", workspace_name=workspace_name, capture_output=True
    )
    print(f"App status:\n{result.stdout}")

    print("\nExample 3: Running a command through Piku shell")
    result = run_piku_in_silica(
        "ls -la /home/piku/apps",
        workspace_name=workspace_name,
        use_shell_pipe=True,
        capture_output=True,
    )
    print(f"Piku apps directory contents:\n{result.stdout}")

    print("\nExample 3a: Running a command with explicit workspace")
    result = run_piku_in_silica(
        f"status {app_name}", workspace_name="production", capture_output=True
    )
    print(f"App status on production workspace:\n{result.stdout}")

    # More complex example - run a series of commands
    print("\nExample 4: Running multiple commands")
    try:
        # First, check if we need to deploy
        deploy_needed = False

        # Default workspace name
        workspace_name = "agent"

        # Get the current status
        status_result = run_piku_in_silica(
            f"status {app_name}", workspace_name=workspace_name, capture_output=True
        )

        if "not deployed" in status_result.stdout:
            deploy_needed = True
            print("App needs to be deployed first")

            # Deploy using git push inside the .silica directory
            deploy_result = run_in_silica_dir("git push piku main", capture_output=True)
            print(f"Deploy result: {deploy_result.returncode}")

        # Wait a moment and check status again
        if deploy_needed:
            import time

            time.sleep(2)

        # Check logs
        logs_result = run_piku_in_silica(
            f"logs {app_name} 10", workspace_name=workspace_name, capture_output=True
        )
        print(f"Recent logs:\n{logs_result.stdout}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    example_silica_commands()
