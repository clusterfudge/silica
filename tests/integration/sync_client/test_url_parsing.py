"""Test URL parsing with FastAPI route."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()


@app.put("/blob-v1/{namespace:path}/{path:path}")
def write_blob_v1(namespace: str, path: str):
    return {"namespace": namespace, "path": path, "version": "v1"}


@app.put("/blob-v2/{namespace}/{path:path}")
def write_blob_v2(namespace: str, path: str):
    return {"namespace": namespace, "path": path, "version": "v2"}


@app.put("/blob-v3/{full_path:path}")
def write_blob_v3(full_path: str):
    # Manually parse namespace and path
    # This doesn't work because FastAPI decodes URLs before routing
    from urllib.parse import unquote

    parts = full_path.split("/", 1)
    namespace = unquote(parts[0]) if parts else ""
    path = unquote(parts[1]) if len(parts) > 1 else ""
    return {"namespace": namespace, "path": path, "version": "v3"}


client = TestClient(app)


def test_url_parsing_v1():
    # Test original pattern with two :path converters
    response = client.put("/blob-v1/test-xxx%2Fmemory/projects%2Fproject1%2Fnotes.md")
    print(f"V1 Response: {response.json()}")

    # This will fail - FastAPI greedily matches namespace
    assert response.json()["namespace"] == "test-xxx/memory/projects/project1"
    assert response.json()["path"] == "notes.md"


def test_url_parsing_v2():
    # Test with only path having :path converter
    response = client.put("/blob-v2/test-xxx%2Fmemory/projects%2Fproject1%2Fnotes.md")
    print(f"V2 Response: {response.json()}")

    # This doesn't work - splits at first / even if encoded
    assert response.json()["namespace"] == "test-xxx"
    assert response.json()["path"] == "memory/projects/project1/notes.md"


def test_url_parsing_v3():
    # Test with manual parsing of single path parameter
    response = client.put("/blob-v3/test-xxx%2Fmemory/projects%2Fproject1%2Fnotes.md")
    print(f"V3 Response: {response.json()}")

    # This should work!
    assert response.json()["namespace"] == "test-xxx/memory"
    assert response.json()["path"] == "projects/project1/notes.md"
