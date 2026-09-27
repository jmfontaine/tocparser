"""Pydantic models describing the contents of a TOC file.

The hierarchy mirrors cdrdao's own grammar: a :class:`Toc` carries disc level
metadata and a list of :class:`Track`, and each track carries flags, optional
CD-TEXT and an ordered list of statements describing where its data comes
from.

Every rule cdrdao enforces on the text is enforced when a model is built, so a
model can only describe a file cdrdao would accept. A broken rule raises
:class:`~tocparser.errors.TocValidationError`, whose ``loc`` says where the
problem is; a value of the wrong type raises pydantic's ``ValidationError``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from enum import Enum
from typing import Annotated, ClassVar, Literal, NoReturn, TypeAlias, TypeVar

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

from tocparser.errors import TocValidationError
from tocparser.times import Msf, Time

# cdrdao's syntax has no negative numbers, so neither do the models: a bare
# integer time or a byte offset below zero could not be written back.
_TimeField: TypeAlias = Msf | NonNegativeInt

__all__ = [
    "CdText",
    "CdTextBlock",
    "CdTextEncoding",
    "CdTextItemName",
    "CdTextValue",
    "ContentItem",
    "DataFile",
    "DataMode",
    "DiscType",
    "End",
    "Fifo",
    "File",
    "Silence",
    "Start",
    "SubChannelMode",
    "Toc",
    "Track",
    "TrackMode",
    "TrackStatement",
    "Zero",
    "cd_text_codec",
    "validate_binary_value",
    "validate_block_number",
    "validate_catalog",
    "validate_first_track_number",
    "validate_isrc",
    "validate_language_code",
    "validate_language_number",
    "validate_non_zero_length",
]

_T = TypeVar("_T")

_CATALOG_RE = re.compile(r"\A[0-9]{13}\Z")
_ISRC_RE = re.compile(r"\A[A-Z0-9]{5}[0-9]{7}\Z")

MAX_INDEX_INCREMENTS = 98
#: cdrdao's ``MAX_CD_TEXT_DATA_LEN``.
MAX_BINARY_LENGTH = 256 * 12

# cdrdao's messages, shared with the parser so both report the same text.
PREGAP_IS_ZERO = "Length of pregap is zero."
SILENCE_IS_ZERO = "Length of silence is 0."
ZERO_DATA_IS_ZERO = "Length of zero data is 0."
MIXED_STATEMENTS = (
    "Mixing of FILE/AUDIOFILE/SILENCE and DATAFILE/ZERO statements not allowed."
)
BINARY_DATA_TOO_LONG = f"Binary data exceeds maximum length ({MAX_BINARY_LENGTH})."


class DiscType(str, Enum):
    """The session type declared by the leading disc flag."""

    CD_DA = "CD_DA"
    CD_ROM = "CD_ROM"
    CD_ROM_XA = "CD_ROM_XA"
    CD_I = "CD_I"


class TrackMode(str, Enum):
    """The sector layout of a track's data."""

    AUDIO = "AUDIO"
    MODE1 = "MODE1"
    MODE1_RAW = "MODE1_RAW"
    MODE2 = "MODE2"
    MODE2_RAW = "MODE2_RAW"
    MODE2_FORM1 = "MODE2_FORM1"
    MODE2_FORM2 = "MODE2_FORM2"
    MODE2_FORM_MIX = "MODE2_FORM_MIX"


class DataMode(str, Enum):
    """Sector layouts accepted by a ``ZERO`` statement.

    Identical to :class:`TrackMode` plus ``MODE0``, which cdrdao's grammar
    only reaches through ``ZERO``.
    """

    AUDIO = "AUDIO"
    MODE0 = "MODE0"
    MODE1 = "MODE1"
    MODE1_RAW = "MODE1_RAW"
    MODE2 = "MODE2"
    MODE2_RAW = "MODE2_RAW"
    MODE2_FORM1 = "MODE2_FORM1"
    MODE2_FORM2 = "MODE2_FORM2"
    MODE2_FORM_MIX = "MODE2_FORM_MIX"


class SubChannelMode(str, Enum):
    """The type of R-W sub-channel data carried by each sector."""

    RW = "RW"
    RW_RAW = "RW_RAW"


#: Bytes of user data per sector, per sector layout.
BLOCK_SIZES: dict[str, int] = {
    "AUDIO": 2352,
    "MODE0": 2336,
    "MODE1": 2048,
    "MODE1_RAW": 2352,
    "MODE2": 2336,
    "MODE2_RAW": 2352,
    "MODE2_FORM1": 2048,
    "MODE2_FORM2": 2324,
    "MODE2_FORM_MIX": 2336,
}

#: Extra bytes per sector when a sub-channel mode is in use.
SUB_CHANNEL_SIZE = 96


def block_size(
    mode: TrackMode | DataMode, sub_channel_mode: SubChannelMode | None
) -> int:
    """Return the sector size for ``mode``, including sub-channel data."""
    size = BLOCK_SIZES[mode.value]
    if sub_channel_mode is not None:
        size += SUB_CHANNEL_SIZE
    return size


class CdTextItemName(str, Enum):
    """The CD-TEXT pack types cdrdao's grammar accepts."""

    TITLE = "TITLE"
    PERFORMER = "PERFORMER"
    SONGWRITER = "SONGWRITER"
    COMPOSER = "COMPOSER"
    ARRANGER = "ARRANGER"
    MESSAGE = "MESSAGE"
    DISC_ID = "DISC_ID"
    GENRE = "GENRE"
    TOC_INFO1 = "TOC_INFO1"
    TOC_INFO2 = "TOC_INFO2"
    RESERVED1 = "RESERVED1"
    RESERVED2 = "RESERVED2"
    RESERVED3 = "RESERVED3"
    RESERVED4 = "RESERVED4"
    CLOSED = "CLOSED"
    UPC_EAN = "UPC_EAN"
    ISRC = "ISRC"
    SIZE_INFO = "SIZE_INFO"


#: Pairs of names cdrdao reads as the same pack: ``UPC_EAN`` is what it writes
#: on the disc and ``ISRC`` what it writes on a track, and ``RESERVED4`` is an
#: old spelling of ``CLOSED``.
CD_TEXT_ALIASES: dict[CdTextItemName, CdTextItemName] = {
    CdTextItemName.UPC_EAN: CdTextItemName.ISRC,
    CdTextItemName.ISRC: CdTextItemName.UPC_EAN,
    CdTextItemName.RESERVED4: CdTextItemName.CLOSED,
    CdTextItemName.CLOSED: CdTextItemName.RESERVED4,
}

#: CD-TEXT items cdrdao rejects inside a track's ``CD_TEXT`` block.
DISC_ONLY_CD_TEXT_ITEMS = frozenset(
    {
        CdTextItemName.GENRE,
        CdTextItemName.TOC_INFO1,
        CdTextItemName.TOC_INFO2,
        CdTextItemName.SIZE_INFO,
    }
)


class CdTextEncoding(str, Enum):
    """The character set of a CD-TEXT language block (cdrdao 1.2.5 and later)."""

    ISO_8859_1 = "ENCODING_ISO_8859_1"
    ASCII = "ENCODING_ASCII"
    MS_JIS = "ENCODING_MS_JIS"
    KOREAN = "ENCODING_KOREAN"
    MANDARIN = "ENCODING_MANDARIN"


def cd_text_codec(encoding: CdTextEncoding) -> str:
    """The Python codec matching the conversion cdrdao applies for ``encoding``.

    cdrdao has no converter for Korean or Mandarin and treats both as
    ISO-8859-1, so they share its codec.
    """
    if encoding is CdTextEncoding.ASCII:
        return "ascii"
    if encoding is CdTextEncoding.MS_JIS:
        return "cp932"
    return "latin-1"


#: A CD-TEXT value is either a string or a run of raw bytes.
CdTextValue: TypeAlias = str | list[int]

MAX_LANGUAGE_NUMBER = 7
MAX_LANGUAGE_CODE = 255
MAX_BINARY_BYTE = 255


#: The only symbolic country code cdrdao's lexer knows.
LANGUAGE_CODE_EN = 9


def _fail(message: str, *loc: str | int) -> NoReturn:
    raise TocValidationError(message, loc=loc)


def _check_at(check: Callable[[_T], object], value: _T, *loc: str | int) -> None:
    """Run one of the ``validate_*`` checks, locating any failure at ``loc``."""
    try:
        check(value)
    except TocValidationError as exc:
        _fail(exc.message, *loc)


def _is_zero_length(length: Time) -> bool:
    return length.total_frames == 0 if isinstance(length, Msf) else length == 0


def validate_catalog(catalog: str) -> str:
    """Check a ``CATALOG`` value: cdrdao requires exactly 13 digits."""
    if not _CATALOG_RE.match(catalog):
        raise TocValidationError(f"Illegal catalog number: {catalog}.")
    return catalog


def validate_isrc(isrc: str) -> str:
    """Check a track ``ISRC`` value against cdrdao's ``CCOOOYYSSSSS`` format."""
    if not _ISRC_RE.match(isrc):
        raise TocValidationError(f"Illegal ISRC code: {isrc}.")
    return isrc


def validate_first_track_number(number: int) -> int:
    """Check a ``FIRST_TRACK_NO`` value."""
    if not 1 <= number <= 99:
        raise TocValidationError(f"Illegal track number: {number}")
    return number


def validate_language_number(number: int) -> int:
    """Check the language number of a ``LANGUAGE_MAP`` entry."""
    if not 0 <= number <= MAX_LANGUAGE_NUMBER:
        raise TocValidationError(
            f"Invalid language number, allowed range: [0..{MAX_LANGUAGE_NUMBER}]."
        )
    return number


def validate_block_number(number: int) -> int:
    """Check the number of a ``LANGUAGE`` block."""
    if not 0 <= number <= MAX_LANGUAGE_NUMBER:
        raise TocValidationError(
            f"Invalid block number, allowed range: [0..{MAX_LANGUAGE_NUMBER}]."
        )
    return number


def validate_language_code(code: int) -> int:
    """Check a country code from a ``LANGUAGE_MAP`` entry."""
    if not 0 <= code <= MAX_LANGUAGE_CODE:
        raise TocValidationError(
            f"Invalid language code, allowed range: [0..{MAX_LANGUAGE_CODE}]."
        )
    return code


def validate_non_zero_length(length: Time, message: str) -> Time:
    """Check a ``PREGAP``/``SILENCE``/``ZERO`` length, which may not be zero."""
    if _is_zero_length(length):
        raise TocValidationError(message)
    return length


def validate_binary_value(value: int) -> int:
    """Check one byte of a binary CD-TEXT value."""
    if not 0 <= value <= MAX_BINARY_BYTE:
        raise TocValidationError(f"Illegal binary data: {value}")
    return value


class _Model(BaseModel):
    """Base for every tocparser model: unknown fields are rejected."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")


class CdTextBlock(_Model):
    """The CD-TEXT items defined for one language.

    ``encoding`` is the ``ENCODING_*`` keyword written at the top of the block,
    if any. cdrdao only honors it on the disc's ``CD_TEXT``; track blocks
    follow the disc block with the same number, see
    :meth:`Toc.cd_text_encoding`.
    """

    encoding: CdTextEncoding | None = None
    items: dict[CdTextItemName, CdTextValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> CdTextBlock:
        for name, value in self.items.items():
            loc = ("items", name.value)
            alias = CD_TEXT_ALIASES.get(name)
            if alias is not None and alias in self.items:
                _fail(
                    f"{name.value} and {alias.value} are the same CD-TEXT item.", *loc
                )
            if isinstance(value, list):
                for byte in value:
                    _check_at(validate_binary_value, byte, *loc)
                if len(value) > MAX_BINARY_LENGTH:
                    _fail(BINARY_DATA_TOO_LONG, *loc)
        return self

    def get(self, name: CdTextItemName) -> CdTextValue | None:
        """Return the value of ``name``, or ``None`` when it is not defined.

        A value stored under the other spelling of the same pack (see
        :data:`CD_TEXT_ALIASES`) is found too.
        """
        value = self.items.get(name)
        alias = CD_TEXT_ALIASES.get(name)
        if value is None and alias is not None:
            value = self.items.get(alias)
        return value

    def text(self, name: CdTextItemName) -> str | None:
        """Return ``name`` when it holds a string, otherwise ``None``."""
        value = self.get(name)
        return value if isinstance(value, str) else None

    @property
    def title(self) -> str | None:
        return self.text(CdTextItemName.TITLE)

    @property
    def performer(self) -> str | None:
        return self.text(CdTextItemName.PERFORMER)

    @property
    def songwriter(self) -> str | None:
        return self.text(CdTextItemName.SONGWRITER)

    @property
    def composer(self) -> str | None:
        return self.text(CdTextItemName.COMPOSER)

    @property
    def arranger(self) -> str | None:
        return self.text(CdTextItemName.ARRANGER)

    @property
    def message(self) -> str | None:
        return self.text(CdTextItemName.MESSAGE)

    @property
    def disc_id(self) -> str | None:
        return self.text(CdTextItemName.DISC_ID)

    @property
    def upc_ean(self) -> str | None:
        """The UPC/EAN code; the same pack as :attr:`isrc`."""
        return self.text(CdTextItemName.UPC_EAN)

    @property
    def isrc(self) -> str | None:
        """The ISRC code; the same pack as :attr:`upc_ean`."""
        return self.text(CdTextItemName.ISRC)


class CdText(_Model):
    """A ``CD_TEXT`` block: an optional language map plus per-language items.

    ``cd_text[n]`` returns block ``n`` and ``n in cd_text`` tests for it.
    """

    language_map: dict[int, int] = Field(default_factory=dict)
    blocks: dict[int, CdTextBlock] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> CdText:
        for number, code in self.language_map.items():
            _check_at(validate_language_number, number, "language_map", number)
            _check_at(validate_language_code, code, "language_map", number)
        for number in self.blocks:
            _check_at(validate_block_number, number, "blocks", number)
        return self

    def __getitem__(self, language: int) -> CdTextBlock:
        return self.blocks[language]

    def __contains__(self, language: int) -> bool:
        return language in self.blocks


class File(_Model):
    """``FILE`` or ``AUDIOFILE``: audio data taken from a file."""

    kind: Literal["file"] = "file"
    filename: str
    start: _TimeField
    length: _TimeField | None = None
    swap: bool = False
    #: Byte offset given as ``#N``, which also forces raw (headerless) reading.
    offset: NonNegativeInt | None = None
    #: ``True`` when the statement was spelled ``AUDIOFILE``.
    audiofile: bool = False


class DataFile(_Model):
    """``DATAFILE``: sector data taken from a file."""

    kind: Literal["datafile"] = "datafile"
    filename: str
    length: _TimeField | None = None
    offset: NonNegativeInt | None = None


class Fifo(_Model):
    """``FIFO``: data read from a named pipe."""

    kind: Literal["fifo"] = "fifo"
    filename: str
    length: _TimeField


class Silence(_Model):
    """``SILENCE``: zeroed audio data."""

    kind: Literal["silence"] = "silence"
    length: _TimeField


class Zero(_Model):
    """``ZERO``: zeroed sector data."""

    kind: Literal["zero"] = "zero"
    length: _TimeField
    data_mode: DataMode | None = None
    sub_channel_mode: SubChannelMode | None = None


class Start(_Model):
    """``START``: marks the end of the pre-gap.

    ``position`` is ``None`` for a bare ``START``, which means "here", at
    whatever length the track has accumulated so far.
    """

    kind: Literal["start"] = "start"
    position: _TimeField | None = None


class End(_Model):
    """``END``: marks the start of the post-gap."""

    kind: Literal["end"] = "end"
    position: _TimeField | None = None


#: A statement inside a track, in the order it was written.
TrackStatement = Annotated[
    File | DataFile | Fifo | Silence | Zero | Start | End,
    Field(discriminator="kind"),
]

#: The subset of statements that contribute data to a track.
ContentItem: TypeAlias = File | DataFile | Fifo | Silence | Zero

_CONTENT_TYPES = (File, DataFile, Fifo, Silence, Zero)


class Track(_Model):
    """A single ``TRACK`` specification."""

    mode: TrackMode
    sub_channel_mode: SubChannelMode | None = None
    #: ``None`` when no ``COPY`` flag was written.
    copy_permitted: bool | None = None
    #: ``None`` when no ``PRE_EMPHASIS`` flag was written.
    pre_emphasis: bool | None = None
    #: ``None`` when neither channel flag was written.
    channels: Literal[2, 4] | None = None
    isrc: str | None = None
    cd_text: CdText | None = None
    pregap: _TimeField | None = None
    statements: list[TrackStatement] = Field(default_factory=list)
    indexes: list[_TimeField] = Field(default_factory=list)

    @property
    def is_copy_permitted(self) -> bool:
        """The effective copy flag; cdrdao defaults to not permitted."""
        return bool(self.copy_permitted)

    @property
    def has_pre_emphasis(self) -> bool:
        """The effective pre-emphasis flag; cdrdao defaults to off."""
        return bool(self.pre_emphasis)

    @property
    def channel_count(self) -> int:
        """The effective channel count; cdrdao defaults to two."""
        return self.channels if self.channels is not None else 2

    @property
    def block_size(self) -> int:
        """Bytes per sector for this track, including sub-channel data."""
        return block_size(self.mode, self.sub_channel_mode)

    @property
    def content(self) -> list[ContentItem]:
        """The statements that contribute data, in order."""
        return [s for s in self.statements if isinstance(s, _CONTENT_TYPES)]

    @property
    def start(self) -> Start | None:
        """The track's ``START`` statement, if any."""
        return next((s for s in self.statements if isinstance(s, Start)), None)

    @property
    def end(self) -> End | None:
        """The track's ``END`` statement, if any."""
        return next((s for s in self.statements if isinstance(s, End)), None)

    @property
    def has_pregap(self) -> bool:
        """Whether the track defines a pre-gap, by ``PREGAP`` or ``START``."""
        if self.pregap is not None:
            return True
        start = self.start
        if start is None:
            return False
        return start.position is None or not _is_zero_length(start.position)

    @model_validator(mode="after")
    def _check(self) -> Track:
        # The checks run in the order cdrdao meets the text, so the first
        # problem reported is the one cdrdao reports first.
        if self.isrc is not None:
            _check_at(validate_isrc, self.isrc, "isrc")

        if self.cd_text is not None:
            if self.cd_text.language_map:
                _fail(
                    "LANGUAGE_MAP is only allowed in the global CD_TEXT block.",
                    "cd_text",
                    "language_map",
                )
            for number, block in self.cd_text.blocks.items():
                for name, value in block.items.items():
                    # cdrdao 1.2.6 drops an empty string before checking it
                    # (cdTextItem in trackdb/TocParser.g). Its master branch
                    # keeps the string, so there this item is rejected.
                    if name in DISC_ONLY_CD_TEXT_ITEMS and value != "":
                        _fail(
                            "Invalid CD-TEXT item for a track.",
                            "cd_text",
                            "blocks",
                            number,
                            "items",
                            name.value,
                        )

        if self.pregap is not None and _is_zero_length(self.pregap):
            _fail(PREGAP_IS_ZERO, "pregap")

        if not self.statements:
            _fail("Track has no data statement.", "statements")

        self._check_statements()
        self._check_indexes()
        return self

    def _check_statements(self) -> None:
        is_audio = self.mode is TrackMode.AUDIO
        # cdrdao files each piece of data as audio (FILE, SILENCE, and a
        # PREGAP on an audio track, which it inserts as silence) or as data
        # (everything else), and rejects a track holding both.
        audio_data: bool | None = None
        if self.pregap is not None:
            audio_data = is_audio
        start_defined = self.pregap is not None
        end_defined = False

        for index, statement in enumerate(self.statements):
            loc = ("statements", index)
            if isinstance(statement, Start):
                if start_defined:
                    _fail("Track start (end of pre-gap) already defined.", *loc)
                start_defined = True
                continue
            if isinstance(statement, End):
                if end_defined:
                    _fail("Track end (start of post-gap) already defined.", *loc)
                end_defined = True
                continue

            if isinstance(statement, Silence) and _is_zero_length(statement.length):
                _fail(SILENCE_IS_ZERO, *loc)
            if isinstance(statement, Zero) and _is_zero_length(statement.length):
                _fail(ZERO_DATA_IS_ZERO, *loc)

            is_audio_statement = isinstance(statement, (File, Silence))
            if is_audio_statement:
                name = "FILE/AUDIOFILE" if isinstance(statement, File) else "SILENCE"
                if not is_audio:
                    _fail(f"{name} statements are only allowed for audio tracks.", *loc)
                if self.sub_channel_mode is not None:
                    _fail(
                        f"{name} statements are only allowed for audio tracks "
                        "without sub-channel mode.",
                        *loc,
                    )

            if audio_data is None:
                audio_data = is_audio_statement
            elif audio_data != is_audio_statement:
                _fail(MIXED_STATEMENTS, *loc)

    def _check_indexes(self) -> None:
        for index, position in enumerate(self.indexes):
            loc = ("indexes", index)
            if index == MAX_INDEX_INCREMENTS:
                _fail(f"More than {MAX_INDEX_INCREMENTS} index increments.", *loc)
            if _is_zero_length(position):
                _fail("Index at start of track.", *loc)


class Toc(_Model):
    """A parsed TOC file."""

    catalog: str | None = None
    disc_type: DiscType = DiscType.CD_DA
    first_track_number: int | None = None
    cd_text: CdText | None = None
    tracks: list[Track] = Field(default_factory=list)

    def cd_text_encoding(self, language: int) -> CdTextEncoding:
        """The encoding cdrdao applies to CD-TEXT language block ``language``.

        It is the ``ENCODING_*`` of that block in the disc's ``CD_TEXT``, and
        ISO-8859-1 when there is none. Track blocks follow the disc: an
        encoding written on a track block is ignored.

        This is ``CdTextContainer::enforceEncoding`` in cdrdao 1.2.6's
        ``trackdb/CdTextContainer.cc``. cdrdao's master branch differs: for a
        block with no ``ENCODING_*`` it first tries the character code in the
        first byte of the block's ``SIZE_INFO``.
        """
        if self.cd_text is not None:
            block = self.cd_text.blocks.get(language)
            if block is not None and block.encoding is not None:
                return block.encoding
        return CdTextEncoding.ISO_8859_1

    @model_validator(mode="after")
    def _check(self) -> Toc:
        if self.catalog is not None:
            _check_at(validate_catalog, self.catalog, "catalog")

        if self.first_track_number is not None:
            _check_at(
                validate_first_track_number,
                self.first_track_number,
                "first_track_number",
            )

        if not self.tracks:
            _fail("A TOC file must define at least one track.", "tracks")

        # cdrdao converts CD-TEXT to its block's encoding once the whole file
        # is read, so this is the last check it makes.
        located: list[tuple[tuple[str | int, ...], CdText | None]] = [
            (("cd_text",), self.cd_text)
        ]
        located += [
            (("tracks", number, "cd_text"), track.cd_text)
            for number, track in enumerate(self.tracks)
        ]
        for prefix, cd_text in located:
            if cd_text is None:
                continue
            for number, block in cd_text.blocks.items():
                codec = cd_text_codec(self.cd_text_encoding(number))
                for name, value in block.items.items():
                    if isinstance(value, str) and not _encodes(value, codec):
                        _fail(
                            f'CD-TEXT: Unable to encode "{value}" '
                            "into compatible format",
                            *prefix,
                            "blocks",
                            number,
                            "items",
                            name.value,
                        )

        return self


def _encodes(text: str, codec: str) -> bool:
    try:
        text.encode(codec)
    except UnicodeEncodeError:
        return False
    return True
