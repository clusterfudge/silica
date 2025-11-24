"""Test final URL strategy."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.parse import quote

app = FastAPI()


@app.put("/blob/{namespace:path}")
def write_blob(namespace: str):
    # Namespace includes both namespace and path
    # Parse by splitting at LAST /
    if "/" in namespace:
        parts = namespace.rsplit("/", 1)  # Split from right
        actual_namespace = parts[0]
        path = parts[1]
    else:
        actual_namespace = namespace
        path = ""

    return {"namespace": actual_namespace, "path": path}


client = TestClient(app)


def test_with_unencoded_separator():
    # URL-encode namespace and path separately, but use unencoded / between them
    namespace = "test-xxx/memory"
    path = "projects/project1/notes.md"

    encoded_ns = quote(namespace, safe="")
    encoded_path = quote(path, safe="")

    # Use unencoded / as separator
    url = f"/blob/{encoded_ns}/{encoded_path}"
    print(f"URL: {url}")

    response = client.put(url)
    print(f"Response: {response.json()}")

    assert response.json()["namespace"] == namespace
    assert response.json()["path"] == path
