set quiet := true

# List the available recipes.
_list:
    just --list

# CDRDAO_DEVICE picks the drive, CDRDAO_SESSION the session on a multi-session disc.
# Add the disc's TOC, or TOC_FILE, to the test corpus
add-toc toc_file="":
    uv run python scripts/add_toc.py {{ if toc_file == "" { "" } else { quote(toc_file) } }}

# Update deps to latest versions
deps-update:
    uv lock --upgrade
    uv sync --all-groups

# Run formatters
format:
    # pyproject-fmt exits 1 after reformatting; only fail if the file is still off.
    uv run pyproject-fmt pyproject.toml || uv run pyproject-fmt --check pyproject.toml
    uv run ruff format

# Check formatting without modifying files
format-check:
    uv run pyproject-fmt --check pyproject.toml
    uv run ruff format --check

# Run linter
lint:
    uv run ruff check

# Run linter and fix issues
lint-fix:
    uv run ruff check --fix

# Run pre-commit on all files
pre-commit:
    uv run pre-commit run --all-files

# Install pre-commit hooks
pre-commit-install:
    uv run pre-commit install

# Update pre-commit hooks to latest versions
pre-commit-update:
    uv run pre-commit autoupdate --freeze

# Run all quality assurance checks
qa: format-check lint type-check verify-types

# Set local dev environment up
setup:
    uv sync --all-groups  # Install dependencies
    uv run pre-commit install  # Install pre-commit hooks
    echo "Run 'source .venv/bin/activate' to activate the Python virtual environment"

# Run tests with coverage
test *args:
    uv run pytest --cov --cov-report=term-missing {{ args }}

# Compare results with cdrdao (requires cdrdao)
test-cdrdao *args:
    TOCPARSER_REQUIRE_CDRDAO=1 uv run pytest tests/test_cdrdao_oracle.py {{ args }}

# Run type checker
type-check:
    uv run mypy

# Audit public API type annotation coverage
verify-types:
    uv run pyright --ignoreexternal --verifytypes tocparser
