.PHONY: help dev install test unit integration system regression clean lint format setup-hooks

# Default target
help:
	@echo "Available targets:"
	@echo "  dev         - Install package in development mode with dev dependencies"
	@echo "  install     - Install package in regular mode"
# 	@echo "  setup-hooks - Install pre-commit git hooks"
	@echo "  test        - Run all tests"
	@echo "  unit        - Run unit tests only"
	@echo "  integration - Run integration tests only"
	@echo "  system      - Run system tests only"
	@echo "  regression  - Run regression tests only"
	@echo "  lint        - Run pylint on source and tests"
	@echo "  format      - Format code with black and isort"
	@echo "  clean       - Remove build artifacts and cache files"

# Development setup
dev:
	pip install -e ".[dev]"
	@echo ""
	@echo "Installing git hooks..."
	pre-commit install
	pre-commit install --hook-type pre-push
	@echo ""
	@echo "Development environment ready."
	@echo "Git hooks are installed and will run automatically on commit/push"

# Regular installation
install:
	pip install -e .

# # Setup pre-commit hooks
# setup-hooks:
# 	pre-commit install
# 	pre-commit install --hook-type pre-push
# 	@echo "Git hooks installed."

# Run all tests (with pre-commit checks)
test:
	@echo "Running pre-commit checks..."
	pre-commit run --all-files
	@echo "\nChecking for dead code..."
	vulture
	@echo "\nRunning all tests with coverage..."
	python -m pytest tests/ --cov=umann --cov-report=term-missing --cov-report=xml:coverage.xml
	@echo "\nChecking coverage against baseline..."
	python tests/utils/coverage_guard.py

# Run unit tests only
unit:
	python -m pytest tests/ -m unit

# Run integration tests only
integration:
	python -m pytest tests/ -m integration

# Run system tests only
system:
	python -m pytest tests/ -m system

# Run regression tests only
regression:
	python -m pytest tests/ -m regression

# Run linter
lint:
	python -m pylint src/umann tests/

# Format code
format:
	python -m black src/ tests/
	python -m isort src/ tests/

# Clean build artifacts
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	rm -rf build/ dist/
