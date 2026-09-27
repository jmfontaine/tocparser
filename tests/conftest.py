"""Shared fixtures.

Corpus files are numbered rather than named after the disc they came from, so no
filename here names an artist or a release. To keep failures readable the pytest
id is rebuilt from each file's own contents instead.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.paths import CORPUS_FILES, FIXTURE_FILES

_DISC_TYPE_RE = re.compile(
    r"^\s*(CD_DA|CD_ROM_XA|CD_ROM|CD_I)\s*(?://.*)?$", re.MULTILINE
)
_TRACK_RE = re.compile(r"^\s*TRACK\s", re.MULTILINE)


def corpus_id(path: Path) -> str:
    """Describe a corpus file by what it contains, e.g. ``00007-cd_rom-11t-cdtext``."""
    text = path.read_text()
    disc_types = _DISC_TYPE_RE.findall(text)
    # The last disc type flag is the one that takes effect.
    parts = [path.stem, (disc_types[-1] if disc_types else "CD_DA").lower()]
    parts.append(f"{len(_TRACK_RE.findall(text))}t")
    if "CD_TEXT" in text:
        parts.append("cdtext")
    return "-".join(parts)


@pytest.fixture(params=CORPUS_FILES, ids=corpus_id)
def corpus_file(request: pytest.FixtureRequest) -> Path:
    path = request.param
    assert isinstance(path, Path)
    return path


@pytest.fixture(params=FIXTURE_FILES, ids=lambda path: path.stem)
def fixture_file(request: pytest.FixtureRequest) -> Path:
    path = request.param
    assert isinstance(path, Path)
    return path
