# UV Cache and Package Upgrade for Remote Workspaces

## Overview

When creating remote workspaces, silica ensures that the latest version of `pysilica` is installed from PyPI by clearing UV's cache and upgrading dependencies during deployment.

## Problem Addressed

Previously, when creating a remote workspace using `silica remote create`, the deployed environment might use a cached version of `pysilica` from UV's cache rather than fetching the latest version from PyPI. This could result in:

- Outdated silica features on remote workspaces
- Inconsistent behavior between local and remote environments
- Missing bug fixes or security updates

## Solution

The `Procfile` template used for Piku deployment has been modified to ensure fresh package installation:

```procfile
web: uv cache clean pysilica && uv sync --upgrade && uv run silica remote antennae --port $PORT
```

### Command Breakdown

1. **`uv cache clean pysilica`**: Removes any cached versions of the `pysilica` package from UV's cache
2. **`uv sync --upgrade`**: Synchronizes dependencies and upgrades to the latest available versions
3. **`uv run silica remote antennae --port $PORT`**: Starts the antennae server with the freshly installed packages

## Benefits

- **Always Latest**: Remote workspaces always use the most recent version of silica from PyPI
- **Consistent Environments**: All remotes run the same version, making debugging easier
- **Automatic Updates**: When redeploying, the latest version is automatically installed
- **No Manual Intervention**: Developers don't need to manually clear caches or force upgrades

## Performance Considerations

The cache clearing and upgrade process adds a small amount of time to deployment startup (typically 5-15 seconds). This is a reasonable trade-off for ensuring version consistency and avoiding stale packages.

If you have a slow network connection or need faster startup times for development, you can temporarily modify your local copy of the Procfile, but this is not recommended for production deployments.

## Testing

The implementation includes comprehensive tests to verify:

- Cache clean command is present in Procfile
- Sync with upgrade flag is present
- Commands are executed in the correct order
- Shell chaining (`&&`) is used properly to ensure all commands succeed

Run the tests with:

```bash
pytest tests/remote/test_procfile_upgrade.py -v
```

## Related Components

- **Template**: `silica/remote/utils/templates/Procfile`
- **Tests**: `tests/remote/test_procfile_upgrade.py`
- **Workspace Environment**: `silica/remote/cli/commands/workspace_environment.py` (contains similar logic for manual setup)

## Backward Compatibility

This change is fully backward compatible. Existing remote workspaces will automatically adopt this behavior on their next deployment or restart.

## Manual Cache Clearing

If you need to manually clear the UV cache on an existing remote workspace, you can run:

```bash
silica remote tell -w <workspace> "run this command: uv cache clean pysilica && uv sync --upgrade"
```

Or connect to the workspace and run it directly:

```bash
# SSH into the piku server
ssh piku@your-server

# Navigate to the app directory
cd ~/.piku/apps/<workspace>-<project>

# Clear cache and upgrade
uv cache clean pysilica
uv sync --upgrade

# Restart the app
piku restart <workspace>-<project>
```
