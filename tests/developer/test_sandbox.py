import os
import tempfile
import pytest

from silica.developer.sandbox import Sandbox, SandboxMode


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


def test_sandbox_init(temp_dir):
    # Test initializing Sandbox with different modes
    sandbox = Sandbox(temp_dir, SandboxMode.REQUEST_EVERY_TIME)
    assert sandbox.permissions_cache is None

    sandbox = Sandbox(temp_dir, SandboxMode.REMEMBER_PER_RESOURCE)
    assert isinstance(sandbox.permissions_cache, dict)

    sandbox = Sandbox(temp_dir, SandboxMode.REMEMBER_ALL)
    assert isinstance(sandbox.permissions_cache, dict)

    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)
    assert sandbox.permissions_cache is None


def test_gitignore_loading(temp_dir):
    with open(os.path.join(temp_dir, ".gitignore"), "w") as f:
        f.write("ignored_dir/\n*.txt")

    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)

    os.makedirs(os.path.join(temp_dir, "ignored_dir"))
    os.makedirs(os.path.join(temp_dir, "included_dir"))

    with open(os.path.join(temp_dir, "ignored_dir/file.txt"), "w") as f:
        f.write("text")
    with open(os.path.join(temp_dir, "included_dir/file.py"), "w") as f:
        f.write("code")

    listing = sandbox.get_directory_listing()
    assert "ignored_dir/file.txt" not in listing
    assert "included_dir/file.py" in listing


def test_permissions(temp_dir, monkeypatch):
    sandbox = Sandbox(temp_dir, SandboxMode.REQUEST_EVERY_TIME)

    monkeypatch.setattr("builtins.input", lambda _: "y")
    assert sandbox.check_permissions("read", "file.txt")

    monkeypatch.setattr("builtins.input", lambda _: "n")
    assert not sandbox.check_permissions("write", "file.txt")

    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)
    assert sandbox.check_permissions("any_action", "any_resource")


async def test_read_write_file(temp_dir):
    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)

    file_path = "test.txt"
    content = "test content"

    sandbox.write_file(file_path, content)
    result = await sandbox.read_file(file_path)
    assert result == content

    with pytest.raises(ValueError):
        await sandbox.read_file("../outside_sandbox.txt")

    with pytest.raises(FileNotFoundError):
        await sandbox.read_file("nonexistent.txt")


def test_create_file(temp_dir):
    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)

    file_path = "new_file.txt"
    sandbox.create_file(file_path)
    assert os.path.exists(os.path.join(temp_dir, file_path))

    with pytest.raises(FileExistsError):
        sandbox.create_file(file_path)

    with pytest.raises(ValueError):
        sandbox.create_file("../outside_sandbox.txt")


def test_get_directory_listing(temp_dir):
    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)

    # Create a directory structure
    os.makedirs(os.path.join(temp_dir, "dir1/subdir"))
    os.makedirs(os.path.join(temp_dir, "dir2"))

    with open(os.path.join(temp_dir, "file1.txt"), "w") as f:
        f.write("content")
    with open(os.path.join(temp_dir, "dir1/file2.txt"), "w") as f:
        f.write("content")
    with open(os.path.join(temp_dir, "dir1/subdir/file3.txt"), "w") as f:
        f.write("content")
    with open(os.path.join(temp_dir, "dir2/file4.txt"), "w") as f:
        f.write("content")

    # Test current behavior (listing all files)
    listing = sandbox.get_directory_listing()
    assert set(listing) == {
        "file1.txt",
        "dir1/file2.txt",
        "dir1/subdir/file3.txt",
        "dir2/file4.txt",
    }

    # Test desired behavior (listing files only under a specific path)
    listing = sandbox.get_directory_listing("dir1")
    assert set(listing) == {"file2.txt", "subdir/file3.txt"}

    listing = sandbox.get_directory_listing("dir2")
    assert set(listing) == {"file4.txt"}

    listing = sandbox.get_directory_listing("nonexistent")
    assert listing == []


def test_get_directory_listing_follows_symlinks(temp_dir):
    """Test that directory listing follows symbolic links to directories."""
    sandbox = Sandbox(temp_dir, SandboxMode.ALLOW_ALL)

    # Create a separate directory outside the temp_dir structure
    # (but still within temp filesystem for test isolation)
    external_dir = tempfile.mkdtemp()
    try:
        # Create files in the external directory
        os.makedirs(os.path.join(external_dir, "subdir"))
        with open(os.path.join(external_dir, "external_file.py"), "w") as f:
            f.write("# external file")
        with open(os.path.join(external_dir, "subdir/nested_file.py"), "w") as f:
            f.write("# nested external file")

        # Create a symlink inside the sandbox pointing to the external directory
        symlink_path = os.path.join(temp_dir, "linked_project")
        os.symlink(external_dir, symlink_path)

        # Also create a regular directory for comparison
        os.makedirs(os.path.join(temp_dir, "regular_dir"))
        with open(os.path.join(temp_dir, "regular_dir/regular_file.py"), "w") as f:
            f.write("# regular file")

        # Verify the symlink exists and is a directory
        assert os.path.islink(symlink_path)
        assert os.path.isdir(symlink_path)

        # Get directory listing - should follow symlinks
        listing = sandbox.get_directory_listing()

        # Should include files from regular directory
        assert "regular_dir/regular_file.py" in listing

        # Should also include files from symlinked directory
        assert "linked_project/external_file.py" in listing
        assert "linked_project/subdir/nested_file.py" in listing

        # Test listing within the symlinked directory specifically
        linked_listing = sandbox.get_directory_listing("linked_project")
        assert "external_file.py" in linked_listing
        assert "subdir/nested_file.py" in linked_listing

    finally:
        # Clean up external directory
        import shutil

        shutil.rmtree(external_dir)
