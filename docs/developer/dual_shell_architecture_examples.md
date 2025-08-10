# Dual Shell Architecture Examples

This document provides real-world examples of using the dual shell architecture for common autonomous agent workflows.

## Overview

The dual shell architecture provides two complementary approaches:

1. **`shell_execute`** - Quick commands with unlimited output capture
2. **`shell_session_*`** - Persistent sessions for complex workflows

## Common Use Case: Slow-Starting Service Management

One of the most common patterns for autonomous agents is managing services that take time to start up, then testing them once ready. Here's how the dual shell architecture handles this:

### Core Pattern

```python
# 1. Start the service in a persistent session
await shell_session_create(
    context, 
    "service_name", 
    "startup_script_with_delays"
)

# 2. Monitor for readiness
while not ready:
    logs = shell_session_get_output(context, "service_name")
    if "READY" in logs:
        ready = True
    time.sleep(check_interval)

# 3. Test the service (quick commands)
test_result = await shell_execute(context, "curl http://localhost:8080")

# 4. Capture logs for analysis
logs = shell_session_get_output(context, "service_name")

# 5. Clean up
shell_session_destroy(context, "service_name")
```

### Real-World Example: Web Server Testing

```python
async def test_web_server_workflow():
    """Complete workflow for testing a slow-starting web server."""
    
    # Start web server with realistic startup delays
    server_script = '''
    echo "$(date): Initializing..."
    sleep 3
    echo "$(date): Loading config..."  
    sleep 2
    echo "$(date): Server ready!"
    python3 -m http.server 8080
    '''
    
    # Create persistent session for the server
    await shell_session_create(context, "web_server", server_script)
    
    # Monitor startup progress
    server_ready = False
    max_wait = 15
    
    for i in range(max_wait // 2):
        logs = shell_session_get_output(context, "web_server", lines=5)
        if "Server ready!" in logs:
            server_ready = True
            break
        time.sleep(2)
    
    if not server_ready:
        raise Exception("Server failed to start within timeout")
    
    # Test the server with quick commands
    test_commands = [
        "curl -s http://localhost:8080/",
        "curl -s -I http://localhost:8080/",
        "curl -s http://localhost:8080/nonexistent || echo 'Expected 404'"
    ]
    
    test_results = []
    for cmd in test_commands:
        result = await shell_execute(context, cmd)
        test_results.append(result)
    
    # Capture comprehensive logs
    server_logs = shell_session_get_output(context, "web_server", lines=20)
    
    # Clean up
    shell_session_destroy(context, "web_server")
    
    return {
        "server_logs": server_logs,
        "test_results": test_results,
        "status": "success"
    }
```

## Benefits for Autonomous Agents

### Service Management
- **Background processes**: Services run independently in sessions
- **Startup monitoring**: Real-time progress tracking
- **Health checking**: Continuous monitoring capabilities
- **Graceful shutdown**: Proper resource cleanup

### Testing Workflows  
- **Integration testing**: Test services once they're ready
- **Load testing**: Multiple concurrent test sessions
- **Log analysis**: Comprehensive log capture and analysis
- **Failure handling**: Robust error recovery

### Development Environments
- **Multi-service setup**: Coordinate multiple services
- **State preservation**: Development environment persists
- **Hot reloading**: Restart services without losing context
- **Debugging**: Interactive debugging capabilities

## Advanced Patterns

### Multi-Service Coordination

```python
# Start multiple services
await shell_session_create(context, "database", "start_db_script")
await shell_session_create(context, "api", "start_api_script") 
await shell_session_create(context, "frontend", "start_frontend_script")

# Wait for all to be ready
services = ["database", "api", "frontend"]
for service in services:
    wait_for_service_ready(context, service)

# Run integration tests
test_result = await shell_execute(context, "run_integration_tests")

# Cleanup all services
for service in services:
    shell_session_destroy(context, service)
```

### CI/CD Pipeline Integration

```python
# Build phase
build_result = await shell_execute(context, "docker build -t myapp .")

# Test environment setup
await shell_session_create(context, "test_env", "docker run -d myapp")
wait_for_service_ready(context, "test_env")

# Run test suite
test_results = await shell_execute(context, "pytest integration_tests/")

# Capture test logs
test_logs = shell_session_get_output(context, "test_env")

# Cleanup
shell_session_destroy(context, "test_env")
```

### Development Environment Management

```python
# Set up complete development environment
await shell_session_create(context, "db", "docker run -d postgres")
await shell_session_create(context, "redis", "docker run -d redis")
await shell_session_create(context, "api", "cd api && npm start")
await shell_session_create(context, "frontend", "cd frontend && npm start")

# Monitor all services
sessions = shell_session_list(context)

# Development work (sessions persist across agent restarts)
# ... agent can continue working ...

# When done, cleanup everything
for session in ["db", "redis", "api", "frontend"]:
    shell_session_destroy(context, session)
```

## Best Practices

### Session Naming
- Use descriptive names: `web_server`, `database`, `test_client`
- Include purpose: `integration_test_db`, `performance_api`
- Avoid conflicts: Check existing sessions first

### Error Handling
```python
try:
    await shell_session_create(context, "service", script)
    # ... work with service ...
finally:
    # Always cleanup, even on errors
    try:
        shell_session_destroy(context, "service")
    except Exception:
        pass  # Session might already be gone
```

### Monitoring Patterns
```python
def wait_for_service_ready(context, session_name, ready_pattern="READY", timeout=30):
    """Generic service readiness checker."""
    elapsed = 0
    while elapsed < timeout:
        logs = shell_session_get_output(context, session_name, lines=10)
        if ready_pattern in logs:
            return True
        time.sleep(2)
        elapsed += 2
    return False
```

### Log Management
```python
# Capture logs at different granularities
recent_logs = shell_session_get_output(context, "service", lines=10)  # Recent activity
full_logs = shell_session_get_output(context, "service", lines=1000)  # Complete history
error_logs = shell_session_get_output(context, "service", lines=50)   # Error investigation
```

## Performance Considerations

### Quick Commands vs. Sessions
- **Use `shell_execute` for**: File operations, system queries, one-off commands
- **Use `shell_session_*` for**: Long-running processes, stateful workflows, background services

### Resource Management
- **Monitor session count**: Don't create too many concurrent sessions
- **Clean up promptly**: Destroy sessions when no longer needed
- **Use timeouts**: Prevent sessions from hanging indefinitely

### Output Buffering
- **Session output is buffered**: Limited by tmux buffer size
- **Quick command output is unlimited**: No buffer constraints
- **Choose appropriately**: Large output → `shell_execute`, ongoing monitoring → sessions

## Conclusion

The dual shell architecture enables sophisticated autonomous agent workflows by providing both the simplicity of direct command execution and the power of persistent session management. This pattern is particularly powerful for:

- **CI/CD automation**
- **Integration testing**  
- **Development environment management**
- **System administration**
- **Service orchestration**

The key is choosing the right tool for each task: `shell_execute` for quick operations and `shell_session_*` for persistent workflows.