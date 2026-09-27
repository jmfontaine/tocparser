set quiet := true

# List the available recipes.
_list:
    just --list

# CDRDAO_DEVICE picks the drive. `just add-toc --help` lists the options.
# Add the disc's TOC, or a TOC file, to the test corpus
[positional-arguments]
add-toc *args:
    uv run python scripts/add_toc.py "$@"

# Preview release notes for unreleased changes
changelog-preview:
    uv run git-cliff --unreleased

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

# Tag the version in pyproject.toml, push it, and watch the publish workflow
release:
    #!/usr/bin/env bash
    set -euo pipefail
    tag="v$(uv version --short)"
    if [ "$(git branch --show-current)" != "main" ]; then
        echo "Error: releases are tagged on main" >&2
        exit 1
    fi
    if [ -n "$(git status --porcelain)" ]; then
        echo "Error: working tree is not clean" >&2
        exit 1
    fi
    if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then
        echo "Error: tag $tag already exists" >&2
        exit 1
    fi
    echo "Creating signed tag $tag..."
    git tag -s "$tag" -m "Release $tag"
    echo "Pushing main and $tag to origin..."
    # Atomic: were main rejected, the tag alone would still publish.
    if ! git push --atomic origin main "$tag"; then
        git tag -d "$tag" >/dev/null
        echo "Error: push rejected; deleted the local tag $tag" >&2
        exit 1
    fi
    echo "Waiting for the publish workflow to start..."
    run_id=""
    for _ in $(seq 30); do
        run_id=$(gh run list --workflow=publish.yml --branch="$tag" --limit=1 --json=databaseId --jq='.[0].databaseId // empty')
        [ -n "$run_id" ] && break
        sleep 2
    done
    if [ -z "$run_id" ]; then
        echo "Error: no publish run for $tag after 60s; check GitHub Actions" >&2
        exit 1
    fi
    gh run watch --exit-status "$run_id"

# Set local dev environment up
setup:
    uv sync --all-groups  # Install dependencies
    uv run pre-commit install  # Install pre-commit hooks
    echo "Run 'source .venv/bin/activate' to activate the Python virtual environment"

# Run tests with coverage
test *args:
    uv run pytest --cov {{ args }}

# Compare results with cdrdao (requires cdrdao)
test-cdrdao *args:
    TOCPARSER_REQUIRE_CDRDAO=1 uv run pytest tests/test_cdrdao_oracle.py {{ args }}

# Run type checker
type-check:
    uv run mypy

# Audit public API type annotation coverage
verify-types:
    uv run pyright --ignoreexternal --verifytypes tocparser
