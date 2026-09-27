# Contributing to tocparser

Contributions are welcome, including bug fixes, new features, documentation, and test
coverage. This guide covers the development setup and pull request process.

For larger changes, please open an issue first so we can discuss the approach before you
invest significant time.

## Reporting Bugs and Requesting Features

Before opening an issue, search
[existing issues](https://github.com/jmfontaine/tocparser/issues) to avoid duplicates.

**Bug reports** should include:

- Python and tocparser versions (`python --version`, `pip show tocparser`, or
  `uv pip show tocparser`)
- The TOC file that triggers the problem, or the smallest part that reproduces it
- The full traceback or error message
- If tocparser accepts or rejects a file differently from cdrdao, the cdrdao version and
  the output of `cdrdao show-toc`

**Feature requests**: describe the problem you want to solve, not just the solution.

## Setup

```bash
git clone https://github.com/jmfontaine/tocparser.git
cd tocparser
just setup
```

`just setup` requires only [uv](https://docs.astral.sh/uv/) and
[just](https://github.com/casey/just) on your PATH. It installs all dependencies,
including pre-commit from the `dev` dependency group, and then installs the git hooks.

> [!TIP]
> If just isn't installed, run the underlying commands directly. See
> [`justfile`](justfile) for what each recipe runs; most are one-line `uv run` commands.
> For example, `just test` runs `uv run pytest --cov`.

## Development Workflow

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

The suite parses and round-trips every file in `tests/corpus/`, which contains actual
cdrdao output, along with the hand-written files in `tests/fixtures/`, which cover
directives absent from the corpus. Coverage is 100%; keep it there.

### The Corpus

Files in `tests/corpus/` contain cdrdao's own bytes, and the suite requires each one to
round-trip byte for byte, so never edit them. Add a disc with `just add-toc`, which
reads it using cdrdao and records the cdrdao version in
`tests/corpus/cdrdao-versions.csv`. For a TOC file written elsewhere by cdrdao, run
`just add-toc path/to/file.toc` instead. See
[`tests/corpus/README.md`](tests/corpus/README.md) for details.

### Comparing with cdrdao

`tests/test_cdrdao_oracle.py` runs `cdrdao show-toc` over the fixtures and a list of
edge cases to verify that tocparser's verdict, message and line number match cdrdao's.
It also runs `cdrdao show-toc -v 4` on each fixture and on the output from `dumps`,
requiring identical results; a value lost or changed during writing causes the test to
fail. The expectations were recorded with cdrdao 1.2.6, which tocparser follows.

```bash
brew install cdrdao   # or your distribution's package
just test-cdrdao
```

`just test` skips the comparison if cdrdao is not installed; `just test-cdrdao` fails
instead. CI always runs it. If a different cdrdao version is installed, one test fails
and reports the mismatch, and the comparisons are skipped.

## Code Style

- Python 3.10+; formatting and linting use ruff, with a line length of 88
  (`just format`, `just lint-fix`)
- Strict type checking with mypy (`just type-check`) and a fully typed public API
  (`just verify-types`)
- Use US English in code, comments, docs, and commit messages
- Follow [Conventional Commits](https://www.conventionalcommits.org/) without a scope,
  as `<type>: <description>`. Use one of `feat`, `fix`, `refactor`, `chore`, `docs`,
  `test` or `ci` as the type (e.g., `fix: reject an index at the start of a track`)

## Submitting a Pull Request

1. Fork the repository and create a branch from `main` (e.g., `fix/index-at-start`)
2. Make your changes and add or update tests
3. Run `just qa` and `just test` to catch issues before CI does
4. Push your branch and open a pull request against `main`, referencing any related
   issues (e.g., "Fixes #42")

### Pull Request Checklist

- [ ] Add or update tests, then run `just test` and maintain 100% coverage
- [ ] Run `just qa` and confirm it passes
- [ ] If the change affects what tocparser accepts, rejects or writes, run
  `just test-cdrdao` and confirm it passes
- [ ] Update the README if the change affects user-visible behavior

### What to Expect

A maintainer usually reviews pull requests within a few days. Change requests are a
normal part of the collaborative process. Push any additional commits to the same
branch; you don't need to force-push or squash unless asked.

## Releasing

Maintainers only.

1. Set the new version, e.g. `uv version --bump minor`, and commit it with `uv.lock`
2. Run `just changelog-preview` to review the release notes, which
   [git-cliff](https://git-cliff.org/) generates from the commits since the last tag
3. Run `just release`, which creates a `vX.Y.Z` tag, pushes `main` and the tag in a
   single atomic push, and monitors the publish workflow

The tag triggers `.github/workflows/publish.yml`. The workflow verifies that the tagged
commit is on `main`, runs all CI checks, publishes the wheel and sdist that CI built and
tested to PyPI, and then creates the GitHub release with the same notes. If a tag
doesn't match the package version, the workflow stops before uploading.

If a job fails after the PyPI upload, rerun the workflow. It skips files already on PyPI
and creates the GitHub release only if one doesn't already exist.

Publishing uses [trusted publishing](https://docs.pypi.org/trusted-publishers/), so no
token is stored. It requires a GitHub environment named `pypi` and a trusted publisher
on PyPI configured with exactly these values: owner `jmfontaine`, repository
`tocparser`, workflow `publish.yml`, and environment `pypi`. Before the first release,
the PyPI project doesn't exist yet, so register it as a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
for the project name `tocparser`. The first upload creates the project.

## License

By contributing, you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE.txt).
