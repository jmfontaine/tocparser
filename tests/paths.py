"""Where the TOC files the tests run on live."""

from __future__ import annotations

from pathlib import Path

#: Real TOC files produced by cdrdao. Nothing here may be edited by hand.
CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
#: Hand-written files covering spec corners the corpus does not reach.
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

CORPUS_FILES = sorted(CORPUS_DIR.glob("*.toc"))
FIXTURE_FILES = sorted(FIXTURES_DIR.glob("*.toc"))

#: Which cdrdao version wrote each corpus file, kept beside the files because
#: they must stay cdrdao's bytes untouched.
CORPUS_VERSIONS = CORPUS_DIR / "cdrdao-versions.csv"
