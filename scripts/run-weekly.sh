#!/bin/bash
# Shell Script to run Weekly Gmail Cleanup & Deep Scan

# Navigate to the project root directory
cd "$(dirname "$0")/.."

echo "========================================="
echo "Starting Weekly Gmail Auto-Cleanup & Deep Scan"
echo "Timestamp: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================="

# Run using uv if available, otherwise fallback to python3
if command -v uv &> /dev/null; then
    uv run python3 -m gmail_cleanup --account personal --analytics-deep --apply --ai-summary
else
    python3 -m gmail_cleanup --account personal --analytics-deep --apply --ai-summary
fi

echo "-----------------------------------------"
echo "Weekly Cleanup & Deep Scan complete."
echo "========================================="
