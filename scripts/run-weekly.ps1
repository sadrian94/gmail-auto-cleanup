# PowerShell Script to run Weekly Gmail Cleanup & Deep Scan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
# Navigate to the project root directory
Set-Location $ScriptDir\..

Write-Host "========================================="
Write-Host "Starting Weekly Gmail Auto-Cleanup & Deep Scan"
Write-Host "Timestamp: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "========================================="

# Execute weekly cleanup: apply deletion + deep scan + generate weekly AI/Markdown report
if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv run python -m gmail_cleanup --account personal --analytics-deep --apply --ai-summary
} else {
    python -m gmail_cleanup --account personal --analytics-deep --apply --ai-summary
}

Write-Host "-----------------------------------------"
Write-Host "Weekly Cleanup & Deep Scan complete."
Write-Host "========================================="
