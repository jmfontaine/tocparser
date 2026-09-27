"""Invalid input must be rejected the way cdrdao rejects it.

Each message and line number here is the one ``cdrdao show-toc`` 1.2.6 reports;
``test_cdrdao_oracle.py`` checks them against cdrdao again when it is installed.
"""

from __future__ import annotations

import pytest

from tocparser import TocParseError, TocValidationError, parse

MINIMAL_TRACK = 'TRACK AUDIO\nFILE "a.wav" 0\n'


def expect_validation_error(
    source: str, *, line: int, message: str
) -> TocValidationError:
    with pytest.raises(TocValidationError) as info:
        parse(source, filename="x.toc")
    assert (info.value.line, info.value.message) == (line, message)
    assert str(info.value) == f"x.toc:{line}: {message}"
    return info.value


def expect_parse_error(source: str, *, line: int, message: str) -> None:
    with pytest.raises(TocParseError) as info:
        parse(source, filename="x.toc")
    assert (info.value.line, info.value.message) == (line, message)


@pytest.mark.parametrize(
    "catalog", ["", "123", "123456789012", "12345678901234", "123456789012X"]
)
def test_catalog_must_be_thirteen_digits(catalog: str) -> None:
    expect_validation_error(
        f'CD_DA\nCATALOG "{catalog}"\n{MINIMAL_TRACK}',
        line=2,
        message=f"Illegal catalog number: {catalog}.",
    )


@pytest.mark.parametrize(
    "isrc",
    [
        "DEXXX980000",  # too short
        "DEXXX98000012",  # too long
        "dexxx9800001",  # lower case
        "DE-XXX-98-00001",  # dashed, only valid inside CD-TEXT
        "DEXXXAB00001",  # letters in the year
        "DEXXX98ABCDE",  # letters in the serial number
    ],
)
def test_isrc_format(isrc: str) -> None:
    expect_validation_error(
        f'CD_DA\nTRACK AUDIO\nISRC "{isrc}"\nFILE "a.wav" 0\n',
        line=3,
        message=f"Illegal ISRC code: {isrc}.",
    )


@pytest.mark.parametrize("isrc", ["DEXXX9800001", "12XXX9800001", "12A4B9800001"])
def test_valid_isrc_is_accepted(isrc: str) -> None:
    assert (
        parse(f'CD_DA\nTRACK AUDIO\nISRC "{isrc}"\nFILE "a.wav" 0\n').tracks[0].isrc
        == isrc
    )


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("00:60:00", "Illegal second field: 60"),
        ("00:02:75", "Illegal fraction field: 75"),
    ],
)
def test_msf_field_ranges(value: str, message: str) -> None:
    expect_validation_error(
        f'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART {value}\n', line=4, message=message
    )


@pytest.mark.parametrize("number", [0, 100])
def test_first_track_number_range(number: int) -> None:
    expect_validation_error(
        f"CD_DA\nFIRST_TRACK_NO {number}\n{MINIMAL_TRACK}",
        line=2,
        message=f"Illegal track number: {number}",
    )


def test_first_track_number_may_be_99() -> None:
    assert parse(f"CD_DA\nFIRST_TRACK_NO 99\n{MINIMAL_TRACK}").first_track_number == 99


def test_language_map_number_range() -> None:
    expect_validation_error(
        f"CD_DA\nCD_TEXT {{\nLANGUAGE_MAP {{ 8 : EN }}\n}}\n{MINIMAL_TRACK}",
        line=3,
        message="Invalid language number, allowed range: [0..7].",
    )


def test_language_block_number_range() -> None:
    expect_validation_error(
        f"CD_DA\nCD_TEXT {{\nLANGUAGE 8 {{ }}\n}}\n{MINIMAL_TRACK}",
        line=3,
        message="Invalid block number, allowed range: [0..7].",
    )


def test_language_code_range() -> None:
    expect_validation_error(
        f"CD_DA\nCD_TEXT {{\nLANGUAGE_MAP {{ 0:\n256 }}\n}}\n{MINIMAL_TRACK}",
        line=4,
        message="Invalid language code, allowed range: [0..255].",
    )


def test_binary_data_byte_range() -> None:
    expect_validation_error(
        f"CD_DA\nCD_TEXT {{\nLANGUAGE 0 {{\nTOC_INFO1 {{ 0,\n256 }}\n"
        f"}}\n}}\n{MINIMAL_TRACK}",
        line=5,
        message="Illegal binary data: 256",
    )


def test_binary_data_length_limit() -> None:
    values = ",\n".join(["1"] * 3073)
    expect_validation_error(
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TOC_INFO1 {{ {values} }} }} }}\n"
        f"{MINIMAL_TRACK}",
        line=3074,
        message="Binary data exceeds maximum length (3072).",
    )


@pytest.mark.parametrize(
    "source",
    [
        'CD_DA\nTRACK AUDIO\nSILENCE 0\nFILE "a.wav" 0\n',
        'CD_DA\nTRACK AUDIO\nSILENCE 00:00:00\nFILE "a.wav" 0\n',
    ],
)
def test_zero_length_silence(source: str) -> None:
    expect_validation_error(source, line=3, message="Length of silence is 0.")


def test_zero_length_zero() -> None:
    expect_validation_error(
        'CD_ROM\nTRACK MODE1\nDATAFILE "d"\nZERO 0\n',
        line=4,
        message="Length of zero data is 0.",
    )


def test_zero_length_pregap() -> None:
    expect_validation_error(
        'CD_DA\nTRACK AUDIO\nPREGAP 00:00:00\nFILE "a.wav" 0\n',
        line=3,
        message="Length of pregap is zero.",
    )


def test_start_may_only_be_given_once() -> None:
    error = expect_validation_error(
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nSTART 00:01:00\nSTART 00:02:00\n',
        line=5,
        message="Track start (end of pre-gap) already defined.",
    )
    assert error.loc == ("tracks", 0, "statements", 2)


def test_end_may_only_be_given_once() -> None:
    expect_validation_error(
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nEND 00:01:00\nEND 00:02:00\n',
        line=5,
        message="Track end (start of post-gap) already defined.",
    )


def test_pregap_and_start_are_mutually_exclusive() -> None:
    expect_validation_error(
        'CD_DA\nTRACK AUDIO\nPREGAP 00:02:00\nFILE "a.wav" 0\nSTART 00:01:00\n',
        line=5,
        message="Track start (end of pre-gap) already defined.",
    )


@pytest.mark.parametrize(
    ("statement", "name"),
    [('FILE "a.wav" 0', "FILE/AUDIOFILE"), ("SILENCE 00:02:00", "SILENCE")],
)
def test_audio_statements_are_rejected_on_data_tracks(
    statement: str, name: str
) -> None:
    expect_validation_error(
        f'CD_ROM\nTRACK MODE1\n{statement}\nDATAFILE "d" 00:04:00\n',
        line=3,
        message=f"{name} statements are only allowed for audio tracks.",
    )


def test_audio_statements_are_rejected_with_a_sub_channel_mode() -> None:
    expect_validation_error(
        'CD_DA\nTRACK AUDIO RW\nFILE "a.wav" 0\n',
        line=3,
        message="FILE/AUDIOFILE statements are only allowed for audio tracks "
        "without sub-channel mode.",
    )


@pytest.mark.parametrize(
    "source",
    [
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nZERO 00:02:00\n',
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nFIFO "p" 00:02:00\n',
        # A PREGAP on an audio track is inserted as silence, so it is audio.
        'CD_DA\nTRACK AUDIO\nPREGAP 00:02:00\nDATAFILE "d" 00:05:00\n',
        "CD_DA\nTRACK AUDIO\nPREGAP 00:02:00\nZERO 00:05:00\n",
    ],
    ids=["file-zero", "file-fifo", "pregap-datafile", "pregap-zero"],
)
def test_audio_and_data_statements_may_not_be_mixed(source: str) -> None:
    expect_validation_error(
        source,
        line=4,
        message=(
            "Mixing of FILE/AUDIOFILE/SILENCE and DATAFILE/ZERO statements not allowed."
        ),
    )


def test_pregap_of_a_data_track_is_data() -> None:
    track = parse('CD_ROM\nTRACK MODE1\nPREGAP 00:02:00\nDATAFILE "d"\n').tracks[0]
    assert track.pregap is not None


@pytest.mark.parametrize(
    "item", ["GENRE { 1 }", "TOC_INFO1 { 1 }", "TOC_INFO2 { 1 }", "SIZE_INFO { 1 }"]
)
def test_disc_only_cd_text_items_are_rejected_on_tracks(item: str) -> None:
    expect_validation_error(
        f"CD_DA\nTRACK AUDIO\nCD_TEXT {{\nLANGUAGE 0 {{\n{item}\n}}\n}}\n"
        'FILE "a.wav" 0\n',
        line=5,
        message="Invalid CD-TEXT item for a track.",
    )


def test_empty_disc_only_item_is_ignored_on_a_track() -> None:
    """cdrdao 1.2.6 drops an empty string before checking where it may appear."""
    parse('CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE 0 { GENRE "" } }\nFILE "a.wav" 0\n')


def test_disc_id_is_allowed_on_a_track() -> None:
    """cdrdao only rejects pack types 0x87..0x89 and 0x8f, so DISC_ID passes."""
    toc = parse(
        "CD_DA\nTRACK AUDIO\n"
        'CD_TEXT { LANGUAGE 0 { DISC_ID "XY12345" } }\nFILE "a.wav" 0\n'
    )
    assert toc.tracks[0].cd_text is not None
    assert toc.tracks[0].cd_text[0].disc_id == "XY12345"


def test_index_at_start_of_track() -> None:
    expect_validation_error(
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nINDEX 00:02:00\nINDEX 00:00:00\n',
        line=5,
        message="Index at start of track.",
    )


def test_too_many_index_increments() -> None:
    indexes = "\n".join(f"INDEX 00:{1 + i // 60:02d}:{i % 60:02d}" for i in range(99))
    expect_validation_error(
        f'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n{indexes}\n',
        line=102,
        message="More than 98 index increments.",
    )


def test_escapes_may_not_be_mixed_with_utf8() -> None:
    expect_validation_error(
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "é\\351" }} }}\n{MINIMAL_TRACK}',
        line=2,
        message="Illegal mixed UTF-8 and binary.",
    )


def test_escaped_backslash_before_digits_is_an_escape_too() -> None:
    expect_validation_error(
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "é\\\\123" }} }}\n{MINIMAL_TRACK}',
        line=2,
        message="Illegal mixed UTF-8 and binary.",
    )


@pytest.mark.parametrize(
    ("block", "title"),
    [
        ("", "日本"),  # ISO-8859-1 by default
        ("ENCODING_ASCII", "café"),
        # cdrdao has no converter for Korean or Mandarin and uses ISO-8859-1.
        ("ENCODING_KOREAN", "한"),
    ],
)
def test_cd_text_must_fit_its_encoding(block: str, title: str) -> None:
    error = expect_validation_error(
        f'CD_DA\nCD_TEXT {{\nLANGUAGE 0 {{ {block}\nTITLE "{title}" }} }}\n'
        f"{MINIMAL_TRACK}",
        line=4,
        message=f'CD-TEXT: Unable to encode "{title}" into compatible format',
    )
    assert error.loc == ("cd_text", "blocks", 0, "items", "TITLE")


@pytest.mark.parametrize(
    ("block", "raw", "message"),
    [
        (
            "ENCODING_MS_JIS",
            r"\201",
            "CD-TEXT: Illegal byte sequence for ENCODING_MS_JIS.",
        ),
        (
            "ENCODING_ASCII",
            r"caf\351",
            'CD-TEXT: Unable to encode "café" into compatible format',
        ),
    ],
)
def test_escaped_bytes_must_be_text_in_their_encoding(
    block: str, raw: str, message: str
) -> None:
    """A deliberate difference: cdrdao keeps such bytes, warning at most.

    A value that is not text in its block's encoding cannot be held as a
    string, nor written back in a form cdrdao would read the same way.
    """
    expect_validation_error(
        f'CD_DA\nCD_TEXT {{\nLANGUAGE 0 {{ {block}\nTITLE "{raw}" }} }}\n'
        f"{MINIMAL_TRACK}",
        line=4,
        message=message,
    )


def test_track_cd_text_follows_the_disc_encoding() -> None:
    """An encoding on a track block is ignored; the disc's block decides."""
    source = (
        "CD_DA\nTRACK AUDIO\nCD_TEXT {\nLANGUAGE 0 { ENCODING_MS_JIS\n"
        'TITLE "日本" } }\nFILE "a.wav" 0\n'
    )
    error = expect_validation_error(
        source,
        line=5,
        message='CD-TEXT: Unable to encode "日本" into compatible format',
    )
    assert error.loc == ("tracks", 0, "cd_text", "blocks", 0, "items", "TITLE")


@pytest.mark.parametrize(
    ("source", "line", "message"),
    [
        ("CD_DA\n", 2, 'syntax error at "EOF"'),
        ("CD_DA", 1, 'syntax error at "EOF"'),
        ("CD_DA\nTRACK AUDIO\n", 3, 'syntax error at "EOF"'),
        ('CD_DA\nTRACK AUDIO\nFILE "a.wav"\n', 4, 'syntax error at "EOF"'),
        ('CD_DA\nTRACK AUDIO\nFILE "a.wav 0\n', 3, 'syntax error at "EOF"'),
        # cdrdao names a string by its opening quote.
        ('CD_DA\n"x"\nTRACK AUDIO\nFILE "a.wav" 0\n', 2, 'syntax error at """'),
        ('cd_da\nTRACK AUDIO\nFILE "a.wav" 0\n', 1, "Illegal token: c"),
        ('CD_DA\nTRACK AUDIO\nFILE "a.wav" -1\n', 3, "Illegal token: -"),
        ('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n$\n', 4, "Illegal token: $"),
        (
            f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE\n"a\\b" }} }}\n{MINIMAL_TRACK}',
            3,
            "Illegal token: \\",
        ),
        (
            'CD_DA\nTRACK AUDIO\nINDEX 00:02:00\nFILE "a.wav" 0\n',
            3,
            'syntax error at "INDEX"',
        ),
        (
            'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nINDEX 00:02:00\nSTART\n',
            5,
            'syntax error at "START"',
        ),
        ('CD_ROM\nTRACK MODE0\nDATAFILE "d" 00:04:00\n', 2, 'syntax error at "MODE0"'),
        (
            (
                f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ TITLE "x" ENCODING_ASCII }} }}\n'
                f"{MINIMAL_TRACK}"
            ),
            2,
            'syntax error at "ENCODING_ASCII"',
        ),
    ],
    ids=[
        "no-tracks",
        "no-tracks-no-newline",
        "no-data-statement",
        "file-without-start",
        "unterminated-string",
        "stray-string",
        "lower-case-keywords",
        "negative-number",
        "stray-character",
        "lone-backslash",
        "index-before-content",
        "start-after-index",
        "mode0-track",
        "encoding-after-item",
    ],
)
def test_syntax_errors(source: str, line: int, message: str) -> None:
    expect_parse_error(source, line=line, message=message)


@pytest.mark.parametrize(
    "source",
    [
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nPREGAP 00:02:00\n',  # PREGAP comes first
        'CD_DA\nTRACK AUDIO\nCD_TEXT { LANGUAGE_MAP { 0: 9 } }\nFILE "a.wav" 0\n',
        # header comes first
        'CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nCATALOG "1234567890123"\n',
    ],
    ids=["pregap-after-content", "language-map-in-track", "catalog-after-track"],
)
def test_other_syntax_errors_are_rejected(source: str) -> None:
    """cdrdao looks ahead differently here, so only the verdict is compared."""
    with pytest.raises(TocParseError):
        parse(source)


def test_error_without_a_filename_still_reports_the_line() -> None:
    with pytest.raises(TocValidationError) as info:
        parse(f'CD_DA\nCATALOG "1"\n{MINIMAL_TRACK}')
    assert str(info.value) == "2: Illegal catalog number: 1."
