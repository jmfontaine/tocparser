"""Every TOC file shipped with the project must parse and round-trip."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from tests.paths import CORPUS_FILES, CORPUS_VERSIONS, FIXTURE_FILES
from tocparser import Toc, dumps, parse, parse_file


def test_corpus_is_not_empty() -> None:
    assert len(CORPUS_FILES) >= 60
    assert FIXTURE_FILES


def test_corpus_file_parses(corpus_file: Path) -> None:
    toc = parse_file(corpus_file)
    assert isinstance(toc, Toc)
    assert toc.tracks


def test_corpus_file_round_trips(corpus_file: Path) -> None:
    toc = parse_file(corpus_file)
    assert parse(dumps(toc)) == toc


def test_corpus_file_round_trips_through_json(corpus_file: Path) -> None:
    toc = parse_file(corpus_file)
    assert Toc.model_validate_json(toc.model_dump_json()) == toc


def test_fixture_parses(fixture_file: Path) -> None:
    toc = parse_file(fixture_file)
    assert isinstance(toc, Toc)
    assert toc.tracks


def test_fixture_round_trips(fixture_file: Path) -> None:
    toc = parse_file(fixture_file)
    assert parse(dumps(toc)) == toc


def test_serializer_reproduces_cdrdao_output_byte_for_byte() -> None:
    """Files cdrdao wrote must come back out unchanged, byte for byte.

    ``tests/corpus/`` holds only real cdrdao output, so nothing here may differ.
    """
    differing = {path.stem for path in CORPUS_FILES if path.read_text() != dumps(parse_file(path))}
    assert differing == set()


def test_every_corpus_file_records_its_cdrdao_version() -> None:
    """``just add-toc`` records the version; a file added by hand must too."""
    with CORPUS_VERSIONS.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    recorded = [row["file"] for row in rows]
    assert len(recorded) == len(set(recorded)), "a file is listed twice"
    assert set(recorded) == {path.name for path in CORPUS_FILES}
    for row in rows:
        assert re.fullmatch(r"[0-9]+(\.[0-9]+)+|unknown", row["cdrdao"]), row
