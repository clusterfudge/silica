"""Tests for FastAPI application endpoints."""


def test_health_check_no_auth(test_client):
    """Test health check endpoint doesn't require auth."""
    response = test_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["storage"] == "connected"


def test_read_blob_requires_auth(test_client, mock_auth_failure):
    """Test read blob requires authentication."""
    response = test_client.get("/blob/default/test.txt")

    # 403 when no auth header, 401 when invalid token
    assert response.status_code in (401, 403)


def test_read_blob_not_found(test_client, auth_headers):
    """Test reading non-existent blob."""
    response = test_client.get("/blob/default/nonexistent.txt", headers=auth_headers)

    assert response.status_code == 404


def test_write_and_read_blob(test_client, auth_headers):
    """Test writing and reading a blob."""
    content = b"Hello, World!"

    # Write blob
    write_response = test_client.put(
        "/blob/default/test/file.txt",
        content=content,
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    assert write_response.status_code == 201
    etag = write_response.headers["ETag"]
    assert etag
    assert "X-Version" in write_response.headers

    # Read blob
    read_response = test_client.get("/blob/default/test/file.txt", headers=auth_headers)

    assert read_response.status_code == 200
    assert read_response.content == content
    assert "ETag" in read_response.headers
    assert "Last-Modified" in read_response.headers
    assert "X-Version" in read_response.headers


def test_write_blob_without_content_md5(test_client, auth_headers):
    """Test writing blob with If-Match-Version but without Content-MD5."""
    content = b"Test content"

    # First write (new file) with version 0
    response1 = test_client.put(
        "/blob/default/test.txt",
        content=content,
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    assert response1.status_code == 201
    assert "X-Version" in response1.headers
    version1 = int(response1.headers["X-Version"])

    # Second write (update) with correct version
    response2 = test_client.put(
        "/blob/default/test.txt",
        content=b"Updated content",
        headers={**auth_headers, "If-Match-Version": str(version1)},
    )

    assert response2.status_code == 200
    assert "X-Version" in response2.headers


def test_write_blob_conditional_new_fails_if_exists(test_client, auth_headers):
    """Test conditional write with version 0 fails if file exists."""
    # Create file
    test_client.put(
        "/blob/default/test.txt",
        content=b"Existing content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Try to create again
    response = test_client.put(
        "/blob/default/test.txt",
        content=b"New content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    assert response.status_code == 412
    data = response.json()
    assert data["error_code"] == "PRECONDITION_FAILED"


def test_write_blob_conditional_update_success(test_client, auth_headers):
    """Test conditional update with correct version."""
    # Create file
    response1 = test_client.put(
        "/blob/default/test.txt",
        content=b"Version 1",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    version1 = int(response1.headers["X-Version"])

    # Update with correct version
    response2 = test_client.put(
        "/blob/default/test.txt",
        content=b"Version 2",
        headers={**auth_headers, "If-Match-Version": str(version1)},
    )

    assert response2.status_code == 200
    version2 = int(response2.headers["X-Version"])
    assert version2 > version1
    assert "X-Version" in response2.headers


def test_write_blob_conditional_update_fails_with_wrong_version(
    test_client, auth_headers
):
    """Test conditional update fails with incorrect version."""
    # Create file
    test_client.put(
        "/blob/default/test.txt",
        content=b"Version 1",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Try to update with wrong version
    response = test_client.put(
        "/blob/default/test.txt",
        content=b"Version 2",
        headers={**auth_headers, "If-Match-Version": "999"},
    )

    assert response.status_code == 412
    data = response.json()
    assert data["error_code"] == "PRECONDITION_FAILED"
    assert data["context"]["provided_version"] == "999"


def test_delete_blob(test_client, auth_headers):
    """Test deleting a blob."""
    # Create file
    test_client.put(
        "/blob/default/test.txt",
        content=b"To be deleted",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Delete file
    delete_response = test_client.delete("/blob/default/test.txt", headers=auth_headers)

    assert delete_response.status_code == 200

    # Verify response contains sync index
    sync_data = delete_response.json()
    assert "files" in sync_data
    assert "test.txt" in sync_data["files"]
    assert sync_data["files"]["test.txt"]["is_deleted"] is True

    # Verify file is tombstoned (404 on read)
    read_response = test_client.get("/blob/default/test.txt", headers=auth_headers)
    assert read_response.status_code == 404


def test_delete_blob_not_found(test_client, auth_headers):
    """Test deleting non-existent blob."""
    response = test_client.delete("/blob/default/nonexistent.txt", headers=auth_headers)

    assert response.status_code == 404


def test_delete_blob_conditional_success(test_client, auth_headers):
    """Test conditional delete with correct version."""
    # Create file
    write_response = test_client.put(
        "/blob/default/test.txt",
        content=b"Content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    version = write_response.headers["X-Version"]

    # Delete with correct version
    delete_response = test_client.delete(
        "/blob/default/test.txt",
        headers={**auth_headers, "If-Match-Version": version},
    )

    assert delete_response.status_code == 200

    # Verify response contains sync index
    sync_data = delete_response.json()
    assert "files" in sync_data


def test_delete_blob_conditional_fails_with_wrong_version(test_client, auth_headers):
    """Test conditional delete fails with incorrect version."""
    # Create file
    test_client.put(
        "/blob/default/test.txt",
        content=b"Content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Try to delete with wrong version
    response = test_client.delete(
        "/blob/default/test.txt",
        headers={**auth_headers, "If-Match-Version": "999"},
    )

    assert response.status_code == 412


def test_get_sync_index_empty(test_client, auth_headers):
    """Test getting sync index when no files exist."""
    response = test_client.get("/sync/default", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["files"] == {}
    assert "index_last_modified" in data
    assert "index_version" in data
    assert "index_version" in data


def test_get_sync_index_with_files(test_client, auth_headers):
    """Test getting sync index after writing files."""
    # Write files
    test_client.put(
        "/blob/default/file1.txt",
        content=b"Content 1",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    test_client.put(
        "/blob/default/file2.txt",
        content=b"Content 2",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Get sync index
    response = test_client.get("/sync/default", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 2
    assert "index_version" in data
    assert "index_version" in data

    # Check file1 metadata
    assert "file1.txt" in data["files"]
    file1_meta = data["files"]["file1.txt"]
    assert "md5" in file1_meta
    assert "last_modified" in file1_meta
    assert "size" in file1_meta
    assert file1_meta["is_deleted"] is False
    assert "version" in file1_meta


def test_get_sync_index_includes_tombstones(test_client, auth_headers):
    """Test sync index includes tombstoned files."""
    # Write and delete file
    test_client.put(
        "/blob/default/deleted.txt",
        content=b"To be deleted",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    test_client.delete("/blob/default/deleted.txt", headers=auth_headers)

    # Write active file
    test_client.put(
        "/blob/default/active.txt",
        content=b"Active content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # Get sync index
    response = test_client.get("/sync/default", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert len(data["files"]) == 2
    assert data["files"]["deleted.txt"]["is_deleted"] is True
    assert data["files"]["active.txt"]["is_deleted"] is False


def test_sync_workflow(test_client, auth_headers):
    """Test complete sync workflow."""
    # 1. Get initial sync index (empty)
    sync1 = test_client.get("/sync/default", headers=auth_headers).json()
    assert len(sync1["files"]) == 0

    # 2. Upload files
    test_client.put(
        "/blob/default/dir1/file1.txt",
        content=b"File 1 content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    test_client.put(
        "/blob/default/dir2/file2.txt",
        content=b"File 2 content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )

    # 3. Get updated sync index
    sync2 = test_client.get("/sync/default", headers=auth_headers).json()
    assert len(sync2["files"]) == 2
    file1_version = sync2["files"]["dir1/file1.txt"]["version"]

    # 4. Update a file with conditional write
    update_response = test_client.put(
        "/blob/default/dir1/file1.txt",
        content=b"Updated file 1 content",
        headers={**auth_headers, "If-Match-Version": str(file1_version)},
    )
    assert update_response.status_code == 200

    # 5. Delete a file
    test_client.delete("/blob/default/dir2/file2.txt", headers=auth_headers)

    # 6. Get final sync index
    sync3 = test_client.get("/sync/default", headers=auth_headers).json()
    assert len(sync3["files"]) == 2
    assert sync3["files"]["dir1/file1.txt"]["version"] > file1_version  # Updated
    assert sync3["files"]["dir2/file2.txt"]["is_deleted"] is True  # Deleted

    # 7. Verify reading deleted file returns 404
    read_response = test_client.get(
        "/blob/default/dir2/file2.txt", headers=auth_headers
    )
    assert read_response.status_code == 404


def test_content_type_preservation(test_client, auth_headers):
    """Test that Content-Type is preserved."""
    # Write with specific content type
    test_client.put(
        "/blob/default/test.json",
        content=b'{"key": "value"}',
        headers={
            **auth_headers,
            "If-Match-Version": "0",
            "Content-Type": "application/json",
        },
    )

    # Read and verify content type
    response = test_client.get("/blob/default/test.json", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"


def test_nested_paths(test_client, auth_headers):
    """Test deeply nested file paths."""
    path = "very/deeply/nested/path/to/file.txt"

    # Write
    write_response = test_client.put(
        f"/blob/default/{path}",
        content=b"Nested content",
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    assert write_response.status_code == 201

    # Read
    read_response = test_client.get(f"/blob/default/{path}", headers=auth_headers)
    assert read_response.status_code == 200
    assert read_response.content == b"Nested content"

    # Verify in sync index
    sync = test_client.get("/sync/default", headers=auth_headers).json()
    assert path in sync["files"]


def test_auth_failure_on_protected_endpoints(test_client, mock_auth_failure):
    """Test that all protected endpoints require valid auth."""
    endpoints = [
        ("GET", "/blob/default/test.txt"),
        ("PUT", "/blob/default/test.txt"),
        ("DELETE", "/blob/default/test.txt"),
        ("GET", "/sync/default"),
    ]

    for method, path in endpoints:
        if method == "GET":
            response = test_client.get(
                path, headers={"Authorization": "Bearer bad-token"}
            )
        elif method == "PUT":
            response = test_client.put(
                path,
                content=b"content",
                headers={"Authorization": "Bearer bad-token"},
            )
        elif method == "DELETE":
            response = test_client.delete(
                path, headers={"Authorization": "Bearer bad-token"}
            )

        assert response.status_code == 401, f"{method} {path} should require auth"


def test_namespace_isolation_api(test_client, auth_headers):
    """Test that namespaces are isolated at the API level."""
    # Create same file in two different namespaces
    content_ns1 = b"Content in namespace 1"
    content_ns2 = b"Content in namespace 2"

    # Write to namespace1
    write_response1 = test_client.put(
        "/blob/namespace1/test.txt",
        content=content_ns1,
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    assert write_response1.status_code == 201
    etag_ns1 = write_response1.headers["ETag"]

    # Write to namespace2
    write_response2 = test_client.put(
        "/blob/namespace2/test.txt",
        content=content_ns2,
        headers={**auth_headers, "If-Match-Version": "0"},
    )
    assert write_response2.status_code == 201
    etag_ns2 = write_response2.headers["ETag"]

    # Verify ETags are different (different content)
    assert etag_ns1 != etag_ns2

    # Read from namespace1
    read_response1 = test_client.get("/blob/namespace1/test.txt", headers=auth_headers)
    assert read_response1.status_code == 200
    assert read_response1.content == content_ns1

    # Read from namespace2
    read_response2 = test_client.get("/blob/namespace2/test.txt", headers=auth_headers)
    assert read_response2.status_code == 200
    assert read_response2.content == content_ns2

    # Get sync index for namespace1
    sync1 = test_client.get("/sync/namespace1", headers=auth_headers).json()
    assert len(sync1["files"]) == 1
    assert "test.txt" in sync1["files"]
    assert sync1["files"]["test.txt"]["md5"] == etag_ns1.strip('"')

    # Get sync index for namespace2
    sync2 = test_client.get("/sync/namespace2", headers=auth_headers).json()
    assert len(sync2["files"]) == 1
    assert "test.txt" in sync2["files"]
    assert sync2["files"]["test.txt"]["md5"] == etag_ns2.strip('"')

    # Delete in namespace1 should not affect namespace2
    delete_response = test_client.delete(
        "/blob/namespace1/test.txt", headers=auth_headers
    )
    assert delete_response.status_code == 200

    # Verify response contains sync index for namespace1
    sync_data = delete_response.json()
    assert "files" in sync_data

    # Verify namespace1 file is deleted
    read_after_delete = test_client.get(
        "/blob/namespace1/test.txt", headers=auth_headers
    )
    assert read_after_delete.status_code == 404

    # Verify namespace2 file still exists
    read_ns2_after = test_client.get("/blob/namespace2/test.txt", headers=auth_headers)
    assert read_ns2_after.status_code == 200
    assert read_ns2_after.content == content_ns2
