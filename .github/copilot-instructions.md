# AI Agent Instructions for pyumann

This document provides essential context for AI agents working with the pyumann codebase.

## Project Overview
pyumann is a Python toolset with a focus on metadata manipulation and utility functions. The project requires Python 3.11+ and uses modern Python features.

## Key Components

### Metadata Tools (`umann/metadata/`)
- `et.py`: ExifTool wrapper for image metadata manipulation
  - Uses `pyexiftool` for metadata operations
  - Supports both single and batch file operations
  - Handles GPS and keyword tag transformations
  - CLI interface via Click framework

### Utilities (`umann/utils/`)
- `fs_utils.py`: Filesystem utilities
  - `project_root()`: Path resolution relative to project root
  - Implements caching via `@lru_cache` for performance

## Project Patterns & Conventions

### Type Hints
- Strict typing with `typing` module
- Use `t.Any` for dynamic types
- Position-only parameters marked with `/`

### Function Design
- Pure functions preferred
- Use `@lru_cache` for caching expensive operations
- Context managers for resource handling (e.g., ExifTool connections)

### CLI Tools
- Click framework for command-line interfaces
- YAML for structured data I/O
- Support both single and batch operations where applicable

## Development Environment

### Python Virtual Environment
- Repository-local venv in `.venv/`
- VS Code integration via workspace settings
- Automatic venv activation in integrated terminals

### Dependencies
- Core: `PyYAML`, `click`, `pyexiftool`
- Dev: `pytest`, `pytest-cov`, `black`

### Code Style
- Black formatter with 119 character line length
- Modern Python features (3.11+)
  - Pattern matching with `:=` operator
  - Type hints with `|` for unions

## Common Development Tasks

### Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Using CLI Tools
Example of metadata operations:
```bash
et image.jpg  # Get metadata
et --set '{"IPTC:Keywords": "tag1, tag2"}' image.jpg  # Set metadata
```
