"""Test namespace-first route pattern."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from urllib.parse import quote

app = FastAPI()


@app.put("/{namespace:path}/blob/{entry:path}")
def write_blob(namespace: str, entry: str):
    return {"namespace": namespace, "entry": entry}


client = TestClient(app)


@pytest.mark.integration
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


@pytest.mark.integration
def test_with_unencoded_separator():
    """Test that /blob/ acts as a reliable separator even with slashes in namespace."""
    # This verifies the route pattern works correctly
    namespace = "personas/default/memory"
    entry = "notes.md"

    encoded_ns = quote(namespace, safe="")
    url = f"/{encoded_ns}/blob/{entry}"

    response = client.put(url)

    assert response.json()["namespace"] == namespace
    assert response.json()["entry"] == entry
