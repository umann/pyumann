# Env vars
PYTHON=.venv/bin/python
PRE_COMMIT=${PYTHON} -m pre_commit
VULTURE=${PYTHON} -m umann.utils.vulture_wrapper

.PHONY: help dev install build-c test unit integration system regression clean lint format setup-hooks vulture

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
	@echo "  vulture     - Scan for unused Python code"
	@echo "  difflint    - Run pylint on git diff --name-only"
	@echo "  format      - Format code with black and isort"
	@echo "  clean       - Remove build artifacts and cache files"

# Development setup
dev:
	pip install -e ".[dev]"
	@echo ""
	@echo "Installing git hooks..."
	${PRE_COMMIT} install
	${PRE_COMMIT} install --hook-type pre-push
	@echo ""
	@echo "Development environment ready."
	@echo "Git hooks are installed and will run automatically on commit/push"
	$(MAKE) build-c

# Build C utilities
bin/iter_dir_to_csv: src/c/iter_dir_to_csv.c
	@echo "Compiling C utilities..."
	@mkdir -p bin
	@gcc -o bin/iter_dir_to_csv src/c/iter_dir_to_csv.c -l ssl -l crypto || \
		echo "gcc not available or compilation failed - will use Python fallback"
	@true

bin/iter_dir_to_csv.exe: src/c/iter_dir_to_csv.c
	@echo "Cross-compiling Windows executable..."
	@mkdir -p bin
	@x86_64-w64-mingw32-gcc -o bin/iter_dir_to_csv.exe src/c/iter_dir_to_csv.c -l ssl -l crypto || \
		echo "x86_64-w64-mingw32-gcc not available or compilation failed - skipping Windows executable"
	@true

build-c: bin/iter_dir_to_csv bin/iter_dir_to_csv.exe

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
	${PRE_COMMIT} run --all-files
	@echo "\nChecking for dead code..."
	@${VULTURE}
	@echo "\nRunning all tests with coverage..."
	${PYTHON} -m pytest tests/ --cov=umann --cov-report=term-missing --cov-report=xml:coverage.xml
	@echo "\nChecking coverage against baseline..."
	${PYTHON} tests/utils/coverage_guard.py

# Run unit tests only
unit:
	${PYTHON} -m pytest tests/ -m unit

# Run integration tests only
integration:
	${PYTHON} -m pytest tests/ -m integration

# Run system tests only
system:
	${PYTHON} -m pytest tests/ -m system

# Run regression tests only
regression:
	${PYTHON} -m pytest tests/ -m regression

# Run linter
lint:
	${PYTHON} -m umann.utils.pylint_wrapper src/umann tests/

vulture:
	@${VULTURE}

difflint:
	${PYTHON} -m umann.utils.pylint_wrapper $(shell git diff --name-only HEAD~1 | grep -E '\.py$$')

# Format code
format:
	${PRE_COMMIT} run black --all-files
	${PRE_COMMIT} run isort --all-files

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
