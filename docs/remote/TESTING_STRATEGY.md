# Testing Strategy for SILIC-5 Messaging System

This document outlines various approaches for testing the messaging system before it's published to PyPI.

## 🚀 Quick Start: Local Testing

Run the comprehensive test script:

```bash
./test_messaging_system.sh
```

This will:
- Start the root messaging app and agent receiver
- Test all CLI commands
- Validate the agent messaging function
- Check web interface and API endpoints
- Provide manual testing endpoints

## 🔧 Detailed Testing Approaches

### Option 1: Full Local Testing (Recommended for Development)

**Setup:**
```bash
git checkout feature/silic-5-messaging-system
uv sync
```

**Test Components Individually:**

1. **Root Messaging App:**
   ```bash
   # Terminal 1
   uv run silica messaging app --port 5000
   
   # Test health check
   curl -H "Host: silica-messaging" http://localhost:5000/health
   ```

2. **Agent Receiver:**
   ```bash
   # Terminal 2
   export SILICA_WORKSPACE=test
   export SILICA_PROJECT=myproject
   uv run silica messaging receiver --port 8901
   
   # Test health check
   curl http://localhost:8901/health
   ```

3. **CLI Commands:**
   ```bash
   # Terminal 3
   uv run silica msg list
   uv run silica msg send -t "test123" "Hello world"
   uv run silica msg history "test123"
   uv run silica msg participants "test123"
   ```

4. **Agent Messaging Function:**
   ```bash
   source silica/agent/messaging.sh
   export SILICA_WORKSPACE=test
   export SILICA_PROJECT=myproject
   
   silica-msg "Hello from agent"
   echo "piped message" | silica-msg
   silica-msg-status
   ```

5. **Web Interface:**
   ```bash
   # Open browser to http://localhost:5000
   # Set Host header to 'silica-messaging' (or use proxy)
   ```

### Option 2: Piku Integration Testing

**Install development version on piku server:**

```bash
# On piku server
cd /tmp
git clone https://github.com/clusterfudge/silica.git
cd silica
git checkout feature/silic-5-messaging-system

# Install in development mode
pip install -e .
# or with uv: uv pip install -e .
```

**Create test workspace:**
```bash
# In your project directory
silica create -w test-messaging

# This should:
# 1. Deploy root messaging app (silica-messaging)
# 2. Set up workspace with messaging receiver
# 3. Configure environment variables
```

**Test integration:**
```bash
# Check messaging app deployment
piku app list | grep silica-messaging

# Check workspace app
piku app list | grep test-messaging

# Test messaging
silica msg send -t "integration-test" "Testing piku integration"

# Connect to workspace and test agent function
silica agent -w test-messaging
# In agent session:
silica-msg "Hello from piku agent"
```

### Option 3: Docker Testing

**Create test container:**

```dockerfile
# Dockerfile.test
FROM python:3.11

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tmux \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv

# Copy source code
COPY .. /app
WORKDIR /app

# Install silica in development mode
RUN uv sync

# Set up environment
ENV SILICA_WORKSPACE=docker-test
ENV SILICA_PROJECT=test-project
ENV DATA_DIR=/tmp/silica-messaging

# Expose ports
EXPOSE 5000 8901

# Run test script
CMD ["./test_messaging_system.sh"]
```

**Build and run:**
```bash
docker build -f Dockerfile.test -t silica-messaging-test .
docker run -p 5000:5000 -p 8901:8901 silica-messaging-test
```

### Option 4: Hybrid Testing (Most Practical)

**Phase 1: Local Component Testing**
- Run `./test_messaging_system.sh` to validate all components work locally
- Test web interface functionality
- Validate CLI commands and agent messaging function

**Phase 2: Mock Piku Environment**
```bash
# Simulate piku environment variables
export PORT=5000
export SILICA_WORKSPACE=mock-workspace
export SILICA_PROJECT=mock-project

# Test Procfile commands
python silica/messaging/app.py --port $PORT &
uv run silica messaging receiver --port 8901 &

# Test integration
silica msg send -t "mock-test" "Testing mock environment"
```

**Phase 3: Real Piku Integration**
- Install development version on piku server
- Create actual workspace and validate end-to-end

## 🧪 Test Checklist

### Core Functionality
- [ ] Root messaging app starts and responds to health checks
- [ ] Agent receiver starts and handles message delivery  
- [ ] CLI commands work (list, send, history, participants)
- [ ] Web interface loads and functions properly
- [ ] silica-msg bash function works with args and stdin
- [ ] Environment variables are properly set and used

### Message Flow Testing
- [ ] Human → Root App → Agent Receiver → tmux
- [ ] Agent → Root App → All Participants
- [ ] Cross-"workspace" communication via global threads
- [ ] Participant management (add/remove)
- [ ] Implicit thread creation

### Integration Testing
- [ ] Auto-deployment during workspace creation
- [ ] Procfile launches correct services
- [ ] Port configuration works correctly
- [ ] Environment variable precedence
- [ ] HTTP proxy functionality
- [ ] Real tmux session integration

### Edge Cases
- [ ] Large message handling (truncation)
- [ ] Network failure recovery
- [ ] Concurrent message handling
- [ ] Invalid JSON handling
- [ ] Missing environment variables

### Performance Testing
- [ ] Multiple concurrent threads
- [ ] High message volume
- [ ] Web interface responsiveness
- [ ] File system performance (thread storage)

## 🐛 Common Issues and Solutions

### Issue: Import Errors
**Solution:** Ensure you're using the development version:
```bash
pip install -e .
# or
uv sync && uv run silica --version
```

### Issue: Port Conflicts
**Solution:** Use different ports for testing:
```bash
uv run silica messaging app --port 5001
uv run silica messaging receiver --port 8902
```

### Issue: Host Header Issues
**Solution:** Test with proper headers:
```bash
curl -H "Host: silica-messaging" http://localhost:5000/health
```

### Issue: Environment Variables Not Set
**Solution:** Export required variables:
```bash
export SILICA_WORKSPACE=test
export SILICA_PROJECT=myproject
export SILICA_PARTICIPANT=test-myproject
```

## 📊 Expected Test Results

**Successful test output should show:**
- ✅ All components start without errors
- ✅ Health checks return 200 status
- ✅ CLI commands execute successfully
- ✅ Messages flow between components
- ✅ Web interface displays threads and messages
- ✅ Agent messaging function works in subshells

## 🚀 Next Steps After Testing

1. **Validate locally** with test script
2. **Test piku integration** with editable install
3. **Create real workspace** and test end-to-end
4. **Verify tmux integration** with actual agent sessions
5. **Test cross-workspace communication**
6. **Validate performance** with multiple threads/messages

## 📝 Reporting Issues

When reporting issues, please include:
- Testing approach used (local/piku/docker)
- Environment details (OS, Python version, etc.)
- Full error messages and logs
- Steps to reproduce
- Expected vs actual behavior

The test script generates logs in `messaging_app.log` and `receiver.log` which can help with debugging.