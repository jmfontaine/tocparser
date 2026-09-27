"""Tests for rendering models back to TOC text."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.paths import FIXTURES_DIR
from tocparser import (
    CdText,
    CdTextBlock,
    CdTextItemName,
    DiscType,
    File,
    Msf,
    Toc,
    TocValidationError,
    Track,
    TrackMode,
    dump,
    dumps,
    parse,
    parse_file,
)
from tocparser.serializer import escape


def test_minimal_output() -> None:
    toc = Toc(
        tracks=[
            Track(mode=TrackMode.AUDIO, statements=[File(filename="a.wav", start=0)])
        ]
    )
    assert dumps(toc) == 'CD_DA\n\n\n// Track 1\nTRACK AUDIO\nFILE "a.wav" 0\n\n'


def test_absent_flags_are_not_invented() -> None:
    assert "COPY" not in dumps(parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n'))


def test_flag_order_matches_cdrdao() -> None:
    source = (
        "CD_DA\nTRACK AUDIO\nTWO_CHANNEL_AUDIO\nNO PRE_EMPHASIS\nNO COPY\n"
        'ISRC "DEXXX9800001"\nFILE "a.wav" 0\n'
    )
    body = dumps(parse(source)).splitlines()
    assert body[body.index("TRACK AUDIO") : body.index("TRACK AUDIO") + 5] == [
        "TRACK AUDIO",
        "NO COPY",
        "NO PRE_EMPHASIS",
        "TWO_CHANNEL_AUDIO",
        'ISRC "DEXXX9800001"',
    ]


def test_msf_values_are_normalized_but_scalars_are_not() -> None:
    output = dumps(parse('CD_DA\nTRACK AUDIO\nFILE "a.cdr" 1234567 1:2:3\n'))
    assert 'FILE "a.cdr" 1234567 01:02:03' in output


def test_track_numbering_follows_first_track_no() -> None:
    source = (
        'CD_DA\nFIRST_TRACK_NO 7\nTRACK AUDIO\nFILE "a.wav" 0\n'
        'TRACK AUDIO\nFILE "b.wav" 0\n'
    )
    output = dumps(parse(source))
    assert "FIRST_TRACK_NO 7" in output
    assert "// Track 7" in output
    assert "// Track 8" in output


def test_binary_values_match_cdrdao_layout() -> None:
    toc = Toc(
        cd_text=CdText(
            blocks={
                0: CdTextBlock(
                    items={CdTextItemName.SIZE_INFO: [1, 1, 6, 3, 10, 2] + [0] * 30}
                )
            }
        ),
        tracks=[
            Track(mode=TrackMode.AUDIO, statements=[File(filename="a.wav", start=0)])
        ],
    )
    lines = dumps(toc).splitlines()
    first = next(i for i, line in enumerate(lines) if "SIZE_INFO" in line)
    assert (
        lines[first] == "    SIZE_INFO { 1,  1,  6,  3, 10,  2,  0,  0,  0,  0,  0,  0,"
    )
    assert lines[first + 1].startswith(" " * 16 + "0,")
    assert lines[first + 2].endswith("}")


def test_empty_binary_value() -> None:
    toc = parse(
        'CD_DA\nCD_TEXT { LANGUAGE 0 { TOC_INFO1 {} } }\nTRACK AUDIO\nFILE "a.wav" 0\n'
    )
    assert "TOC_INFO1 {}" in dumps(toc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("plain", "plain"),
        ('a"b', r"a\"b"),
        # cdrdao rejects a backslash used for anything but an escape, so every
        # one of them has to be doubled...
        ("back\\slash", r"back\\slash"),
        ('a\\"b', r"a\\\"b"),
        # ...except before three digits, which cdrdao would read as an octal
        # escape even after a doubled backslash.
        ("a\\101b", r"a\134101b"),
        ("café\\x", r"café\\x"),
    ],
)
def test_escape(value: str, expected: str) -> None:
    assert escape(value) == expected


def test_non_ascii_text_cannot_hold_a_backslash_before_digits() -> None:
    with pytest.raises(TocValidationError, match="octal escape"):
        escape("café\\101")


@pytest.mark.parametrize(
    "value",
    [
        "plain",
        'a"b',
        "back\\slash",
        "a\\101b",
        "\\\\123",
        'a\\"b',
        "",
        "  spaced  ",
        "tab\tnew\nline",
        "café",
    ],
)
def test_string_values_survive_a_round_trip(value: str) -> None:
    toc = Toc(
        cd_text=CdText(blocks={0: CdTextBlock(items={CdTextItemName.TITLE: value})}),
        tracks=[
            Track(mode=TrackMode.AUDIO, statements=[File(filename="a.wav", start=0)])
        ],
    )
    restored = parse(dumps(toc))
    assert restored.cd_text is not None
    assert restored.cd_text[0].title == value


def test_encoding_is_written_at_the_top_of_its_block() -> None:
    output = dumps(parse_file(FIXTURES_DIR / "encodings.toc"))
    assert "  LANGUAGE 0 {\n    ENCODING_MS_JIS\n    TITLE" in output
    # Escaped bytes come back as the text they encode.
    assert '    PERFORMER "日本"' in output


def test_a_changed_model_is_validated_before_it_is_written() -> None:
    toc = parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n')
    toc.tracks[0].isrc = "bad"
    with pytest.raises(TocValidationError, match=r"Illegal ISRC code: bad\."):
        dumps(toc)
    toc.tracks[0].isrc = None
    toc.tracks[0].statements.clear()
    with pytest.raises(TocValidationError, match="no data statement"):
        dumps(toc)


def test_a_negative_number_is_never_written() -> None:
    """cdrdao's syntax has no sign, so ``FILE "a.wav" -1`` would not read back."""
    toc = parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n')
    statement = toc.tracks[0].statements[0]
    assert isinstance(statement, File)
    statement.start = -1
    with pytest.raises(ValidationError):
        dumps(toc)


def test_disc_type_collapses_to_the_effective_one() -> None:
    """Only the last disc flag has an effect, so only it is written back."""
    output = dumps(parse_file(FIXTURES_DIR / "repeated_disc_type.toc"))
    assert output.startswith("CD_DA\n")
    assert "CD_ROM" not in output


def test_hand_written_comments_are_dropped() -> None:
    source = '// a comment\nCD_DA\nTRACK AUDIO\nFILE "a.wav" 0 // here\n'
    output = dumps(parse(source))
    # The only comments written back are the ones cdrdao generates itself.
    assert [line for line in output.splitlines() if line.startswith("//")] == [
        "// Track 1"
    ]
    assert "// here" not in output
    assert "// a comment" not in output


def test_data_lengths_are_annotated_like_cdrdao() -> None:
    """``TrackData::print`` appends the byte count to every data length."""
    toc = parse('CD_ROM\nTRACK MODE1\nDATAFILE "d" 12:03:45\n')
    # 54270 frames x 2048 bytes per MODE1 sector.
    assert 'DATAFILE "d" 12:03:45 // length in bytes: 111144960' in dumps(toc)


def test_data_length_annotation_uses_the_track_block_size() -> None:
    toc = parse('CD_ROM_XA\nTRACK MODE2_FORM2\nDATAFILE "d" 00:01:00\n')
    assert f"// length in bytes: {75 * 2324}" in dumps(toc)


def test_scalar_data_length_is_already_a_byte_count() -> None:
    toc = parse('CD_ROM\nTRACK MODE1\nDATAFILE "d" 4096\n')
    assert 'DATAFILE "d" 4096 // length in bytes: 4096' in dumps(toc)


def test_omitted_data_length_is_not_annotated() -> None:
    assert dumps(parse('CD_ROM\nTRACK MODE1\nDATAFILE "d"\n')).count("//") == 1


def test_fifo_is_annotated_only_when_block_aligned() -> None:
    aligned = dumps(parse('CD_ROM\nTRACK MODE1\nFIFO "p" 00:01:00\n'))
    assert f'FIFO "p" 00:01:00 // length in bytes: {75 * 2048}' in aligned
    assert 'FIFO "p" 1234\n' in dumps(parse('CD_ROM\nTRACK MODE1\nFIFO "p" 1234\n'))


def test_dump_writes_a_file(tmp_path: Path) -> None:
    toc = parse_file(FIXTURES_DIR / "man_minimal.toc")
    target = tmp_path / "out.toc"
    dump(toc, target)
    assert parse_file(target) == toc


def test_disc_type_is_always_written() -> None:
    assert dumps(parse('TRACK AUDIO\nFILE "a.wav" 0\n')).startswith(
        DiscType.CD_DA.value
    )


def test_msf_start_of_zero_is_kept_as_written() -> None:
    assert 'FILE "a.wav" 00:00:00' in dumps(
        parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 00:00:00\n')
    )
    assert 'FILE "a.wav" 0\n' in dumps(parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\n'))


def test_msf_helper_is_used_for_indexes() -> None:
    toc = parse('CD_DA\nTRACK AUDIO\nFILE "a.wav" 0\nINDEX 1:2:3\n')
    assert "INDEX 01:02:03" in dumps(toc)
    assert toc.tracks[0].indexes == [Msf(1, 2, 3)]


def test_continued_binary_line_pads_its_first_value() -> None:
    """cdrdao pads every value on a continued line, the first one included.

    A single digit hides it, since one pad column looks like one more indent
    column, so this needs a thirteenth value of two digits to show up.
    """
    genre = [*range(1, 13), 32]
    toc = Toc(
        cd_text=CdText(blocks={0: CdTextBlock(items={CdTextItemName.GENRE: genre})}),
        tracks=[
            Track(mode=TrackMode.AUDIO, statements=[File(filename="a.wav", start=0)])
        ],
    )
    lines = dumps(toc).splitlines()
    assert "    GENRE { 1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12," in lines
    assert "               32}" in lines
