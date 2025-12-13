#!/bin/bash
#
# Persona Backup Restoration Script
# ==================================
# This script restores history and memory files from the backup tarball
# WITHOUT overwriting any existing files.
#
# What it does:
# 1. Creates a temporary extraction directory
# 2. Extracts the tarball to that directory
# 3. Copies files from backup to personas directory, skipping any that already exist
# 4. Provides a detailed summary of what was restored
#
# Safety features:
# - Uses rsync with --ignore-existing to never overwrite
# - Creates a backup manifest before restoration
# - Dry-run mode available for preview
# - Logs all operations

set -euo pipefail

# Configuration
SILICA_DIR="${HOME}/.silica"
PERSONAS_DIR="${SILICA_DIR}/personas"
BACKUP_TARBALL="${SILICA_DIR}/personas-backeup-20251110.tar.gz"
TEMP_DIR="${SILICA_DIR}/restore_temp_$$"
LOG_FILE="${SILICA_DIR}/restore_$(date +%Y%m%d_%H%M%S).log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
DRY_RUN=false
VERBOSE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Restore personas backup without overwriting existing files."
            echo ""
            echo "Options:"
            echo "  -n, --dry-run    Show what would be done without making changes"
            echo "  -v, --verbose    Show detailed progress"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

log() {
    local level=$1
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" >> "$LOG_FILE"
    
    case $level in
        INFO)
            echo -e "${BLUE}[INFO]${NC} ${message}"
            ;;
        WARN)
            echo -e "${YELLOW}[WARN]${NC} ${message}"
            ;;
        ERROR)
            echo -e "${RED}[ERROR]${NC} ${message}"
            ;;
        SUCCESS)
            echo -e "${GREEN}[SUCCESS]${NC} ${message}"
            ;;
    esac
}

cleanup() {
    if [[ -d "$TEMP_DIR" ]]; then
        log INFO "Cleaning up temporary directory..."
        rm -rf "$TEMP_DIR"
    fi
}
trap cleanup EXIT

# Pre-flight checks
log INFO "Starting persona backup restoration"
log INFO "Log file: $LOG_FILE"

if [[ ! -f "$BACKUP_TARBALL" ]]; then
    log ERROR "Backup tarball not found: $BACKUP_TARBALL"
    exit 1
fi

if [[ ! -d "$PERSONAS_DIR" ]]; then
    log ERROR "Personas directory not found: $PERSONAS_DIR"
    exit 1
fi

if $DRY_RUN; then
    log WARN "DRY RUN MODE - No changes will be made"
fi

# Count existing files
EXISTING_COUNT=$(find "$PERSONAS_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
log INFO "Current personas directory has $EXISTING_COUNT files"

# Count files in tarball
BACKUP_COUNT=$(tar -tzf "$BACKUP_TARBALL" | grep -v '/$' | wc -l | tr -d ' ')
log INFO "Backup tarball contains $BACKUP_COUNT files"

# Create manifest of existing files (for safety)
log INFO "Creating manifest of existing files..."
MANIFEST_FILE="${SILICA_DIR}/existing_files_manifest_$(date +%Y%m%d_%H%M%S).txt"
find "$PERSONAS_DIR" -type f > "$MANIFEST_FILE"
log INFO "Manifest saved to: $MANIFEST_FILE"

# Create temp directory
log INFO "Creating temporary extraction directory..."
mkdir -p "$TEMP_DIR"

# Extract tarball
log INFO "Extracting backup tarball (this may take a moment)..."
if $VERBOSE; then
    tar -xzvf "$BACKUP_TARBALL" -C "$TEMP_DIR"
else
    tar -xzf "$BACKUP_TARBALL" -C "$TEMP_DIR"
fi

# The tarball extracts to a 'personas' subdirectory
EXTRACTED_DIR="${TEMP_DIR}/personas"

if [[ ! -d "$EXTRACTED_DIR" ]]; then
    log ERROR "Expected personas directory not found in extracted tarball"
    exit 1
fi

# Count extracted files
EXTRACTED_COUNT=$(find "$EXTRACTED_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
log INFO "Extracted $EXTRACTED_COUNT files from backup"

# Count history and memory files specifically
BACKUP_HISTORY_COUNT=$(find "$EXTRACTED_DIR" -path "*/history/*" -type f | wc -l | tr -d ' ')
BACKUP_MEMORY_COUNT=$(find "$EXTRACTED_DIR" -path "*/memory/*" -type f | wc -l | tr -d ' ')
log INFO "Backup contains: $BACKUP_HISTORY_COUNT history files, $BACKUP_MEMORY_COUNT memory files"

# Use rsync with --ignore-existing to restore without overwriting
# This is the safest and most reliable method
log INFO "Restoring files (skipping existing)..."

if $DRY_RUN; then
    # Count files that would be restored vs skipped
    log INFO "Analyzing what would be restored..."
    WOULD_RESTORE=0
    WOULD_SKIP=0
    
    while IFS= read -r -d '' f; do
        REL_PATH="${f#$EXTRACTED_DIR/}"
        TARGET="${PERSONAS_DIR}/${REL_PATH}"
        if [[ ! -f "$TARGET" ]]; then
            ((WOULD_RESTORE++))
            if $VERBOSE; then
                echo "  [NEW] $REL_PATH"
            fi
        else
            ((WOULD_SKIP++))
            if $VERBOSE; then
                echo "  [SKIP] $REL_PATH (already exists)"
            fi
        fi
    done < <(find "$EXTRACTED_DIR" -type f -print0)
    
    echo ""
    echo "========================================="
    echo "        DRY RUN ANALYSIS                "
    echo "========================================="
    echo ""
    echo "Current state:"
    echo "  Existing files:     $EXISTING_COUNT"
    echo ""
    echo "Backup contents:"
    echo "  History files:      $BACKUP_HISTORY_COUNT"
    echo "  Memory files:       $BACKUP_MEMORY_COUNT"
    echo "  Total:              $BACKUP_COUNT"
    echo ""
    echo "Restoration preview:"
    echo "  Would restore:      $WOULD_RESTORE files"
    echo "  Would skip:         $WOULD_SKIP files (already exist)"
    echo ""
    echo "Projected result:"
    echo "  Total after restore: $((EXISTING_COUNT + WOULD_RESTORE)) files"
    echo ""
    echo "========================================="
else
    # Actual restoration
    RSYNC_OUTPUT=$(rsync -av --ignore-existing "$EXTRACTED_DIR/" "$PERSONAS_DIR/" 2>&1)
    echo "$RSYNC_OUTPUT" >> "$LOG_FILE"
    
    # Count files that were restored
    RESTORED=$(echo "$RSYNC_OUTPUT" | grep -E "^personas/" | grep -v "/$" | wc -l | tr -d ' ')
    
    if $VERBOSE; then
        echo "$RSYNC_OUTPUT"
    fi
fi

# Post-restoration counts
if ! $DRY_RUN; then
    NEW_COUNT=$(find "$PERSONAS_DIR" -type f 2>/dev/null | wc -l | tr -d ' ')
    NEW_HISTORY_COUNT=$(find "$PERSONAS_DIR" -path "*/history/*" -type f | wc -l | tr -d ' ')
    NEW_MEMORY_COUNT=$(find "$PERSONAS_DIR" -path "*/memory/*" -type f | wc -l | tr -d ' ')
    
    log SUCCESS "Restoration complete!"
    echo ""
    echo "========================================="
    echo "           RESTORATION SUMMARY          "
    echo "========================================="
    echo ""
    echo "Before restoration:"
    echo "  Total files:    $EXISTING_COUNT"
    echo ""
    echo "Backup contents:"
    echo "  History files:  $BACKUP_HISTORY_COUNT"
    echo "  Memory files:   $BACKUP_MEMORY_COUNT"
    echo "  Total files:    $BACKUP_COUNT"
    echo ""
    echo "After restoration:"
    echo "  Total files:    $NEW_COUNT"
    echo "  History files:  $NEW_HISTORY_COUNT"
    echo "  Memory files:   $NEW_MEMORY_COUNT"
    echo ""
    echo "Files restored:   $((NEW_COUNT - EXISTING_COUNT))"
    echo ""
    echo "========================================="
    echo ""
    log INFO "Manifest of pre-existing files: $MANIFEST_FILE"
    log INFO "Full log: $LOG_FILE"
else
    echo ""
    echo "========================================="
    echo "        DRY RUN COMPLETE                "
    echo "========================================="
    echo ""
    echo "Run without -n/--dry-run to perform actual restoration."
fi
