# Plane.so Cache System

This document explains the cache system used for Plane.so integration.

## Overview

The cache system stores Plane.so entity data like states, priorities, and workspace members locally to:

1. Reduce API calls
2. Enable mapping between state/priority names and IDs
3. Allow offline operation with previously fetched data
4. Make state transitions more reliable by using the correct state IDs

## Cache Structure

The cache is stored in `~/.cache/hdev/plane.so/` with each entity type for each project in its own file:

```
~/.cache/hdev/plane.so/
  workspace-slug_project-id_states.json
  workspace-slug_project-id_priorities.json
  workspace-slug_project-id_members.json
  ...
```

Each cache file contains:

1. Raw results directly from the API
2. Lookup maps for converting between names and IDs
3. Additional metadata like colors and descriptions

## Using the Cache

The cache is used automatically by the Plane.so client and issue tools. When you:

1. View issue details - The system uses the cache to look up state, priority names, and user information
2. Update an issue state - The system converts readable state names to the required IDs
3. Create issues - The system validates priorities against known values
4. Assign issues - The system can look up users by name or email

## Refreshing the Cache

The cache is refreshed:

1. Automatically when it's older than 24 hours
2. On demand using the `refresh_plane_cache` tool or script
3. When lookups fail (fallback to API)

To manually refresh the cache:

```
# Using the tool in a conversation
@tool refresh_plane_cache

# Using the script
./refresh_plane_cache.py
```

## Implementation Details

The cache system is implemented in:

- `heare/developer/clients/plane_cache.py` - Core caching functionality
- Functions for interacting with the cache are integrated in the issue tools

Key functions:

- `fetch_and_cache_states()` - Fetches states from the API and stores them in the cache
- `fetch_and_cache_priorities()` - Fetches priorities and stores them in the cache
- `fetch_and_cache_members()` - Fetches workspace members and stores them in the cache
- `get_state_id_by_name()` - Converts a state name to its ID using the cache
- `get_state_name_by_id()` - Converts a state ID to its name using the cache
- `get_member_by_id()` - Gets member details by their ID
- `get_member_by_email()` - Gets member details by their email
- `get_member_by_name()` - Gets member details by their name
- `refresh_all_caches()` - Refreshes all caches for a project
- `clear_cache()` - Clears the cache

## Troubleshooting

If you're having issues with state transitions or seeing "Unknown" states:

1. Run `./refresh_plane_cache.py` to refresh the cache
2. Check the cache files in `~/.cache/hdev/plane.so/` to verify they contain the expected data
3. Verify your Plane.so API key is still valid