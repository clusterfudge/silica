# FastAPI Path Parameter Research Summary

## The Problem

We tried to use this route pattern:
```python
@app.put("/blob/{namespace:path}/{path:path}")
def write_blob(namespace: str, path: str):
    ...
```

With URL-encoded parameters:
```
PUT /blob/test-xxx%2Fmemory/projects%2Fproject1%2Fnotes.md
```

Expected:
- namespace: `test-xxx/memory`
- path: `projects/project1/notes.md`

Got:
- namespace: `test-xxx/memory/projects/project1` ❌
- path: `notes.md`

## Why It Doesn't Work

### 1. URL Decoding Happens First
From [Stack Overflow](https://stackoverflow.com/questions/72801333):
> "When FastAPI decodes the complete request URL (i.e., request.url), any %2F characters are converted back to /, and hence, it recognizes those forward slashes as path separators"

FastAPI decodes `%2F` → `/` **before** route matching, so:
```
/blob/test-xxx%2Fmemory/projects%2Fproject1%2Fnotes.md
↓ decodes to ↓
/blob/test-xxx/memory/projects/project1/notes.md
```

### 2. The `:path` Converter is Greedy
From [FastAPI GitHub](https://github.com/fastapi/fastapi/discussions/7362):
> "Using the path param type simply takes everything from that point on and converts it to a string parameter, including forward slashes"

With route `/blob/{namespace:path}/{path:path}`:
- `{namespace:path}` captures: `test-xxx/memory/projects/project1` (greedy!)
- `{path:path}` captures: `notes.md` (what's left)

### 3. Two `:path` Converters Are Ambiguous
The route pattern doesn't know where to split between the two parameters. FastAPI uses greedy matching, so the first parameter takes as much as possible.

## Official Documentation

From [FastAPI Path Parameters](https://fastapi.tiangolo.com/tutorial/path-params/):

```python
@app.get("/files/{file_path:path}")
async def read_file(file_path: str):
    return {"file_path": file_path}
```

> "You could need the parameter to contain `/home/johndoe/myfile.txt`, with a leading slash (`/`).
> 
> In that case, the URL would be: `/files//home/johndoe/myfile.txt`, with a double slash (`//`) between `files` and `home`."

**Key insight**: The `:path` converter captures **everything** from that point onwards, including all forward slashes.

## Attempted Solutions

### ❌ Option 1: URL Encoding
**Problem**: FastAPI decodes before routing

### ❌ Option 2: Single Path Parameter with Manual Parsing
```python
@app.put("/blob/{full_path:path}")
def write_blob(full_path: str):
    parts = full_path.split("/", 1)  # Try to split manually
```
**Problem**: Still gets decoded path, no way to distinguish encoded vs unencoded slashes

### ❌ Option 3: Custom Separator
```python
@app.put("/blob/{namespace}::{path:path}")
```
**Problem**: Non-standard syntax, awkward to use

### ❌ Option 4: Base64 Encoding
```python
@app.put("/blob/{namespace}/{encoded_path}")
def write_blob(namespace: str, encoded_path: str):
    path = base64.urlsafe_b64decode(encoded_path)
```
**Problem**: Adds complexity, URLs not human-readable

### ✅ Option 5: Query Parameters (CHOSEN)
```python
@app.put("/blob/{namespace:path}")
def write_blob(namespace: str, path: str = Query(...)):
    ...
```

**Why this works**:
1. Query parameters are naturally separate from path
2. FastAPI handles query string decoding correctly
3. Standard REST practice
4. Clean and maintainable
5. Well-documented and supported

**URL format**:
```
PUT /blob/test-xxx%2Fmemory?path=projects%2Fproject1%2Fnotes.md
```

**Result**:
- namespace: `test-xxx/memory` ✅
- path: `projects/project1/notes.md` ✅

## Testing

Created test file `tests/integration/sync_client/test_query_params.py`:

```python
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
```

**Result**: ✅ PASSED

## References

1. [FastAPI Path Parameters Documentation](https://fastapi.tiangolo.com/tutorial/path-params/)
2. [GitHub Issue #1750: Endpoint with parameter that has forward "/" slashes](https://github.com/fastapi/fastapi/issues/1750)
3. [GitHub Discussion #7362: Path parameters with slashes](https://github.com/fastapi/fastapi/discussions/7362)
4. [Stack Overflow: How to pass URL as a path parameter](https://stackoverflow.com/questions/72801333)
5. [Stack Overflow: Route path components with forward slash](https://stackoverflow.com/questions/62770461)

## Conclusion

**Query parameters are the correct and recommended solution** for passing file paths with slashes in FastAPI. This is a well-understood pattern in the FastAPI community and aligns with REST best practices.
