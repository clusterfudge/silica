"""Debug test for nested upload issue."""


def test_upload_nested_debug(memory_sync_engine, create_local_files):
    """Debug nested directory upload."""
    create_local_files(
        {
            "memory/projects/project1/notes.md": "Project 1 notes",
            "memory/projects/project2/notes.md": "Project 2 notes",
            "memory/archive/old/data.md": "Archived data",
        }
    )

    plan = memory_sync_engine.analyze_sync_operations()

    print("\n=== Sync Plan ===")
    print(f"Uploads: {len(plan.upload)}")
    for op in plan.upload:
        print(f"  - {op.path}: {op.reason}")

    result = memory_sync_engine.execute_sync(plan, show_progress=False)

    print("\n=== Sync Result ===")
    print(f"Succeeded: {len(result.succeeded)}")
    for op in result.succeeded:
        print(f"  - {op.path}")
    print(f"Failed: {len(result.failed)}")
    for op in result.failed:
        print(f"  - {op.path}")
    print(f"Success rate: {result.success_rate}%")

    # Get remote index
    remote_index = memory_sync_engine.client.get_sync_index(
        memory_sync_engine.config.namespace
    )

    print("\n=== Remote Index ===")
    print(f"Files: {len(remote_index.files)}")
    for path in sorted(remote_index.files.keys()):
        print(f"  - {path}")
