"""Turn TOC file text into :class:`~tocparser.models.Toc` objects."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from functools import cache
from importlib import resources
from os import PathLike
from pathlib import Path
from typing import Literal, NamedTuple

from lark import Lark, Token, Transformer, v_args
from lark.exceptions import (
    UnexpectedCharacters,
    UnexpectedEOF,
    UnexpectedInput,
    UnexpectedToken,
    VisitError,
)
from lark.tree import Meta

from tocparser.errors import Loc, TocError, TocParseError, TocValidationError
from tocparser.models import (
    BINARY_DATA_TOO_LONG,
    CD_TEXT_ALIASES,
    LANGUAGE_CODE_EN,
    MAX_BINARY_LENGTH,
    PREGAP_IS_ZERO,
    SILENCE_IS_ZERO,
    ZERO_DATA_IS_ZERO,
    CdText,
    CdTextBlock,
    CdTextEncoding,
    CdTextItemName,
    CdTextValue,
    DataFile,
    DataMode,
    DiscType,
    End,
    Fifo,
    File,
    Silence,
    Start,
    SubChannelMode,
    Toc,
    Track,
    TrackMode,
    TrackStatement,
    Zero,
    validate_binary_value,
    validate_block_number,
    validate_catalog,
    validate_first_track_number,
    validate_isrc,
    validate_language_code,
    validate_language_number,
    validate_non_zero_length,
)
from tocparser.times import Msf, Time

__all__ = ["parse", "parse_file"]

# cdrdao's scanner turns \" and \\ into the character and keeps \NNN as it is;
# a second pass then reads every backslash followed by three digits, including
# one that came from \\, as an octal byte. That pass, and the rule that a string
# is either ASCII with escapes or UTF-8 without, are Util::processMixedString in
# cdrdao 1.2.6's trackdb/util.cc.
_SCANNER_ESCAPE_RE = re.compile(r'\\(["\\])|(\\[0-9]{3})')
_OCTAL_RE = re.compile(r"\\([0-9]{3})")
_OCTAL_DIGITS_RE = re.compile(r"[0-7]*")
# The longest start of a string the grammar's STRING terminal would accept.
_STRING_PREFIX_RE = re.compile(r'"(?:\\[0-9]{3}|\\["\\]|[^"\\])*')


@cache
def _get_parser() -> Lark:
    grammar = resources.files(__package__).joinpath("grammar.lark").read_text()
    return Lark(grammar, start="toc", parser="lalr", propagate_positions=True)


class _String(NamedTuple):
    """A decoded quoted string.

    ``raw`` is cdrdao's distinction between a string written in plain ASCII,
    whose ``\\NNN`` escapes are bytes in the CD-TEXT block's encoding, and one
    holding other characters, which is UTF-8 text and may not use escapes.
    A raw string's escapes are decoded here as ISO-8859-1.
    """

    text: str
    raw: bool


def _decode_string(token: Token) -> _String:
    text = _SCANNER_ESCAPE_RE.sub(lambda match: match[1] or match[2], str(token)[1:-1])
    raw = text.isascii()

    def octal(match: re.Match[str]) -> str:
        if not raw:
            raise TocValidationError("Illegal mixed UTF-8 and binary.")
        # strtol() reads the octal digits it can and a char keeps the low byte.
        digits = _OCTAL_DIGITS_RE.match(match[1])
        assert digits is not None
        return chr(int(digits[0] or "0", 8) & 0xFF)

    return _String(_OCTAL_RE.sub(octal, text), raw)


def _cd_text_string(value: _String, encoding: CdTextEncoding) -> str:
    """Read a raw string's bytes in its block's encoding, as cdrdao does.

    cdrdao only warns about bytes the encoding cannot decode and keeps them,
    but they have no text to hold here, nor to write back.
    """
    if value.raw and encoding is CdTextEncoding.MS_JIS:
        try:
            return value.text.encode("latin-1").decode("cp932")
        except UnicodeDecodeError:
            raise TocValidationError(
                f"CD-TEXT: Illegal byte sequence for {encoding.value}."
            ) from None
    return value.text


class _Isrc(NamedTuple):
    value: str


class _Copy(NamedTuple):
    value: bool


class _PreEmphasis(NamedTuple):
    value: bool


class _Channels(NamedTuple):
    value: Literal[2, 4]


class _Pregap(NamedTuple):
    value: Time


class _Index(NamedTuple):
    value: Time
    line: int


class _Statement(NamedTuple):
    value: TrackStatement
    line: int


class _Offset(NamedTuple):
    value: int


class _CdTextItem(NamedTuple):
    name: CdTextItemName
    value: _String | list[int]
    line: int


class _CdTextBlock(NamedTuple):
    number: int
    encoding: CdTextEncoding | None
    items: list[_CdTextItem]


class _TrackCdText(NamedTuple):
    cd_text: CdText
    #: Lines of the items, keyed by their location inside the track.
    lines: dict[Loc, int]


_Child = object


def _item_loc(number: int, name: CdTextItemName) -> Loc:
    return ("cd_text", "blocks", number, "items", name.value)


def _line(token: Token) -> int:
    # propagate_positions gives every token a position.
    assert token.line is not None
    return token.line


@v_args(meta=True)
class _TocTransformer(Transformer[Token, object]):
    """Builds models from the parse tree, reporting errors with a line number."""

    def __init__(self, filename: str | None = None) -> None:
        super().__init__()
        self._filename = filename
        # The encodings the disc's CD_TEXT sets, which its tracks follow.
        self._encodings: dict[int, CdTextEncoding] = {}
        # Lines of everything a Toc-level check can point at.
        self._lines: dict[Loc, int] = {}
        self._track_count = 0

    @contextmanager
    def _at(self, line: int | None) -> Iterator[None]:
        """Report a validation error raised inside at ``line``."""
        try:
            yield
        except TocValidationError as exc:
            raise TocValidationError(
                exc.message,
                line=exc.line if exc.line is not None else line,
                filename=self._filename,
                loc=exc.loc,
            ) from None

    @contextmanager
    def _located(
        self, lines: Mapping[Loc, int], default: int | None, prefix: Loc = ()
    ) -> Iterator[None]:
        """Report a model's validation error at the line its ``loc`` came from."""
        try:
            yield
        except TocValidationError as exc:
            raise TocValidationError(
                exc.message,
                line=lines.get(exc.loc, default),
                filename=self._filename,
                loc=prefix + exc.loc,
            ) from None

    def _string(self, token: Token) -> _String:
        with self._at(token.line):
            return _decode_string(token)

    # -- disc level ------------------------------------------------------

    def toc(self, meta: Meta, children: list[_Child]) -> Toc:
        catalog: str | None = None
        disc_types: list[DiscType] = []
        first_track_number: int | None = None
        cd_text: CdText | None = None
        tracks: list[Track] = []
        for child in children:
            # DiscType is a str enum, so it must be tested before plain str.
            if isinstance(child, DiscType):
                disc_types.append(child)
            elif isinstance(child, CdText):
                cd_text = child
            elif isinstance(child, Track):
                tracks.append(child)
            elif isinstance(child, int):
                first_track_number = child
            elif isinstance(child, str):
                catalog = child
        with self._located(self._lines, None):
            return Toc(
                catalog=catalog,
                disc_type=disc_types[-1] if disc_types else DiscType.CD_DA,
                superseded_disc_types=disc_types[:-1],
                first_track_number=first_track_number,
                cd_text=cd_text,
                tracks=tracks,
            )

    def catalog(self, meta: Meta, children: list[Token]) -> str:
        with self._at(meta.line):
            return validate_catalog(self._string(children[0]).text)

    def disc_type(self, meta: Meta, children: list[Token]) -> DiscType:
        return DiscType(str(children[0]))

    def first_track_no(self, meta: Meta, children: list[Token]) -> int:
        line = _line(children[0])
        with self._at(line):
            return validate_first_track_number(int(children[0]))

    # -- tracks ----------------------------------------------------------

    def track(self, meta: Meta, children: list[_Child]) -> Track:
        mode_token = children[0]
        assert isinstance(mode_token, Token)
        if str(mode_token) == DataMode.MODE0.value:
            # cdrdao's grammar only allows MODE0 after ZERO.
            raise TocParseError(
                f'syntax error at "{mode_token}"',
                line=mode_token.line,
                column=mode_token.column,
                filename=self._filename,
            )

        sub_channel_mode: SubChannelMode | None = None
        isrc: str | None = None
        copy_permitted: bool | None = None
        pre_emphasis: bool | None = None
        channels: Literal[2, 4] | None = None
        cd_text: CdText | None = None
        pregap: Time | None = None
        statements: list[TrackStatement] = []
        indexes: list[Time] = []
        lines: dict[Loc, int] = {}

        for child in children[1:]:
            if isinstance(child, Token):
                sub_channel_mode = SubChannelMode(str(child))
            elif isinstance(child, _Isrc):
                isrc = child.value
            elif isinstance(child, _Copy):
                copy_permitted = child.value
            elif isinstance(child, _PreEmphasis):
                pre_emphasis = child.value
            elif isinstance(child, _Channels):
                channels = child.value
            elif isinstance(child, _TrackCdText):
                cd_text = child.cd_text
                lines.update(child.lines)
            elif isinstance(child, _Pregap):
                pregap = child.value
            elif isinstance(child, _Statement):
                lines[("statements", len(statements))] = child.line
                statements.append(child.value)
            elif isinstance(child, _Index):
                lines[("indexes", len(indexes))] = child.line
                indexes.append(child.value)

        prefix: Loc = ("tracks", self._track_count)
        self._track_count += 1
        self._lines.update({prefix + loc: line for loc, line in lines.items()})
        with self._located(lines, meta.line, prefix):
            return Track(
                mode=TrackMode(str(mode_token)),
                sub_channel_mode=sub_channel_mode,
                copy_permitted=copy_permitted,
                pre_emphasis=pre_emphasis,
                channels=channels,
                isrc=isrc,
                cd_text=cd_text,
                pregap=pregap,
                statements=statements,
                indexes=indexes,
            )

    def isrc(self, meta: Meta, children: list[Token]) -> _Isrc:
        with self._at(meta.line):
            return _Isrc(validate_isrc(self._string(children[0]).text))

    def copy(self, meta: Meta, children: list[Token]) -> _Copy:
        return _Copy(not children)

    def pre_emphasis(self, meta: Meta, children: list[Token]) -> _PreEmphasis:
        return _PreEmphasis(not children)

    def channels(self, meta: Meta, children: list[Token]) -> _Channels:
        return _Channels(4 if str(children[0]).startswith("FOUR") else 2)

    def pregap(self, meta: Meta, children: list[Time]) -> _Pregap:
        with self._at(meta.line):
            return _Pregap(validate_non_zero_length(children[0], PREGAP_IS_ZERO))

    def index(self, meta: Meta, children: list[Time]) -> _Index:
        return _Index(children[0], meta.line)

    # -- track statements ------------------------------------------------

    def file(self, meta: Meta, children: list[_Child]) -> _Statement:
        keyword = children[0]
        assert isinstance(keyword, Token)
        filename_token = children[1]
        assert isinstance(filename_token, Token)
        rest = children[2:]

        swap = False
        if rest and isinstance(rest[0], Token) and rest[0].type == "SWAP":
            swap = True
            rest = rest[1:]
        offset: int | None = None
        if rest and isinstance(rest[0], _Offset):
            offset = rest[0].value
            rest = rest[1:]

        statement = File(
            filename=self._string(filename_token).text,
            start=rest[0],  # type: ignore[arg-type]
            length=rest[1] if len(rest) > 1 else None,  # type: ignore[arg-type]
            swap=swap,
            offset=offset,
            audiofile=str(keyword) == "AUDIOFILE",
        )
        return _Statement(statement, meta.line)

    def datafile(self, meta: Meta, children: list[_Child]) -> _Statement:
        filename_token = children[0]
        assert isinstance(filename_token, Token)
        rest = children[1:]
        offset: int | None = None
        if rest and isinstance(rest[0], _Offset):
            offset = rest[0].value
            rest = rest[1:]
        statement = DataFile(
            filename=self._string(filename_token).text,
            length=rest[0] if rest else None,  # type: ignore[arg-type]
            offset=offset,
        )
        return _Statement(statement, meta.line)

    def fifo(self, meta: Meta, children: list[_Child]) -> _Statement:
        filename_token = children[0]
        assert isinstance(filename_token, Token)
        statement = Fifo(
            filename=self._string(filename_token).text,
            length=children[1],  # type: ignore[arg-type]
        )
        return _Statement(statement, meta.line)

    def silence(self, meta: Meta, children: list[Time]) -> _Statement:
        with self._at(meta.line):
            length = validate_non_zero_length(children[0], SILENCE_IS_ZERO)
        return _Statement(Silence(length=length), meta.line)

    def zero(self, meta: Meta, children: list[_Child]) -> _Statement:
        data_mode: DataMode | None = None
        sub_channel_mode: SubChannelMode | None = None
        rest = list(children)
        if rest and isinstance(rest[0], Token) and rest[0].type == "MODE":
            data_mode = DataMode(str(rest[0]))
            rest = rest[1:]
        if rest and isinstance(rest[0], Token) and rest[0].type == "SUB_CHANNEL_MODE":
            sub_channel_mode = SubChannelMode(str(rest[0]))
            rest = rest[1:]
        with self._at(meta.line):
            length = validate_non_zero_length(
                rest[0],  # type: ignore[arg-type]
                ZERO_DATA_IS_ZERO,
            )
        statement = Zero(
            length=length, data_mode=data_mode, sub_channel_mode=sub_channel_mode
        )
        return _Statement(statement, meta.line)

    def start(self, meta: Meta, children: list[Time]) -> _Statement:
        return _Statement(Start(position=children[0] if children else None), meta.line)

    def end(self, meta: Meta, children: list[Time]) -> _Statement:
        return _Statement(End(position=children[0] if children else None), meta.line)

    def offset(self, meta: Meta, children: list[Token]) -> _Offset:
        return _Offset(int(children[0]))

    def msf(self, meta: Meta, children: list[Token]) -> Msf:
        with self._at(meta.line):
            return Msf.parse(str(children[0]))

    def time(self, meta: Meta, children: list[Token]) -> Time:
        token = children[0]
        if token.type == "MSF":
            with self._at(meta.line):
                return Msf.parse(str(token))
        return int(token)

    # -- CD-TEXT ---------------------------------------------------------

    def cd_text_global(self, meta: Meta, children: list[_Child]) -> CdText:
        language_map: dict[int, int] = {}
        blocks: list[_CdTextBlock] = []
        for child in children:
            if isinstance(child, dict):
                language_map = child
            else:
                assert isinstance(child, _CdTextBlock)
                blocks.append(child)
        # Only the disc's blocks set encodings; its tracks follow them.
        for block in blocks:
            if block.encoding is not None:
                self._encodings[block.number] = block.encoding
        built, lines = self._cd_text_blocks(blocks)
        self._lines.update(lines)
        with self._located(lines, meta.line, ("cd_text",)):
            return CdText(language_map=language_map, blocks=built)

    def cd_text_track(self, meta: Meta, children: list[_Child]) -> _TrackCdText:
        blocks = [child for child in children if isinstance(child, _CdTextBlock)]
        built, lines = self._cd_text_blocks(blocks)
        with self._located(lines, meta.line, ("cd_text",)):
            return _TrackCdText(CdText(blocks=built), lines)

    def _cd_text_blocks(
        self, blocks: list[_CdTextBlock]
    ) -> tuple[dict[int, CdTextBlock], dict[Loc, int]]:
        """Merge blocks the way cdrdao's CD-TEXT container does.

        cdrdao files every item under its language and pack type, so a block
        number given twice adds to the first block, and an item given twice,
        under either spelling of its pack, keeps the last value.
        """
        encodings: dict[int, CdTextEncoding | None] = {}
        items: dict[int, dict[CdTextItemName, CdTextValue]] = {}
        lines: dict[Loc, int] = {}
        for block in blocks:
            if block.encoding is not None or block.number not in encodings:
                encodings[block.number] = block.encoding
            block_items = items.setdefault(block.number, {})
            encoding = self._encodings.get(block.number, CdTextEncoding.ISO_8859_1)
            for item in block.items:
                alias = CD_TEXT_ALIASES.get(item.name)
                if alias is not None and alias in block_items:
                    del block_items[alias]
                    del lines[_item_loc(block.number, alias)]
                value = item.value
                if isinstance(value, _String):
                    with self._at(item.line):
                        block_items[item.name] = _cd_text_string(value, encoding)
                else:
                    block_items[item.name] = value
                lines[_item_loc(block.number, item.name)] = item.line
        built = {
            number: CdTextBlock(encoding=encodings[number], items=block_items)
            for number, block_items in items.items()
        }
        return built, lines

    def language_map(
        self, meta: Meta, children: list[tuple[int, int]]
    ) -> dict[int, int]:
        return dict(children)

    def language_map_entry(self, meta: Meta, children: list[_Child]) -> tuple[int, int]:
        number_token = children[0]
        assert isinstance(number_token, Token)
        code = children[1]
        assert isinstance(code, int)
        with self._at(number_token.line):
            number = validate_language_number(int(number_token))
        with self._at(meta.end_line):
            return number, validate_language_code(code)

    def language_code(self, meta: Meta, children: list[Token]) -> int:
        token = children[0]
        return LANGUAGE_CODE_EN if token.type == "LANGUAGE_EN" else int(token)

    def cd_text_block(self, meta: Meta, children: list[_Child]) -> _CdTextBlock:
        number_token = children[0]
        assert isinstance(number_token, Token)
        with self._at(number_token.line):
            number = validate_block_number(int(number_token))
        encoding: CdTextEncoding | None = None
        items: list[_CdTextItem] = []
        for child in children[1:]:
            if isinstance(child, Token):
                encoding = CdTextEncoding(str(child))
            else:
                assert isinstance(child, _CdTextItem)
                items.append(child)
        return _CdTextBlock(number, encoding, items)

    def cd_text_item(self, meta: Meta, children: list[_Child]) -> _CdTextItem:
        name_token = children[0]
        assert isinstance(name_token, Token)
        value = children[1]
        assert isinstance(value, (_String, list))
        return _CdTextItem(CdTextItemName(str(name_token)), value, _line(name_token))

    def cd_text_value(self, meta: Meta, children: list[_Child]) -> _String | list[int]:
        child = children[0]
        if isinstance(child, Token):
            return self._string(child)
        assert isinstance(child, list)
        return child

    def binary_data(self, meta: Meta, children: list[Token]) -> list[int]:
        values: list[int] = []
        for position, token in enumerate(children):
            with self._at(token.line):
                values.append(validate_binary_value(int(token)))
                if position == MAX_BINARY_LENGTH:
                    raise TocValidationError(BINARY_DATA_TOO_LONG)
        return values


def parse(text: str, *, filename: str | None = None) -> Toc:
    """Parse TOC file *text*.

    Raises :class:`~tocparser.errors.TocParseError` for syntax errors and
    :class:`~tocparser.errors.TocValidationError` for input that parses but
    breaks a rule cdrdao enforces.
    """
    try:
        tree = _get_parser().parse(text)
    except UnexpectedInput as exc:
        raise _syntax_error(exc, text, filename) from None

    try:
        result = _TocTransformer(filename).transform(tree)
    except VisitError as exc:
        raise _unwrap(exc) from None
    assert isinstance(result, Toc)
    return result


def parse_file(path: str | PathLike[str], *, encoding: str = "utf-8") -> Toc:
    """Parse the TOC file at *path*.

    cdrdao 1.2.5 and later write TOC files in UTF-8. Bytes that do not decode
    in ``encoding`` raise :class:`~tocparser.errors.TocParseError`.
    """
    file = Path(path)
    data = file.read_bytes()
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError as exc:
        # Everything before the bad byte decodes, and gives its line.
        before = _universal_newlines(data[: exc.start].decode(encoding))
        raise TocParseError(
            f"Cannot decode byte 0x{data[exc.start]:02x} as {encoding}",
            line=before.count("\n") + 1,
            filename=str(file),
        ) from None
    return parse(_universal_newlines(text), filename=str(file))


def _universal_newlines(text: str) -> str:
    """Line endings as a file opened in text mode would give them."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _unwrap(error: VisitError) -> BaseException:
    original: BaseException = error
    while isinstance(original, VisitError):
        original = original.orig_exc
    return original if isinstance(original, TocError) else error


def _syntax_error(
    error: UnexpectedInput, text: str, filename: str | None
) -> TocParseError:
    """Word a syntax error the way cdrdao does."""
    if isinstance(error, UnexpectedEOF) or (
        isinstance(error, UnexpectedToken) and error.token.type == "$END"
    ):
        return TocParseError(
            'syntax error at "EOF"', line=text.count("\n") + 1, filename=filename
        )
    if isinstance(error, UnexpectedToken):
        # cdrdao's scanner makes a string's opening quote a token of its own.
        shown = '"' if error.token.type == "STRING" else str(error.token)
        return TocParseError(
            f'syntax error at "{shown}"',
            line=error.line,
            column=error.column,
            filename=filename,
        )
    if isinstance(error, UnexpectedCharacters):
        if error.char == '"':
            return _broken_string(error, text, filename)
        return TocParseError(
            f"Illegal token: {error.char}",
            line=error.line,
            column=error.column,
            filename=filename,
        )
    return TocParseError("syntax error", filename=filename)  # pragma: no cover


def _broken_string(
    error: UnexpectedCharacters, text: str, filename: str | None
) -> TocParseError:
    """A string that does not lex: an illegal backslash, or no closing quote."""
    position = error.pos_in_stream
    assert position is not None
    prefix = _STRING_PREFIX_RE.match(text, position)
    assert prefix is not None
    end = prefix.end()
    if end == len(text):
        return TocParseError(
            'syntax error at "EOF"', line=error.line, filename=filename
        )
    if text[end] == "\\":
        # A backslash starting no escape cdrdao knows.
        return TocParseError(
            "Illegal token: \\",
            line=text.count("\n", 0, end) + 1,
            column=end - text.rfind("\n", 0, end),
            filename=filename,
        )
    # A complete string where the grammar allows none. Lark's contextual lexer
    # reports that as an unexpected STRING token instead, so this only guards
    # against the lexer changing its mind.
    return TocParseError(  # pragma: no cover
        'syntax error at """', line=error.line, column=error.column, filename=filename
    )
