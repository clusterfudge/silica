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
