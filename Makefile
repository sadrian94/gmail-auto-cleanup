.PHONY: install test run run-personal weekly weekly-apply dashboard clean

# Install the package and dependencies
install:
	uv pip install -e .[test,ai]

# Run unit tests
test:
	uv run pytest tests/

# Run dry-run on dummy account
run:
	uv run python -m gmail_cleanup --account dummy

# Run dry-run on personal account
run-personal:
	uv run python -m gmail_cleanup --account personal

# Run weekly dry-run deep scan and report
weekly:
	uv run python -m gmail_cleanup --account personal --analytics-deep --ai-summary

# Run weekly actual cleanup
weekly-apply:
	uv run python -m gmail_cleanup --account personal --analytics-deep --apply --ai-summary

# Generate static HTML dashboard
dashboard:
	uv run python -m gmail_cleanup --account personal --dashboard

# Clean up Python cache and build files
clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache
	find . -name "*.pyc" -delete
	find . -name "__pycache__" -delete
