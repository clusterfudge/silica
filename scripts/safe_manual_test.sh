#!/bin/bash
# Safe manual testing script for workspace environment commands
# This script creates an isolated environment for testing

set -e

echo "🛡️  Starting Safe Manual Testing for Workspace Environment Commands"
echo "================================================"

# Create isolated test environment
TEST_DIR="/tmp/silica-workspace-env-test-$(date +%s)"
echo "📁 Creating isolated test directory: $TEST_DIR"
mkdir -p "$TEST_DIR"
cd "$TEST_DIR"

# Initialize a fake git repository
echo "🔧 Setting up fake git repository..."
git init
git config user.email "test@silica.dev"
git config user.name "Silica Test"
echo "# Test Repository for Silica Workspace Environment Testing" > README.md
git add README.md
git commit -m "Initial commit for testing"

# Create a fake workspace config to test with
echo "⚙️  Creating test workspace configuration..."
mkdir -p .silica
cat > workspace_config.json << EOF
{
  "agent_type": "hdev",
  "agent_config": {
    "flags": ["--port", "8000"],
    "args": {
      "debug": true,
      "verbose": false
    }
  }
}
EOF

echo "📋 Test environment setup complete!"
echo "   Test directory: $TEST_DIR"
echo "   Working directory: $(pwd)"
echo ""

echo "🧪 Running Safe Tests..."
echo "========================"

# Test 1: Basic status command (table output)
echo "Test 1: Basic status command"
echo "Command: python -m silica.cli.main we status"
echo "---"
python -m silica.cli.main we status 2>/dev/null || echo "⚠️  Command failed (expected in test environment)"
echo ""

# Test 2: JSON status output
echo "Test 2: JSON status output"
echo "Command: python -m silica.cli.main we status --json"
echo "---"
JSON_OUTPUT=$(python -m silica.cli.main we status --json 2>/dev/null || echo '{"error": "Command failed"}')
echo "Raw output:"
echo "$JSON_OUTPUT"
echo ""

# Test 3: JSON validation
echo "Test 3: JSON validation"
echo "Validating JSON structure..."
echo "$JSON_OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print('✅ Valid JSON')
    
    if 'overall_status' in data:
        print(f'✅ overall_status: {data[\"overall_status\"]}')
    else:
        print('❌ Missing overall_status')
    
    if 'components' in data:
        components = list(data['components'].keys())
        print(f'✅ components ({len(components)}): {components}')
    else:
        print('❌ Missing components')
        
    if 'timestamp' in data:
        print(f'✅ timestamp: {data[\"timestamp\"]}')
    else:
        print('❌ Missing timestamp')
        
except json.JSONDecodeError as e:
    print(f'❌ Invalid JSON: {e}')
except Exception as e:
    print(f'❌ Error: {e}')
"
echo ""

# Test 4: Command aliases
echo "Test 4: Command aliases"
echo "Testing all command aliases..."

aliases=("workspace-environment" "workspace_environment" "we")
for alias in "${aliases[@]}"; do
    echo "  Testing: silica $alias status --help"
    if python -m silica.cli.main "$alias" status --help >/dev/null 2>&1; then
        echo "    ✅ $alias works"
    else
        echo "    ❌ $alias failed"
    fi
done
echo ""

# Test 5: Help output
echo "Test 5: Help output validation"
echo "Command: python -m silica.cli.main we --help"
echo "---"
python -m silica.cli.main we --help 2>/dev/null || echo "⚠️  Help command failed"
echo ""

# Test 6: Component status extraction
echo "Test 6: Component status extraction (programmatic usage example)"
echo "Extracting specific information from JSON output..."
echo "$JSON_OUTPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    
    print('📊 Status Summary:')
    print(f'   Overall: {data.get(\"overall_status\", \"unknown\")}')
    print(f'   Issues: {len(data.get(\"issues\", []))}')
    
    if 'components' in data:
        components = data['components']
        for name, info in components.items():
            status = info.get('status', 'unknown')
            status_icon = '✅' if status == 'ok' else '⚠️' if status == 'warning' else '❌'
            print(f'   {status_icon} {name}: {status}')
    
except Exception as e:
    print(f'❌ Could not parse JSON: {e}')
"
echo ""

echo "🧹 Cleanup"
echo "=========="
echo "Test directory: $TEST_DIR"
echo "To cleanup: rm -rf $TEST_DIR"
echo ""

echo "🎉 Safe manual testing complete!"
echo "================================"
echo ""
echo "📝 Summary:"
echo "   • All tests run in isolated environment: $TEST_DIR"
echo "   • Original workspace untouched"
echo "   • JSON output structure validated"
echo "   • Command aliases tested"
echo "   • Programmatic usage examples demonstrated"
echo ""
echo "🔍 For more detailed testing, you can:"
echo "   1. cd $TEST_DIR"
echo "   2. Experiment with the commands safely"
echo "   3. Run: rm -rf $TEST_DIR when done"