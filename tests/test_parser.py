"""Tests for parsing individual directives."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.paths import FIXTURES_DIR
from tocparser import (
    CdTextEncoding,
    CdTextItemName,
    DataFile,
    DataMode,
    DiscType,
    End,
    Fifo,
    File,
    Msf,
    Silence,
    Start,
    SubChannelMode,
    Toc,
    TocParseError,
    TocValidationError,
    TrackMode,
    Zero,
    parse,
    parse_file,
)

MINIMAL_TRACK = 'TRACK AUDIO\nFILE "data.wav" 0\n'
MINIMAL = f"CD_DA\n{MINIMAL_TRACK}"


def parse_track(body: str) -> Toc:
    return parse(f"CD_DA\nTRACK AUDIO\n{body}\n")


def test_minimal_file() -> None:
    toc = parse(MINIMAL)
    assert toc.disc_type is DiscType.CD_DA
    assert len(toc.tracks) == 1
    track = toc.tracks[0]
    assert track.mode is TrackMode.AUDIO
    assert track.statements == [File(filename="data.wav", start=0)]


def test_disc_type_defaults_to_cd_da_when_absent() -> None:
    assert parse('TRACK AUDIO\nFILE "a.wav" 0\n').disc_type is DiscType.CD_DA


def test_last_disc_type_wins() -> None:
    """cdrdao documents that the last of several disc flags takes effect."""
    toc = parse(f"CD_ROM\n{MINIMAL}")
    assert toc.disc_type is DiscType.CD_DA
    assert toc.superseded_disc_types == [DiscType.CD_ROM]
    assert parse(f"CD_DA\nCD_ROM_XA\n{MINIMAL_TRACK}").disc_type is DiscType.CD_ROM_XA


@pytest.mark.parametrize(
    "disc_type", [DiscType.CD_DA, DiscType.CD_ROM, DiscType.CD_ROM_XA, DiscType.CD_I]
)
def test_all_disc_types(disc_type: DiscType) -> None:
    toc = parse(f'{disc_type.value}\nTRACK AUDIO\nFILE "a.wav" 0\n')
    assert toc.disc_type is disc_type


def test_comments_are_ignored_anywhere() -> None:
    source = (
        "// leading\nCD_DA // trailing\n// between\nTRACK AUDIO\n"
        'FILE "data.wav" 0 // after a statement\n'
    )
    assert parse(source) == parse(MINIMAL)


def test_catalog_and_first_track_number() -> None:
    toc = parse(f'CD_DA\nCATALOG "1234567890123"\nFIRST_TRACK_NO 5\n{MINIMAL_TRACK}')
    assert toc.catalog == "1234567890123"
    assert toc.first_track_number == 5


def test_flags_are_tri_state() -> None:
    """An absent flag stays ``None`` so it is not invented on the way out."""
    track = parse(MINIMAL).tracks[0]
    assert track.copy_permitted is None
    assert track.pre_emphasis is None
    assert track.channels is None
    assert track.is_copy_permitted is False
    assert track.has_pre_emphasis is False
    assert track.channel_count == 2


def test_flags_when_written() -> None:
    track = parse_track(
        'COPY\nPRE_EMPHASIS\nFOUR_CHANNEL_AUDIO\nFILE "a.wav" 0'
    ).tracks[0]
    assert track.copy_permitted is True
    assert track.pre_emphasis is True
    assert track.channels == 4
    assert track.channel_count == 4

    track = parse_track(
        'NO COPY\nNO PRE_EMPHASIS\nTWO_CHANNEL_AUDIO\nFILE "a.wav" 0'
    ).tracks[0]
    assert track.copy_permitted is False
    assert track.pre_emphasis is False
    assert track.channels == 2


def test_file_variants() -> None:
    track = parse_track('AUDIOFILE "a.cdr" SWAP #44 00:01:00 00:02:00').tracks[0]
    assert track.statements == [
        File(
            filename="a.cdr",
            start=Msf(0, 1, 0),
            length=Msf(0, 2, 0),
            swap=True,
            offset=44,
            audiofile=True,
        )
    ]


def test_scalar_times_stay_scalar() -> None:
    """A sample count that is not frame aligned has no MSF form."""
    track = parse_track('FILE "a.wav" 1234567 7654321').tracks[0]
    statement = track.statements[0]
    assert isinstance(statement, File)
    assert statement.start == 1234567
    assert statement.length == 7654321


def test_datafile_fifo_silence_zero() -> None:
    toc = parse(
        "CD_ROM\n"
        'TRACK MODE1\nDATAFILE "d" #2048 00:04:00\nZERO MODE0 RW 00:02:00\n'
        'TRACK AUDIO\nFIFO "p" 00:04:00\n'
        'TRACK AUDIO\nSILENCE 00:02:00\nFILE "a.wav" 0\n'
    )
    assert toc.tracks[0].statements == [
        DataFile(filename="d", offset=2048, length=Msf(0, 4, 0)),
        Zero(
            length=Msf(0, 2, 0),
            data_mode=DataMode.MODE0,
            sub_channel_mode=SubChannelMode.RW,
        ),
    ]
    assert toc.tracks[1].statements == [Fifo(filename="p", length=Msf(0, 4, 0))]
    assert toc.tracks[2].statements[0] == Silence(length=Msf(0, 2, 0))


def test_start_end_and_pregap() -> None:
    track = parse_track('FILE "a.wav" 0\nSTART\nEND 00:04:00').tracks[0]
    assert track.start == Start(position=None)
    assert track.end == End(position=Msf(0, 4, 0))

    track = parse_track('PREGAP 00:02:00\nFILE "a.wav" 0').tracks[0]
    assert track.pregap == Msf(0, 2, 0)
    assert track.start is None
    assert track.has_pregap


def test_statement_order_is_preserved() -> None:
    """``START`` without a position means "at the current length", so the
    interleaving of content statements and markers carries meaning."""
    track = parse_file(FIXTURES_DIR / "man_composed_track.toc").tracks[0]
    assert [statement.kind for statement in track.statements] == [
        "file",
        "start",
        "file",
        "silence",
        "file",
    ]
    assert track.indexes == [Msf(2, 0, 0), Msf(4, 0, 0)]
    assert len(track.content) == 4


def test_sub_channel_modes() -> None:
    toc = parse('CD_ROM\nTRACK MODE1 RW_RAW\nDATAFILE "d" 00:04:00\n')
    assert toc.tracks[0].sub_channel_mode is SubChannelMode.RW_RAW
    assert toc.tracks[0].block_size == 2048 + 96


@pytest.mark.parametrize(
    ("mode", "size"),
    [
        (TrackMode.AUDIO, 2352),
        (TrackMode.MODE1, 2048),
        (TrackMode.MODE1_RAW, 2352),
        (TrackMode.MODE2, 2336),
        (TrackMode.MODE2_RAW, 2352),
        (TrackMode.MODE2_FORM1, 2048),
        (TrackMode.MODE2_FORM2, 2324),
        (TrackMode.MODE2_FORM_MIX, 2336),
    ],
)
def test_block_sizes(mode: TrackMode, size: int) -> None:
    source = f'CD_ROM_XA\nTRACK {mode.value}\nDATAFILE "d" 00:04:00\n'
    if mode is TrackMode.AUDIO:
        source = 'CD_ROM_XA\nTRACK AUDIO\nFILE "a.wav" 0\n'
    assert parse(source).tracks[0].block_size == size


def test_language_map_accepts_both_spellings() -> None:
    numeric = parse(f"CD_DA\nCD_TEXT {{ LANGUAGE_MAP {{ 0: 9 }} }}\n{MINIMAL_TRACK}")
    symbolic = parse(f"CD_DA\nCD_TEXT {{ LANGUAGE_MAP {{ 0 : EN }} }}\n{MINIMAL_TRACK}")
    assert numeric == symbolic
    assert numeric.cd_text is not None
    assert numeric.cd_text.language_map == {0: 9}


def test_cd_text_values_and_accessors() -> None:
    toc = parse_file(FIXTURES_DIR / "cd_text_full.toc")
    assert toc.cd_text is not None
    assert 0 in toc.cd_text
    assert list(toc.cd_text.blocks) == [0, 1]
    disc = toc.cd_text[0]
    assert disc.title == "Disc Title"
    assert disc.performer == "Performer"
    assert disc.songwriter == "Songwriter"
    assert disc.composer == "Composer"
    assert disc.arranger == "Arranger"
    assert disc.message == "Message to the user"
    assert disc.disc_id == "XY12345"
    assert disc.upc_ean == "1234567890123"
    assert disc.get(CdTextItemName.TOC_INFO1) == [1, 2, 3]
    # A binary value is not text, so the text accessor declines to guess.
    assert disc.text(CdTextItemName.GENRE) is None
    assert toc.cd_text[1].title == "Titre du disque"


def test_cd_text_binary_can_be_empty() -> None:
    toc = parse_file(FIXTURES_DIR / "cd_i_and_empty_binary.toc")
    assert toc.cd_text is not None
    assert toc.cd_text[0].get(CdTextItemName.TOC_INFO1) == []


def title_of(raw: str, block: str = "") -> str | None:
    """The TITLE read from a CD-TEXT string written as ``"raw"``."""
    toc = parse(
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ {block} TITLE "{raw}" }} }}\n{MINIMAL_TRACK}'
    )
    assert toc.cd_text is not None
    return toc.cd_text[0].title


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (r"plain", "plain"),
        (r"a\"b", 'a"b'),
        (r"a\\b", "a\\b"),
        (r"A\101B", "AAB"),
        (r"back\\slash", "back\\slash"),
        # A byte above 127 reads as ISO-8859-1, the default block encoding.
        (r"caf\351", "café"),
        # cdrdao reads the digits with strtol(), which stops at the first one
        # that is not octal, and keeps the low byte.
        (r"\999", "\x00"),
        (r"\189", "\x01"),
        (r"\777", "\xff"),
        # An escaped backslash before three digits still makes an octal escape,
        # so \134 is how a backslash followed by digits is written.
        (r"\\101", "A"),
        (r"\134101", "\\101"),
        ("tab\there", "tab\there"),
        ("new\nline", "new\nline"),
    ],
)
def test_string_escapes(raw: str, expected: str) -> None:
    assert title_of(raw) == expected


def test_escaped_bytes_follow_the_block_encoding() -> None:
    assert title_of(r"\223\372\226\173", "ENCODING_MS_JIS") == "日本"


def test_encodings() -> None:
    toc = parse_file(FIXTURES_DIR / "encodings.toc")
    assert toc.cd_text is not None
    assert toc.cd_text[0].encoding is CdTextEncoding.MS_JIS
    assert toc.cd_text[0].title == toc.cd_text[0].performer == "日本"
    assert toc.cd_text_encoding(0) is CdTextEncoding.MS_JIS
    assert toc.cd_text_encoding(1) is CdTextEncoding.ISO_8859_1
    track_cd_text = toc.tracks[0].cd_text
    assert track_cd_text is not None
    assert track_cd_text[0].encoding is None
    assert track_cd_text[0].title == "東京"


def test_track_escapes_follow_the_disc_encoding() -> None:
    toc = parse(
        "CD_DA\nCD_TEXT { LANGUAGE 0 { ENCODING_MS_JIS } }\n"
        'TRACK AUDIO\nCD_TEXT { LANGUAGE 0 { TITLE "\\223\\372" } }\nFILE "a.wav" 0\n'
    )
    assert toc.tracks[0].cd_text is not None
    assert toc.tracks[0].cd_text[0].title == "日"


def test_repeated_language_blocks_merge() -> None:
    """cdrdao files items by language, so a second block adds to the first."""
    toc = parse(
        "CD_DA\nCD_TEXT {\n"
        'LANGUAGE 0 { ENCODING_ISO_8859_1 TITLE "a" PERFORMER "p" }\n'
        'LANGUAGE 0 { TITLE "b" }\n'
        f"}}\n{MINIMAL_TRACK}"
    )
    assert toc.cd_text is not None
    block = toc.cd_text[0]
    assert block.items == {CdTextItemName.TITLE: "b", CdTextItemName.PERFORMER: "p"}
    assert block.encoding is CdTextEncoding.ISO_8859_1


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (CdTextItemName.UPC_EAN, CdTextItemName.ISRC),
        (CdTextItemName.ISRC, CdTextItemName.UPC_EAN),
        (CdTextItemName.RESERVED4, CdTextItemName.CLOSED),
    ],
)
def test_aliased_items_collapse_to_the_last(
    first: CdTextItemName, second: CdTextItemName
) -> None:
    toc = parse(
        f"CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ "
        f'{first.value} "1" {second.value} "2" }} }}\n{MINIMAL_TRACK}'
    )
    assert toc.cd_text is not None
    block = toc.cd_text[0]
    assert block.items == {second: "2"}
    assert block.get(first) == "2"


def test_escapes_in_a_real_file() -> None:
    toc = parse_file(FIXTURES_DIR / "escapes.toc")
    assert toc.cd_text is not None
    assert toc.cd_text[0].title == 'He said "hi"'
    assert toc.cd_text[0].performer == "AAB"
    assert toc.cd_text[0].message == "back\\slash"


def test_empty_string_value() -> None:
    toc = parse(f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ UPC_EAN "" }} }}\n{MINIMAL_TRACK}')
    assert toc.cd_text is not None
    assert toc.cd_text[0].upc_ean == ""


def test_closed_cd_text_item() -> None:
    toc = parse(
        f'CD_DA\nCD_TEXT {{ LANGUAGE 0 {{ CLOSED "SADiE v6" }} }}\n{MINIMAL_TRACK}'
    )
    assert toc.cd_text is not None
    assert toc.cd_text[0].text(CdTextItemName.CLOSED) == "SADiE v6"


def test_parse_file_reports_the_filename_in_errors(tmp_path: Path) -> None:
    path = tmp_path / "album.toc"
    path.write_text('CD_DA\nCATALOG "1"\nTRACK AUDIO\nFILE "a.wav" 0\n')
    with pytest.raises(TocValidationError) as info:
        parse_file(path)
    assert str(info.value) == f"{path}:2: Illegal catalog number: 1."


@pytest.mark.parametrize("newline", [b"\n", b"\r\n", b"\r"], ids=["lf", "crlf", "cr"])
def test_parse_file_rejects_bytes_it_cannot_decode(
    tmp_path: Path, newline: bytes
) -> None:
    path = tmp_path / "latin.toc"
    source = (
        b'CD_DA\nCD_TEXT { LANGUAGE 0 {\nTITLE "caf\xe9" } }\nTRACK AUDIO\nFILE "a" 0\n'
    )
    path.write_bytes(source.replace(b"\n", newline))
    with pytest.raises(TocParseError) as info:
        parse_file(path)
    assert (info.value.line, info.value.message) == (
        3,
        "Cannot decode byte 0xe9 as utf-8",
    )
    assert parse_file(path, encoding="latin-1").cd_text is not None


def test_parse_file_reads_crlf_line_endings(tmp_path: Path) -> None:
    path = tmp_path / "crlf.toc"
    path.write_bytes(MINIMAL.replace("\n", "\r\n").encode())
    assert parse_file(path) == parse(MINIMAL)
