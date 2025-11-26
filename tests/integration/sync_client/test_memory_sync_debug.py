"""Debug memory sync test."""


def test_sync_memory_directory_structure_debug(
    memory_sync_engine, create_local_files, temp_persona_dir
):
    """Test syncing nested directory structure."""
    create_local_files(
        {
            "memory/projects/alpha/notes.md": "Alpha notes",
            "memory/projects/alpha/tasks.md": "Alpha tasks",
            "memory/projects/beta/notes.md": "Beta notes",
            "memory/reference/docs/guide.md": "Guide",
            "memory/reference/docs/api.md": "API",
        }
    )

    # First sync - upload
    plan = memory_sync_engine.analyze_sync_operations()
    print("\n=== Upload Plan ===")
    print(f"Upload: {len(plan.upload)}")
    for op in plan.upload:
        print(f"  - {op.path}")

    result = memory_sync_engine.execute_sync(plan, show_progress=False)
    print("\n=== Upload Result ===")
    print(f"Succeeded: {len(result.succeeded)}")
    print(f"Failed: {len(result.failed)}")

    assert result.success_rate == 100.0

    # Verify remote structure matches
    remote_index = memory_sync_engine.client.get_sync_index(
        memory_sync_engine.config.namespace
    )

    print("\n=== Remote Index ===")
    print(f"Files: {len(remote_index.files)}")
    for path in sorted(remote_index.files.keys()):
        print(f"  - {path}")

    expected_paths = [
        "projects/alpha/notes.md",
        "projects/alpha/tasks.md",
        "projects/beta/notes.md",
        "reference/docs/guide.md",
        "reference/docs/api.md",
        "persona.md",
    ]

    for path in expected_paths:
        assert path in remote_index.files, f"Missing: {path}"

    # Clean environment and download
    print("\n=== Cleaning Local Files ===")
    for file in temp_persona_dir.rglob("*.md"):
        if file.name != "persona.md":
            print(f"  Deleting: {file}")
            file.unlink()

    # Analyze what needs to be downloaded
    plan = memory_sync_engine.analyze_sync_operations()
    print("\n=== Download Plan ===")
    print(f"Download: {len(plan.download)}")
    for op in plan.download:
        print(f"  - {op.path}")

    result = memory_sync_engine.execute_sync(plan, show_progress=False)
    print("\n=== Download Result ===")
    print(f"Succeeded: {len(result.succeeded)}")
    for op in result.succeeded:
        print(f"  - {op.path}")
    print(f"Failed: {len(result.failed)}")
    for op in result.failed:
        print(f"  - {op.path}")

    # Verify directory structure recreated
    print("\n=== Checking Downloaded Files ===")
    expected_file = temp_persona_dir / "memory/projects/alpha/notes.md"
    print(f"Expected file: {expected_file}")
    print(f"Exists: {expected_file.exists()}")

    if not expected_file.exists():
        # List what files do exist
        print("\nFiles in memory dir:")
        memory_dir = temp_persona_dir / "memory"
        if memory_dir.exists():
            for file in memory_dir.rglob("*.md"):
                print(f"  - {file.relative_to(memory_dir)}")
        else:
            print("  (memory dir doesn't exist)")

    assert expected_file.exists()
