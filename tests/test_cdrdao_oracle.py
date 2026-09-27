"""Cross-check our verdicts, messages and line numbers against cdrdao itself.

``cdrdao show-toc`` parses and validates a toc-file and reports each problem
as ``ERROR: file:line: message``, so it can act as an oracle both for "does
cdrdao accept this?" and for what it says when it does not. It needs the
referenced media to exist, so each case is written into a temporary directory
alongside a generated WAVE file and a data file.

Skipped when cdrdao is not installed, unless ``TOCPARSER_REQUIRE_CDRDAO`` is
set, as it is in CI, where a missing cdrdao is an error. The expectations were
recorded with ``EXPECTED_CDRDAO_VERSION``; with any other version installed,
one test fails saying so and the comparisons are skipped, since they would
compare against another cdrdao's rules.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

from tocparser import TocParseError, TocValidationError, dumps, parse

#: The cdrdao release whose rules tocparser follows and these expectations
#: were recorded with. Moving to a new release means re-running this module
#: against it and updating the cases, and the rules, that changed.
EXPECTED_CDRDAO_VERSION = "1.2.6"

HAVE_CDRDAO = shutil.which("cdrdao") is not None
if not HAVE_CDRDAO and os.environ.get("TOCPARSER_REQUIRE_CDRDAO"):
    raise RuntimeError("TOCPARSER_REQUIRE_CDRDAO is set but cdrdao is not installed")

pytestmark = pytest.mark.skipif(not HAVE_CDRDAO, reason="cdrdao is not installed")


def _installed_cdrdao_version() -> str | None:
    if not HAVE_CDRDAO:
        return None
    # cdrdao prints "Cdrdao version 1.2.6 - (C) ..." on stderr.
    completed = subprocess.run(
        ["cdrdao", "version"], capture_output=True, text=True, check=False
    )
    match = re.search(r"version (\S+)", completed.stdout + completed.stderr)
    return match[1] if match else None


INSTALLED_CDRDAO_VERSION = _installed_cdrdao_version()

on_recorded_cdrdao = pytest.mark.skipif(
    HAVE_CDRDAO and INSTALLED_CDRDAO_VERSION != EXPECTED_CDRDAO_VERSION,
    reason=f"recorded with cdrdao {EXPECTED_CDRDAO_VERSION}, "
    f"cdrdao {INSTALLED_CDRDAO_VERSION} is installed",
)

MEDIA_MINUTES = 20
#: Seconds a single ``cdrdao show-toc`` run may take.
CDRDAO_TIMEOUT = 30

T = 'TRACK AUDIO\nFILE "a.wav" 0\n'


def _indexes(count: int) -> str:
    return "".join(
        f"INDEX 00:{1 + second // 60:02d}:{second % 60:02d}\n"
        for second in range(count)
    )


def _binary(count: int) -> str:
    return ", ".join(["1"] * count)


# (id, source, cdrdao accepts it) - every expectation here was observed from
# `cdrdao show-toc` rather than assumed.
CASES: list[tuple[str, str, bool]] = [
    ("minimal", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n', True),
    ("no-disc-type", T, True),
    ("catalog-ok", f'CD_DA\nCATALOG "1234567890123"\n{T}', True),
    ("catalog-short", f'CD_DA\nCATALOG "123"\n{T}', False),
    ("catalog-non-digit", f'CD_DA\nCATALOG "123456789012X"\n{T}', False),
    ("isrc-ok", 'CD_DA\nTRACK AUDIO\nISRC "DEXXX9800001"\nFILE "a.wav" 0\n', True),
    (
        "isrc-digit-country",
        'CD_DA\nTRACK AUDIO\nISRC "12XXX9800001"\nFILE "a.wav" 0\n',
        True,
    ),
    (
        "isrc-lower-case",
        'CD_DA\nTRACK AUDIO\nISRC "dexxx9800001"\nFILE "a.wav" 0\n',
        False,
    ),
    (
        "isrc-dashed",
        'CD_DA\nTRACK AUDIO\nISRC "DE-XXX-98-00001"\nFILE "a.wav" 0\n',
        False,
    ),
    (
        "isrc-alpha-year",
        'CD_DA\nTRACK AUDIO\nISRC "DEXXXAB00001"\nFILE "a.wav" 0\n',
        False,
    ),
    ("msf-second-60", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART 00:60:00\n', False),
    ("msf-frame-75", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART 00:02:75\n', False),
    (
        "msf-wide-fields",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART 000:002:000\n',
        True,
    ),
    (
        "language-without-map",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "x" }} }}\n{T}',
        True,
    ),
    (
        "language-number-8",
        f"CD_DA\nCD_TEXT {{ LANGUAGE_MAP {{ 8 : EN }} }}\n{T}",
        False,
    ),
    (
        "language-code-256",
        f"CD_DA\nCD_TEXT {{ LANGUAGE_MAP {{ 0: 256 }} }}\n{T}",
        False,
    ),
    ("block-number-8", f"CD_DA\nCD_TEXT {{ LANGUAGE 8 {{ }} }}\n{T}", False),
    (
        "language-map-numeric",
        f'CD_DA\nCD_TEXT {{ LANGUAGE_MAP {{ 0: 9 }} LANGUAGE 0 {{ TITLE "x" }} }}\n{T}',
        True,
    ),
    (
        "binary-byte-256",
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TOC_INFO1 {{ 0, 256 }} }} }}\n{T}",
        False,
    ),
    (
        "binary-empty",
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TOC_INFO1 {{ }} }} }}\n{T}",
        True,
    ),
    (
        "binary-at-limit",
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TOC_INFO1 {{ {_binary(3072)} }} }} }}\n{T}",
        True,
    ),
    (
        "binary-over-limit",
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TOC_INFO1 {{ {_binary(3073)} }} }} }}\n{T}",
        False,
    ),
    (
        "track-cd-text-genre",
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE 0 {\nGENRE { 1 } } }\nFILE "a.wav" 0\n',
        False,
    ),
    # cdrdao 1.2.6 drops an empty string before it checks where it may appear.
    # cdrdao's master branch keeps it, and so rejects this.
    (
        "track-cd-text-empty-genre",
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE 0 { GENRE "" } }\nFILE "a.wav" 0\n',
        True,
    ),
    (
        "track-cd-text-disc-id",
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE 0 { DISC_ID "x" } }\nFILE "a.wav" 0\n',
        True,
    ),
    (
        "track-cd-text-language-map",
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE_MAP { 0: 9 } }\nFILE "a.wav" 0\n',
        False,
    ),
    ("pregap-zero", 'CD_DA\nTRACK AUDIO\nPREGAP 0:0:0\nFILE "a.wav" 0\n', False),
    (
        "pregap-and-start",
        'CD_DA\nTRACK AUDIO\nPREGAP 0:2:0\nFILE "a.wav" 0\nSTART 0:1:0\n',
        False,
    ),
    (
        "pregap-after-content",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nPREGAP 0:2:0\n',
        False,
    ),
    ("pregap-then-silence", "CD_DA\nTRACK AUDIO\nPREGAP 0:2:0\nSILENCE 0:5:0\n", True),
    # On an audio track PREGAP is inserted as silence, which is audio data.
    (
        "pregap-then-datafile",
        'CD_DA\nTRACK AUDIO\nPREGAP 0:2:0\nDATAFILE "d" 0:5:0\n',
        False,
    ),
    ("pregap-then-zero", "CD_DA\nTRACK AUDIO\nPREGAP 0:2:0\nZERO 0:5:0\n", False),
    (
        "data-pregap-then-datafile",
        'CD_ROM\nTRACK MODE1\nPREGAP 0:2:0\nDATAFILE "d"\n',
        True,
    ),
    (
        "two-starts",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART 0:1:0\nSTART 0:2:0\n',
        False,
    ),
    (
        "two-ends",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0 0:10:0\nEND 0:8:0\nEND 0:9:0\n',
        False,
    ),
    (
        "start-after-index",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nINDEX 0:2:0\nSTART 0:1:0\n',
        False,
    ),
    (
        "index-before-content",
        'CD_DA\nTRACK AUDIO\nINDEX 0:2:0\nFILE "a.wav" 0\n',
        False,
    ),
    ("index-at-start", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nINDEX 00:00:00\n', False),
    ("98-indexes", f'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n{_indexes(98)}', True),
    ("99-indexes", f'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n{_indexes(99)}', False),
    ("silence-zero-length", 'CD_DA\nTRACK AUDIO\nSILENCE 0\nFILE "a.wav" 0\n', False),
    ("zero-zero-length", 'CD_ROM\nTRACK MODE1\nDATAFILE "d"\nZERO 0\n', False),
    ("zero-on-audio-track", 'CD_DA\nTRACK AUDIO\nZERO 0:2:0\nFILE "a.wav" 0\n', False),
    ("file-then-zero", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0 0:5:0\nZERO 0:2:0\n', False),
    # FIFO data counts as data, not audio, so it cannot join a FILE either.
    (
        "file-then-fifo",
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0 0:5:0\nFIFO "p" 0:2:0\n',
        False,
    ),
    (
        "silence-on-data-track",
        'CD_ROM\nTRACK MODE1\nSILENCE 0:2:0\nDATAFILE "d"\n',
        False,
    ),
    ("file-on-data-track", 'CD_ROM\nTRACK MODE1\nFILE "a.wav" 0\n', False),
    ("file-with-sub-channel", 'CD_DA\nTRACK AUDIO RW\nFILE "a.wav" 0\n', False),
    ("no-tracks", "CD_DA\n", False),
    ("no-tracks-no-newline", "CD_DA", False),
    ("no-content-statement", "CD_DA\nTRACK AUDIO\n", False),
    ("lower-case-keywords", 'cd_da\ntrack audio\nfile "a.wav" 0\n', False),
    ("negative-number", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" -1\n', False),
    ("stray-character", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n$\n', False),
    ("file-without-start", 'CD_DA\nTRACK AUDIO\nFILE "a.wav"\n', False),
    ("unterminated-string", 'CD_DA\nTRACK AUDIO\nFILE "a.wav 0\n', False),
    ("stray-string", 'CD_DA\n"x"\nTRACK AUDIO\nFILE "a.wav" 0\n', False),
    ("mode0-track", 'CD_ROM\nTRACK MODE0\nDATAFILE "d"\n', False),
    ("first-track-no", f"CD_DA\nFIRST_TRACK_NO 5\n{T}", True),
    ("first-track-no-0", f"CD_DA\nFIRST_TRACK_NO 0\n{T}", False),
    ("first-track-no-100", f"CD_DA\nFIRST_TRACK_NO 100\n{T}", False),
    ("cd-i", 'CD_I\nTRACK AUDIO\nFILE "a.wav" 0\n', True),
    ("audiofile-swap", 'CD_DA\nTRACK AUDIO\nAUDIOFILE "a.wav" SWAP 0\n', True),
    ("file-offset", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" #0 0 0:5:0\n', True),
    ("datafile-offset", 'CD_ROM\nTRACK MODE1\nDATAFILE "d" #2048 0:5:0\n', True),
    ("sub-channel-rw", 'CD_ROM\nTRACK MODE1 RW\nDATAFILE "d"\n', True),
    ("zero-with-mode", 'CD_ROM\nTRACK MODE1\nDATAFILE "d"\nZERO MODE0 0:2:0\n', True),
    ("end-statement", 'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nEND 0:8:0\n', True),
    # cdrdao only cross-checks track modes against the disc type when writing.
    ("mode1-under-cd-da", 'CD_DA\nTRACK MODE1\nDATAFILE "d"\n', True),
    ("audio-under-cd-rom", 'CD_ROM\nTRACK AUDIO\nFILE "a.wav" 0\n', True),
    # Audio-only flags on a data track are tolerated.
    (
        "pre-emphasis-on-data",
        'CD_ROM\nTRACK MODE1\nNO PRE_EMPHASIS\nDATAFILE "d"\n',
        True,
    ),
    (
        "pregap-on-first-track",
        'CD_DA\nTRACK AUDIO\nPREGAP 0:2:0\nFILE "a.wav" 0\n',
        True,
    ),
    ("hundred-tracks", "CD_DA\n" + 'TRACK AUDIO\nFILE "a.wav" 0 0:5:0\n' * 100, True),
    (
        "duplicate-cd-text-item",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a" TITLE "b" }} }}\n{T}',
        True,
    ),
    (
        "repeated-language-block",
        (
            f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a" }} '
            f'LANGUAGE 0 {{ PERFORMER "b" }} }}\n{T}'
        ),
        True,
    ),
    (
        "upc-ean-and-isrc",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ UPC_EAN "1" ISRC "2" }} }}\n{T}',
        True,
    ),
    # A backslash may only introduce a quote, another backslash or three
    # digits; cdrdao reports "Illegal token: \" for anything else.
    ("escape-quote", f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\"b" }} }}\n{T}', True),
    (
        "escape-backslash",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\\\b" }} }}\n{T}',
        True,
    ),
    (
        "escape-octal",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\101b" }} }}\n{T}',
        True,
    ),
    (
        "escape-non-octal-digits",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\999" }} }}\n{T}',
        True,
    ),
    (
        "escape-above-byte",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\777" }} }}\n{T}',
        True,
    ),
    (
        "escape-lone-backslash",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\b" }} }}\n{T}',
        False,
    ),
    (
        "escape-short-octal",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\\12b" }} }}\n{T}',
        False,
    ),
    (
        "escape-mixed-with-utf8",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "é\\351" }} }}\n{T}',
        False,
    ),
    # An escaped backslash before three digits still reads as an octal escape.
    (
        "escape-backslash-digits-with-utf8",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "é\\\\123" }} }}\n{T}',
        False,
    ),
    ("tab-in-string", f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\tb" }} }}\n{T}', True),
    (
        "newline-in-string",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "a\nb" }} }}\n{T}',
        True,
    ),
    ("latin-text", f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "café" }} }}\n{T}', True),
    (
        "cjk-without-encoding",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "日本" }} }}\n{T}',
        False,
    ),
    (
        "cjk-with-ms-jis",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ ENCODING_MS_JIS TITLE "日本" }} }}\n{T}',
        True,
    ),
    # SIZE_INFO's first byte, 128 here, is the block's character code: MS-JIS.
    # cdrdao 1.2.6 ignores it and reads the block as ISO-8859-1; cdrdao's
    # master branch falls back on it when there is no ENCODING_*, and accepts.
    (
        "cjk-with-size-info-ms-jis",
        (
            f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "日本" '
            f"SIZE_INFO {{ 128, 1, 2 }} }} }}\n{T}"
        ),
        False,
    ),
    (
        "encoding-iso-8859-1",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ ENCODING_ISO_8859_1 TITLE "café" }} }}\n{T}',
        True,
    ),
    # cdrdao has no converter for Korean and falls back to ISO-8859-1.
    (
        "hangul-with-korean",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ ENCODING_KOREAN TITLE "한" }} }}\n{T}',
        False,
    ),
    (
        "latin-with-ascii",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ ENCODING_ASCII TITLE "café" }} }}\n{T}',
        False,
    ),
    (
        "encoding-on-track-ignored",
        (
            "CD_DA\nTRACK AUDIO\n"
            'CD_TEXT { LANGUAGE 0 { ENCODING_MS_JIS TITLE "日本" } }\n'
            'FILE "a.wav" 0\n'
        ),
        False,
    ),
    (
        "track-follows-disc-encoding",
        (
            "CD_DA\nCD_TEXT { LANGUAGE 0 { ENCODING_MS_JIS } }\n"
            'TRACK AUDIO\nCD_TEXT { LANGUAGE 0 { TITLE "日本" } }\nFILE "a.wav" 0\n'
        ),
        True,
    ),
    (
        "encoding-after-item",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "x" ENCODING_ASCII }} }}\n{T}',
        False,
    ),
    (
        "encoding-twice",
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ ENCODING_ASCII ENCODING_MS_JIS }} }}\n{T}",
        False,
    ),
    ("cd-text-closed", f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ CLOSED "x" }} }}\n{T}', True),
    (
        "track-cd-text-closed",
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE 0 { CLOSED "x" } }\nFILE "a.wav" 0\n',
        True,
    ),
    (
        "unknown-cd-text-item",
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ FOO "x" }} }}\n{T}',
        False,
    ),
]

# cdrdao's parser looks ahead differently, so for these syntax errors it names
# another token, or another line, than ours does. The verdict still agrees.
SYNTAX_ERROR_REPORTED_ELSEWHERE = {
    # cdrdao: syntax error at "0", on the FILE line.
    "pregap-after-content",
    # cdrdao: syntax error at "LANGUAGE_MAP"; ours stops at the "_" after
    # LANGUAGE, since only a LANGUAGE block may follow there.
    "track-cd-text-language-map",
}


class Report(NamedTuple):
    """The first error cdrdao reports, as ``ERROR: file:line: message``."""

    line: int | None
    message: str


_ERROR_RE = re.compile(r"ERROR: (?:[^:\n]+\.toc:(?P<line>\d+): )?(?P<message>.*)")


@pytest.fixture(scope="module")
def media_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory holding the media the test toc-files refer to.

    The files are sparse: cdrdao only needs their declared length, so nothing
    is actually written to disk beyond the WAVE headers.
    """
    directory = tmp_path_factory.mktemp("cdrdao")
    audio_bytes = 44100 * 4 * 60 * MEDIA_MINUTES
    _write_sparse_wave(directory / "a.wav", audio_bytes)
    for name in ("raw.cdr", "d", "t1", "t2", "t3", "t4", "t5", "t6"):
        _write_sparse(directory / name, audio_bytes)
    return directory


def _write_sparse(path: Path, size: int) -> None:
    with path.open("wb") as handle:
        handle.truncate(size)


def _write_sparse_wave(path: Path, data_size: int) -> None:
    header = (
        b"RIFF"
        + (36 + data_size).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (2).to_bytes(2, "little")
        + (44100).to_bytes(4, "little")
        + (44100 * 4).to_bytes(4, "little")
        + (4).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + data_size.to_bytes(4, "little")
    )
    with path.open("wb") as handle:
        handle.write(header)
        handle.truncate(len(header) + data_size)


def show_toc(source: str, directory: Path, name: str, *options: str) -> str:
    """Run ``cdrdao show-toc`` on ``source`` and return everything it printed."""
    path = directory / f"{name}.toc"
    path.write_text(source, encoding="utf-8")
    try:
        completed = subprocess.run(
            ["cdrdao", "show-toc", *options, path.name],
            cwd=directory,
            capture_output=True,
            check=False,
            # A FIFO statement makes cdrdao wait for a writer that never comes.
            timeout=CDRDAO_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"cdrdao show-toc did not finish on {name} within {CDRDAO_TIMEOUT}s"
        )
    output = (completed.stdout + completed.stderr).decode("utf-8", "replace")
    assert completed.returncode == 0 or _ERROR_RE.search(output), output
    return output


def cdrdao_report(source: str, directory: Path, name: str) -> Report | None:
    """cdrdao's first error for ``source``, or ``None`` when it accepts it."""
    output = show_toc(source, directory, name)
    # An error cdrdao meets after parsing, such as CD-TEXT it cannot encode,
    # is reported without failing the command, so the ERROR line decides.
    for output_line in output.splitlines():
        match = _ERROR_RE.match(output_line)
        if match is not None:
            line = match["line"]
            return Report(
                int(line) if line is not None else None, match["message"].strip()
            )
    return None


def tocparser_report(source: str) -> TocParseError | TocValidationError | None:
    try:
        parse(source)
    except (TocParseError, TocValidationError) as error:
        return error
    return None


def assert_same_report(
    ours: TocParseError | TocValidationError, theirs: Report, case: str
) -> None:
    if isinstance(ours, TocParseError) and case in SYNTAX_ERROR_REPORTED_ELSEWHERE:
        return
    # cdrdao reports line 0 for a FIFO, whose statement records no line.
    if theirs.line:
        assert ours.line == theirs.line
    if theirs.message.startswith("CD-TEXT: Unable to encode"):
        # cdrdao's message leaves out the text it could not encode.
        assert ours.message.startswith("CD-TEXT: Unable to encode")
    else:
        # A cdrdao syntax error goes on to list the tokens it expected.
        assert theirs.message.startswith(ours.message)


def test_installed_cdrdao_is_the_recorded_version() -> None:
    assert INSTALLED_CDRDAO_VERSION == EXPECTED_CDRDAO_VERSION, (
        f"these expectations were recorded with cdrdao {EXPECTED_CDRDAO_VERSION}, "
        f"but cdrdao {INSTALLED_CDRDAO_VERSION} is installed: "
        "re-run this module against it, "
        "update the cases and rules that changed, then EXPECTED_CDRDAO_VERSION"
    )


@on_recorded_cdrdao
@pytest.mark.parametrize(
    ("name", "source", "expected"),
    [pytest.param(*case, id=case[0]) for case in CASES],
)
def test_matches_cdrdao(
    name: str, source: str, expected: bool, media_dir: Path
) -> None:
    theirs = cdrdao_report(source, media_dir, name)
    assert (theirs is None) is expected, (
        f"the recorded expectation no longer matches cdrdao: {theirs}"
    )
    ours = tocparser_report(source)
    assert (ours is None) is expected, ours
    if ours is not None and theirs is not None:
        assert_same_report(ours, theirs, name)


@on_recorded_cdrdao
def test_fixtures_are_accepted_by_cdrdao(fixture_file: Path, media_dir: Path) -> None:
    """The hand-written fixtures must be files cdrdao would accept too.

    Without this they would only prove that our own grammar is self
    consistent. ``fifo_and_end`` is excluded because cdrdao would block
    reading the named pipe.
    """
    if fixture_file.stem == "fifo_and_end":
        pytest.skip("cdrdao would block reading the FIFO")
    source = fixture_file.read_text()
    assert cdrdao_report(source, media_dir, f"fixture_{fixture_file.stem}") is None
    assert tocparser_report(source) is None


@on_recorded_cdrdao
def test_cdrdao_reads_written_fixtures_as_it_reads_the_originals(
    fixture_file: Path, media_dir: Path
) -> None:
    """What ``dumps`` writes must mean to cdrdao what the original meant.

    ``show-toc -v 4`` prints the values cdrdao keeps, CD-TEXT included, so a
    value that tocparser loses or changes on the way through shows up as a
    difference. The corpus needs no such check: it comes back byte for byte.
    """
    if fixture_file.stem == "fifo_and_end":
        pytest.skip("cdrdao would block reading the FIFO")
    source = fixture_file.read_text()
    name = f"written_{fixture_file.stem}"
    original = show_toc(source, media_dir, name, "-v", "4")
    written = show_toc(dumps(parse(source)), media_dir, name, "-v", "4")
    for output in (original, written):
        assert not any(map(_ERROR_RE.match, output.splitlines())), output
    assert written == original
