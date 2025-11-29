"""Test namespace-first route pattern."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.parse import quote

app = FastAPI()


@app.put("/{namespace:path}/blob/{entry:path}")
def write_blob(namespace: str, entry: str):
    return {"namespace": namespace, "entry": entry}


client = TestClient(app)


def test_namespace_first_pattern():
    """Test with namespace first, then /blob/ separator, then entry path."""
    namespace = "test-xxx/memory"
    entry = "projects/project1/notes.md"

    # URL-encode both parts
    encoded_ns = quote(namespace, safe="")
    encoded_entry = quote(entry, safe="")

    # Construct URL: /{namespace}/blob/{entry}
    url = f"/{encoded_ns}/blob/{encoded_entry}"
    print(f"URL: {url}")

    response = client.put(url)
    print(f"Response: {response.json()}")

    assert response.json()["namespace"] == namespace
    assert response.json()["entry"] == entry


def test_with_unencoded_separator():
    """Test if /blob/ acts as a clear separator."""
    namespace = "test-xxx/memory"
    entry = "projects/project1/notes.md"

    # URL-encode the namespace and entry, use unencoded /blob/ as separator
    encoded_ns = quote(namespace, safe="")
    encoded_entry = quote(entry, safe="")

    url = f"/{encoded_ns}/blob/{encoded_entry}"
    print(f"\nURL with /blob/ separator: {url}")

    response = client.put(url)
    print(f"Response: {response.json()}")

    assert response.json()["namespace"] == namespace
    assert response.json()["entry"] == entry
