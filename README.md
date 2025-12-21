# pyumann

This project aims to port my pet Perl tools developed for 25 years to Python.

They are almost all metadata-related: Mostly image, some video and audio.

## Roadmap

- Auto-tag image by GPSPosition (Country, City, Location, OffsetTimeOriginal)
- Support Picasa (in the sense of supporting an old building with external frame)
- Sync audio metadata with dir and file name


## Requirements

- [Python](https://www.python.org/) 3.11 or higher
- [ExifTool](https://exiftool.org/install.html) command-line tool (install separately)

## Installation

### For Users

Install the package from the repository:

```bash
pip install git+https://github.com/umann/pyumann.git
```

### For Developers

1. Clone the repository:
```bash
git clone https://github.com/umann/pyumann.git
cd pyumann
```

2. Create a virtual environment:
```bash
python3 -m venv .venv
```

3. Activate the virtual environment:
```bash
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate  # Windows
```

4. Install in development mode with all dependencies:
```bash
make dev
```

This will:
- Install the package and all dev dependencies
- Set up pre-commit hooks that automatically:
  - Format code with Black and isort before commits
  - Run pylint checks before commits
  - Run all tests before pushes

## Usage

### Command Line Interface

The package provides the `et` command-line tool for metadata operations:

```bash
# Get metadata from an image
et image.jpg

# Process multiple files
et *.jpg

# Get one file metadata in same dictionary-by-filename format
et --dictify image.jpg

# Set metadata tags
et --set '{"IPTC:Keywords": "tag1, tag2"}' image.jpg

```

### Python API

```python
from umann.metadata import et

# Get metadata from a file
metadata = et.get_metadata('image.jpg')

# Get metadata from multiple files
metadata_dict = et.get_metadata_multi(['image1.jpg', 'image2.jpg'])

# Set metadata tags
et.set_tags('image.jpg', {'IPTC:Keywords': ['tag1', 'tag2']})
```

## Configuration

pyumann loads its configuration from YAML, with a simple base+override scheme.

- Base config: taken from the file specified by environment variable `PYUMANN_CONFIG`; if unset, defaults to the repository/root `config.yaml`.
- Override config (optional): if environment variable `PYUMANN_CONFIG_OVERRIDE` is set, that file is loaded and shallow-merged on top of the base config. Otherwise, if `~/.pyumann_config_override.yaml` exists, it is merged on top of the base config.

APIs:
- `umann.config.load_config()` returns the merged configuration as a dict and is cached via `functools.lru_cache`.
- `umann.config.get_config(path: str | None = None, default: Any | None = None)` retrieves a value by dot-separated path (e.g., `"section.sub.key"`), or returns the full config when `path` is omitted.

Examples:

```python
from umann.config import load_config, get_config

cfg = load_config()
db_url = get_config("database.url", default="sqlite:///data.db")

# If you need to reload after changing env vars or files:
load_config.cache_clear()
cfg = load_config()
```

Environment variables:
- `PYUMANN_CONFIG` — absolute or relative path to the base YAML file
- `PYUMANN_CONFIG_OVERRIDE` — path to an optional override YAML file

User override file (if env var not set):
- `~/.pyumann_config_override.yaml` — merged on top of base when present

Merging behavior:
- Dictionaries are deep-merged; other values are overridden by the override file.

## Development

### Testing

Run the test suite:

```bash
# Run all tests (includes formatting and linting checks)
make test

# Run specific test types
make unit        # Unit tests only
make integration # Integration tests only
make system      # System tests only

# Run with coverage report
python -m pytest tests/ --cov=umann --cov-report=term-missing
```

### Code Quality

The project uses Black for formatting and Pylint for linting:

```bash
# Format code with Black and isort
make format

# Run linting
make lint

# Run all quality checks and tests
make test
```

All code style settings (line length: 119) are configured in `pyproject.toml`.

### Project Structure

- `umann/metadata/`: ExifTool integration and metadata manipulation
- `umann/utils/`: Core utility functions
- `tests/`: Test suite organized by test type (unit, integration, system)
  - `fixtures/`: Test data and sample files
  - `utils/`: Shared test utilities

## Contributing

1. Create a feature branch from `main`
2. Make your changes
3. Add tests for any new functionality
4. Ensure all tests pass
5. Submit a pull request

To deactivate:

```bash
deactivate
```

VS Code integration

- This repo includes workspace settings in `.vscode/settings.json` that:
	- set the workspace interpreter to `.venv/bin/python`, and
	- start integrated terminals with the venv activated by default.

- To use it: open the folder in VS Code, then open a new integrated terminal -
	it should activate the venv automatically and the Python extension should
	pick the `.venv` interpreter.

- If you prefer these settings to stay local, add `.vscode/` to
	`.gitignore` (the repository currently commits `.vscode/settings.json`).
