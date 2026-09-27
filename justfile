set quiet := true

# List the available recipes.
_list:
    just --list

# CDRDAO_DEVICE picks the drive, CDRDAO_SESSION the session on a multi-session disc.
# Add the disc's TOC, or TOC_FILE, to the test corpus
add-toc toc_file="":
    uv run python scripts/add_toc.py {{ if toc_file == "" { "" } else { quote(toc_file) } }}

# Run formatter
format:
    uv run ruff format

# Check formatting without modifying files
format-check:
    uv run ruff format --check

# Run linter
lint:
    uv run ruff check

# Run linter and fix issues
lint-fix:
    uv run ruff check --fix

# Run all quality assurance checks
qa: format-check lint type-check

# Run tests with coverage
test *args:
    uv run pytest --cov --cov-report=term-missing {{ args }}

# Compare results with cdrdao (requires cdrdao)
test-cdrdao *args:
    TOCPARSER_REQUIRE_CDRDAO=1 uv run pytest tests/test_cdrdao_oracle.py {{ args }}

# Run type checker
type-check:
    uv run mypy
