# Contributing to tocparser

Contributions are welcome: bug fixes, new features, documentation, test coverage.
This guide walks you through the development setup and pull request process.

For larger changes, please open an issue first so we can discuss the approach
before you invest significant time.

## Reporting bugs and requesting features

Before opening an issue, search [existing issues](https://github.com/jmfontaine/tocparser/issues)
to avoid duplicates.

**Bug reports** should include:

- Python version and tocparser version (`python --version`, `pip show tocparser` or
  `uv pip show tocparser`)
- The TOC file that triggers the problem, or the smallest part of it that still does
- The full traceback or error message
- For a file tocparser accepts or rejects differently from cdrdao, the cdrdao version and what
  `cdrdao show-toc` reports

**Feature requests**: describe the problem you want to solve, not just the solution.

## Setup

```bash
git clone https://github.com/jmfontaine/tocparser.git
cd tocparser
just setup
```

`just setup` needs only [uv](https://docs.astral.sh/uv/) and [just](https://github.com/casey/just)
on your PATH. It installs every dependency, including pre-commit, which is declared in the `dev`
dependency group, and then installs the git hooks.

> [!TIP]
> If you don't have just installed, you can run the underlying commands directly. Check
> [`justfile`](justfile) to see what each recipe runs; most are one-line `uv run` commands.
> For example, `just test` runs `uv run pytest --cov --cov-report=term-missing`.

## Development workflow

Key commands:

```bash
just format        # Auto-format code and pyproject.toml
just lint-fix      # Auto-fix lint issues
just qa            # All checks (see the pull request checklist below)
just test          # Tests with coverage
just test-cdrdao   # Compare verdicts, messages and line numbers with cdrdao
just type-check    # Run mypy
just verify-types  # Check the public API is fully typed
```

Run `just --list` to see all available commands.

## Testing

```bash
just test                                        # All tests
just test tests/test_parser.py                   # Single file
just test tests/test_parser.py -k test_encodings # Single test
```

The suite parses and round-trips every file in `tests/corpus/`, which holds real cdrdao output,
plus the hand-written files in `tests/fixtures/`, which cover the directives the corpus never uses.
Coverage is at 100%; keep it there.

### The corpus

Files in `tests/corpus/` are cdrdao's own bytes, and the suite requires each one to come back byte
for byte, so never edit one. Add a disc with `just add-toc`, which reads it with cdrdao and records
the cdrdao version in `tests/corpus/cdrdao-versions.csv`. For a TOC file cdrdao wrote elsewhere,
run `just add-toc path/to/file.toc` instead. See [`tests/corpus/README.md`](tests/corpus/README.md)
for the details.

### Comparing with cdrdao

`tests/test_cdrdao_oracle.py` runs `cdrdao show-toc` over the fixtures and a list of edge cases, and
checks that tocparser's verdict, message and line number match cdrdao's. The expectations were
recorded with cdrdao 1.2.6, which tocparser follows.

```bash
brew install cdrdao   # or your distribution's package
just test-cdrdao
```

`just test` skips the comparison when cdrdao is not installed; `just test-cdrdao` fails instead. CI
always runs it. With a different cdrdao version installed, one test fails saying so and the
comparisons are skipped.

## Code style

- Python 3.10+, formatting and linting by ruff, line length 100 (`just format`, `just lint-fix`)
- Strict type checking with mypy (`just type-check`), and a fully typed public API
  (`just verify-types`)
- US English everywhere: code, comments, docs and commit messages
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) without a
  scope: `<type>: <description>`, where the type is one of `feat`, `fix`, `refactor`, `chore`,
  `docs`, `test` or `ci` (e.g., `fix: reject an index at the start of a track`)

## Submitting a pull request

1. Fork the repository and create a branch from `main` (e.g., `fix/index-at-start`)
2. Make your changes, and add or update tests
3. Run `just qa` and `just test` to catch issues before CI does
4. Push and open a pull request against `main`, referencing any related issues (e.g., "Fixes #42")

### Pull request checklist

- [ ] Tests added or updated and passing (`just test`), with coverage still at 100%
- [ ] `just qa` passes
- [ ] `just test-cdrdao` passes, if the change affects what tocparser accepts or rejects
- [ ] README updated, if the change affects behavior users see

### What to expect

A maintainer will review your pull request, usually within a few days. Change requests are normal
and collaborative. Push additional commits to the same branch; no need to force-push or squash
until asked.

## Releasing

Maintainers only.

1. Set the new version, e.g. `uv version --bump minor`, and commit it along with `uv.lock`
2. Run `just changelog-preview` to check the release notes, which
   [git-cliff](https://git-cliff.org/) builds from the commit messages since the last tag
3. Run `just release`, which tags the version as `vX.Y.Z`, pushes `main` and the tag in one atomic
   push, and watches the publish workflow

The tag starts `.github/workflows/publish.yml`. It checks that the tagged commit is on `main`, runs
every CI check on it, publishes the wheel and sdist that CI built and tested to PyPI, then creates
the GitHub release with the same notes. A tag that doesn't match the package version stops before
the upload.

If a job fails after the PyPI upload, rerun the workflow: the upload skips the files PyPI already
has, and the GitHub release is created only if it doesn't exist yet.

Publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no token is
stored. It needs a GitHub environment named `pypi`, and a trusted publisher on PyPI with exactly
these values: owner `jmfontaine`, repository `tocparser`, workflow `publish.yml`, environment
`pypi`. Before the first release the PyPI project doesn't exist yet, so register it as a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/) for
the project name `tocparser`; the first upload creates the project.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE.txt).
