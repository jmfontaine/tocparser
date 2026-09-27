#!/usr/bin/env python
"""Check the contents of built distributions before they are published.

Usage: ``python scripts/check_distributions.py dist``

The wheel and the sdist are held to different contracts. The wheel is what gets
imported, so it must carry the package, including the grammar and the PEP 561
marker, and nothing else. The sdist is what downstream packagers rebuild and
test from, so it must also carry the test suite and the whole cdrdao corpus.

The test suite cannot make these checks: it runs from the source tree, where a
wheel missing ``grammar.lark`` or an sdist missing corpus files looks fine.
"""

from __future__ import annotations

import csv
import io
import sys
import tarfile
import zipfile
from pathlib import Path

PACKAGE = "tocparser"
PACKAGE_FILES = (
    "__init__.py",
    "errors.py",
    "grammar.lark",
    "models.py",
    "parser.py",
    "py.typed",
    "serializer.py",
    "times.py",
)
# Useful in the repository and in the sdist, wrong in the importable wheel.
WHEEL_FORBIDDEN_ROOTS = ("tests", "scripts")
SDIST_REQUIRED = (
    "PKG-INFO",
    "pyproject.toml",
    "README.md",
    "LICENSE.txt",
    "tests/conftest.py",
    "tests/corpus/cdrdao-versions.csv",
)
# Build and editor leftovers that must never be published.
FORBIDDEN_PARTS = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv")


def fail(message: str) -> None:
    print(f"check_distributions: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_leftovers(archive: str, names: list[str]) -> None:
    for name in names:
        parts = Path(name).parts
        if any(part in FORBIDDEN_PARTS for part in parts) or name.endswith((".pyc", ".coverage")):
            fail(f"{archive} contains {name}")


def check_wheel(path: Path) -> None:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()

    missing = [f"{PACKAGE}/{name}" for name in PACKAGE_FILES if f"{PACKAGE}/{name}" not in names]
    if missing:
        fail(f"{path.name} is missing {', '.join(missing)}")

    if not any(name.endswith(".dist-info/licenses/LICENSE.txt") for name in names):
        fail(f"{path.name} is missing its license file")

    stray = sorted({name.split("/")[0] for name in names} & set(WHEEL_FORBIDDEN_ROOTS))
    if stray:
        fail(f"{path.name} ships project-only directories: {', '.join(stray)}")

    check_leftovers(path.name, names)
    print(f"check_distributions: {path.name} ok ({len(names)} files)")


def check_sdist(path: Path) -> None:
    # Everything sits under "<name>-<version>/", the archive's own name.
    root = path.name.removesuffix(".tar.gz")
    with tarfile.open(path) as archive:
        names = [
            name[len(root) + 1 :] for name in archive.getnames() if name.startswith(f"{root}/")
        ]
        try:
            versions = archive.extractfile(f"{root}/tests/corpus/cdrdao-versions.csv")
        except KeyError:
            versions = None
        listed = (
            [row["file"] for row in csv.DictReader(io.TextIOWrapper(versions, encoding="utf-8"))]
            if versions is not None
            else []
        )

    required = [*SDIST_REQUIRED, *(f"src/{PACKAGE}/{name}" for name in PACKAGE_FILES)]
    missing = [name for name in required if name not in names]
    if missing:
        fail(f"{path.name} is missing {', '.join(missing)}")

    # The corpus is the heart of the test suite, so every file it lists ships.
    if not listed:
        fail(f"{path.name} lists no corpus files")
    missing_corpus = [name for name in listed if f"tests/corpus/{name}" not in names]
    if missing_corpus:
        fail(f"{path.name} is missing {len(missing_corpus)} corpus files, e.g. {missing_corpus[0]}")

    check_leftovers(path.name, names)
    print(f"check_distributions: {path.name} ok ({len(names)} files, {len(listed)} corpus files)")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: check_distributions.py DIST_DIR")
    dist = Path(sys.argv[1])
    wheels = sorted(dist.glob("*.whl"))
    sdists = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        fail(f"expected one wheel and one sdist in {dist}, found {len(wheels)} and {len(sdists)}")
    check_wheel(wheels[0])
    check_sdist(sdists[0])


if __name__ == "__main__":
    main()
