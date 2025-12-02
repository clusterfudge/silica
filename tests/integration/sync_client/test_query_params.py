"""Test using query parameters for path."""

from fastapi import FastAPI, Query
from fastapi.testclient import TestClient
from urllib.parse import quote

app = FastAPI()


@app.put("/blob/{namespace:path}")
def write_blob(namespace: str, path: str = Query(...)):
    return {"namespace": namespace, "path": path}


client = TestClient(app)


def test_with_query_param():
    namespace = "test-xxx/memory"
    path = "projects/project1/notes.md"

    encoded_ns = quote(namespace, safe="")
    encoded_path = quote(path, safe="")

    url = f"/blob/{encoded_ns}?path={encoded_path}"
    print(f"URL: {url}")

    response = client.put(url)
    print(f"Response: {response.json()}")

    assert response.json()["namespace"] == namespace
    assert response.json()["path"] == path
