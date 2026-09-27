"""Tests for the model layer, independent of parsing."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from tocparser import (
    CdText,
    CdTextBlock,
    CdTextEncoding,
    CdTextItemName,
    DataFile,
    DiscType,
    End,
    File,
    Msf,
    Silence,
    Start,
    Toc,
    TocValidationError,
    Track,
    TrackMode,
    Zero,
)


def audio_track(**overrides: object) -> Track:
    defaults: dict[str, object] = {
        "mode": TrackMode.AUDIO,
        "statements": [File(filename="a.wav", start=0)],
    }
    defaults.update(overrides)
    return Track(**defaults)  # type: ignore[arg-type]


def test_defaults() -> None:
    toc = Toc(tracks=[audio_track()])
    assert toc.disc_type is DiscType.CD_DA
    assert toc.catalog is None
    assert toc.cd_text is None
    assert toc.first_track_number is None


def test_resolved_flag_defaults_match_cdrdao() -> None:
    track = audio_track()
    assert (track.is_copy_permitted, track.has_pre_emphasis, track.channel_count) == (
        False,
        False,
        2,
    )


def test_content_excludes_markers() -> None:
    track = audio_track(
        statements=[
            File(filename="a.wav", start=0),
            Start(),
            Silence(length=Msf(0, 2, 0)),
        ]
    )
    assert len(track.statements) == 3
    assert len(track.content) == 2
    assert track.start == Start()
    assert track.end is None


def test_has_pregap() -> None:
    assert not audio_track().has_pregap
    assert audio_track(pregap=Msf(0, 2, 0)).has_pregap
    assert audio_track(
        statements=[File(filename="a.wav", start=0), Start(position=Msf(0, 2, 0))]
    ).has_pregap
    # A bare START means "at the current length", which is a pre-gap too.
    assert audio_track(statements=[File(filename="a.wav", start=0), Start()]).has_pregap
    # START at zero is not a pre-gap.
    assert not audio_track(
        statements=[File(filename="a.wav", start=0), Start(position=Msf(0, 0, 0))]
    ).has_pregap


def test_a_track_needs_a_statement() -> None:
    with pytest.raises(TocValidationError, match="no data statement"):
        Track(mode=TrackMode.AUDIO, statements=[])


def test_a_toc_needs_a_track() -> None:
    with pytest.raises(TocValidationError, match="at least one track"):
        Toc(tracks=[])


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Track(mode=TrackMode.AUDIO, statements=[], nonsense=1)  # type: ignore[call-arg]


def test_cd_text_lookup() -> None:
    cd_text = CdText(
        language_map={0: 9},
        blocks={0: CdTextBlock(items={CdTextItemName.TITLE: "T"})},
    )
    assert 0 in cd_text
    assert 1 not in cd_text
    assert cd_text[0].title == "T"
    with pytest.raises(KeyError):
        cd_text[1]


def test_cd_text_with_only_a_language_map_is_truthy() -> None:
    assert CdText(language_map={0: 9})


def track_error(**overrides: object) -> TocValidationError:
    with pytest.raises(TocValidationError) as info:
        audio_track(**overrides)
    return info.value


@pytest.mark.parametrize(
    ("overrides", "message", "loc"),
    [
        (
            {"statements": [File(filename="a", start=0), Start(), End(), Start()]},
            "Track start (end of pre-gap) already defined.",
            ("statements", 3),
        ),
        (
            {"pregap": Msf(0, 2, 0), "statements": [Zero(length=Msf(0, 4, 0))]},
            "Mixing of FILE/AUDIOFILE/SILENCE and DATAFILE/ZERO statements not allowed.",
            ("statements", 0),
        ),
        (
            {"indexes": [Msf(0, 1, 0), Msf(0, 0, 0)]},
            "Index at start of track.",
            ("indexes", 1),
        ),
        (
            {"indexes": [Msf(0, 1 + i // 75, i % 75) for i in range(99)]},
            "More than 98 index increments.",
            ("indexes", 98),
        ),
        ({"isrc": "bad"}, "Illegal ISRC code: bad.", ("isrc",)),
        ({"pregap": 0}, "Length of pregap is zero.", ("pregap",)),
        (
            {"statements": [File(filename="a", start=0), Silence(length=0)]},
            "Length of silence is 0.",
            ("statements", 1),
        ),
        (
            {"cd_text": CdText(language_map={0: 9})},
            "LANGUAGE_MAP is only allowed in the global CD_TEXT block.",
            ("cd_text", "language_map"),
        ),
        (
            {"cd_text": CdText(blocks={2: CdTextBlock(items={CdTextItemName.GENRE: [1]})})},
            "Invalid CD-TEXT item for a track.",
            ("cd_text", "blocks", 2, "items", "GENRE"),
        ),
    ],
    ids=[
        "start-twice",
        "pregap-zero-mix",
        "index-zero",
        "99-indexes",
        "isrc",
        "pregap",
        "silence",
        "language-map",
        "genre",
    ],
)
def test_track_errors_say_where(
    overrides: dict[str, object], message: str, loc: tuple[str | int, ...]
) -> None:
    error = track_error(**overrides)
    assert (error.message, error.loc, error.line) == (message, loc, None)


def test_pregap_of_a_data_track_is_data() -> None:
    Track(mode=TrackMode.MODE1, pregap=Msf(0, 2, 0), statements=[Zero(length=Msf(0, 4, 0))])


@pytest.mark.parametrize(
    "statement",
    [
        lambda: File(filename="a", start=-1),
        lambda: File(filename="a", start=0, length=-1),
        lambda: File(filename="a", start=0, offset=-1),
        lambda: DataFile(filename="d", offset=-1),
        lambda: Silence(length=-1),
        lambda: Start(position=-1),
        lambda: End(position=-1),
    ],
    ids=["start", "length", "file-offset", "datafile-offset", "silence", "start-at", "end-at"],
)
def test_bare_numbers_may_not_be_negative(statement: Callable[[], object]) -> None:
    """cdrdao's syntax has no sign, so a negative number could not be written."""
    with pytest.raises(ValidationError):
        statement()


@pytest.mark.parametrize("overrides", [{"pregap": -1}, {"indexes": [-1]}])
def test_track_times_may_not_be_negative(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        audio_track(**overrides)


def test_zero_data_may_not_be_empty() -> None:
    with pytest.raises(TocValidationError) as info:
        Track(mode=TrackMode.MODE1, statements=[Zero(length=0)])
    assert (info.value.message, info.value.loc) == ("Length of zero data is 0.", ("statements", 0))


def test_aliased_cd_text_items_may_not_both_be_set() -> None:
    with pytest.raises(TocValidationError) as info:
        CdTextBlock(items={CdTextItemName.UPC_EAN: "1", CdTextItemName.ISRC: "2"})
    assert info.value.message == "UPC_EAN and ISRC are the same CD-TEXT item."


@pytest.mark.parametrize(
    ("stored", "asked"),
    [
        (CdTextItemName.ISRC, CdTextItemName.UPC_EAN),
        (CdTextItemName.UPC_EAN, CdTextItemName.ISRC),
        (CdTextItemName.RESERVED4, CdTextItemName.CLOSED),
    ],
)
def test_aliased_cd_text_items_are_found_by_either_name(
    stored: CdTextItemName, asked: CdTextItemName
) -> None:
    assert CdTextBlock(items={stored: "x"}).text(asked) == "x"


def test_upc_ean_and_isrc_accessors_read_the_same_pack() -> None:
    """The README's promise: either accessor finds the value under either name."""
    for stored in (CdTextItemName.UPC_EAN, CdTextItemName.ISRC):
        block = CdTextBlock(items={stored: "0602498647295"})
        assert block.upc_ean == block.isrc == "0602498647295"


def test_binary_cd_text_length_limit() -> None:
    CdTextBlock(items={CdTextItemName.TOC_INFO1: [0] * 3072})
    with pytest.raises(TocValidationError, match=r"exceeds maximum length \(3072\)"):
        CdTextBlock(items={CdTextItemName.TOC_INFO1: [0] * 3073})


def cd_text_toc(title: str, encoding: CdTextEncoding | None = None) -> Toc:
    block = CdTextBlock(encoding=encoding, items={CdTextItemName.TITLE: title})
    return Toc(cd_text=CdText(blocks={0: block}), tracks=[audio_track()])


def test_cd_text_must_fit_its_encoding() -> None:
    with pytest.raises(TocValidationError) as info:
        cd_text_toc("日本")
    assert info.value.loc == ("cd_text", "blocks", 0, "items", "TITLE")
    toc = cd_text_toc("日本", CdTextEncoding.MS_JIS)
    assert toc.cd_text_encoding(0) is CdTextEncoding.MS_JIS
    assert toc.cd_text_encoding(1) is CdTextEncoding.ISO_8859_1


def test_cd_text_block_accessors_ignore_binary_values() -> None:
    block = CdTextBlock(items={CdTextItemName.TITLE: [65, 66]})
    assert block.get(CdTextItemName.TITLE) == [65, 66]
    assert block.title is None
    assert block.text(CdTextItemName.PERFORMER) is None


def test_json_round_trip_preserves_time_forms() -> None:
    toc = Toc(
        tracks=[
            audio_track(statements=[File(filename="a.wav", start=1234567, length=Msf(0, 4, 0))]),
            Track(mode=TrackMode.MODE1, statements=[DataFile(filename="d", length=9999)]),
        ]
    )
    restored = Toc.model_validate_json(toc.model_dump_json())
    assert restored == toc
    statement = restored.tracks[0].statements[0]
    assert isinstance(statement, File)
    assert statement.start == 1234567
    assert statement.length == Msf(0, 4, 0)


def test_statements_are_discriminated_on_load() -> None:
    toc = Toc(tracks=[audio_track()])
    restored = Toc.model_validate(toc.model_dump())
    assert isinstance(restored.tracks[0].statements[0], File)
