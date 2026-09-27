"""Render :class:`~tocparser.models.Toc` objects back to TOC file text.

The layout follows the files cdrdao itself writes: two-space nesting inside
``CD_TEXT``, binary CD-TEXT arrays wrapped at twelve values per line, and both
of the comments cdrdao generates -- a ``// Track N`` header before each track
and a ``// length in bytes:`` annotation on data lengths. Comments written by
hand are not preserved, so serializing is meaning-preserving rather than
byte-exact. Text is written as UTF-8, as cdrdao 1.2.5 and later write it.
"""

from __future__ import annotations

import re
from os import PathLike
from pathlib import Path

from tocparser.errors import TocValidationError
from tocparser.models import (
    CdText,
    CdTextValue,
    DataFile,
    End,
    Fifo,
    File,
    Silence,
    Start,
    Toc,
    Track,
    TrackMode,
    Zero,
)
from tocparser.times import Msf, Time

__all__ = ["dump", "dumps"]

_INDENT = "  "
_BINARY_VALUES_PER_LINE = 12
_BINARY_CONTINUATION_INDENT = " " * 15

# A backslash before three digits, any other backslash, and a quote.
_TO_ESCAPE_RE = re.compile(r'(\\(?=[0-9]{3}))|(\\)|(")')


def escape(text: str) -> str:
    """Escape *text* so cdrdao reads it back unchanged.

    A quote and a backslash are escaped with a backslash, except a backslash
    followed by three digits: cdrdao reads that as an octal escape even when
    the backslash was itself escaped, so it is written as ``\\134``, the octal
    escape for a backslash. cdrdao rejects octal escapes in text holding
    non-ASCII characters, so such text cannot be written at all.
    """

    def replace(match: re.Match[str]) -> str:
        if match[1] is not None:
            if not text.isascii():
                raise TocValidationError(
                    f"Cannot write {text!r}: a backslash followed by three digits "
                    "needs an octal escape, which cdrdao rejects in non-ASCII text."
                )
            return "\\134"
        return "\\" + match[0]

    return _TO_ESCAPE_RE.sub(replace, text)


def _quote(text: str) -> str:
    return f'"{escape(text)}"'


def _time(value: Time) -> str:
    """Render a position or length; ``Msf.__str__`` zero-pads, ints do not."""
    return str(value)


def _binary(name: str, values: list[int], indent: str) -> list[str]:
    if not values:
        return [f"{indent}{name} {{}}"]
    lines: list[str] = []
    for offset in range(0, len(values), _BINARY_VALUES_PER_LINE):
        chunk = values[offset : offset + _BINARY_VALUES_PER_LINE]
        if offset == 0:
            # The opening brace supplies the padding of the first value, so
            # cdrdao writes that one bare and pads the rest to two columns.
            rendered = str(chunk[0]) + "".join(f", {value:2d}" for value in chunk[1:])
            prefix = f"{indent}{name} {{ "
        else:
            # On a continued line every value is padded, the first included,
            # which only shows once a line begins with more than one digit.
            rendered = ", ".join(f"{value:2d}" for value in chunk)
            prefix = _BINARY_CONTINUATION_INDENT
        suffix = "," if offset + _BINARY_VALUES_PER_LINE < len(values) else "}"
        lines.append(f"{prefix}{rendered}{suffix}")
    return lines


def _cd_text_value(name: str, value: CdTextValue, indent: str) -> list[str]:
    if isinstance(value, str):
        return [f"{indent}{name} {_quote(value)}"]
    return _binary(name, value, indent)


def _cd_text(cd_text: CdText, indent: str = "") -> list[str]:
    lines = [f"{indent}CD_TEXT {{"]
    inner = indent + _INDENT
    if cd_text.language_map:
        lines.append(f"{inner}LANGUAGE_MAP {{")
        for number, code in cd_text.language_map.items():
            lines.append(f"{inner}{_INDENT}{number}: {code}")
        lines.append(f"{inner}}}")
    for number, block in cd_text.blocks.items():
        lines.append(f"{inner}LANGUAGE {number} {{")
        if block.encoding is not None:
            lines.append(f"{inner}{_INDENT}{block.encoding.value}")
        for name, value in block.items.items():
            lines.extend(_cd_text_value(name.value, value, inner + _INDENT))
        lines.append(f"{inner}}}")
    lines.append(f"{indent}}}")
    return lines


def _byte_length(length: Time, track: Track) -> int:
    """The count cdrdao annotates a data length with.

    On an audio track cdrdao counts samples rather than bytes while still
    labeling the comment "length in bytes"; that quirk is reproduced here so
    the output matches.
    """
    if not isinstance(length, Msf):
        return length
    if track.mode is TrackMode.AUDIO:
        return length.to_samples()
    return length.to_bytes(track.block_size)


def _length_comment(length: Time, track: Track) -> str:
    return f" // length in bytes: {_byte_length(length, track)}"


def _statement(statement: object, track: Track) -> str:
    if isinstance(statement, File):
        parts = [
            "AUDIOFILE" if statement.audiofile else "FILE",
            _quote(statement.filename),
        ]
        if statement.swap:
            parts.append("SWAP")
        if statement.offset is not None:
            parts.append(f"#{statement.offset}")
        parts.append(_time(statement.start))
        if statement.length is not None:
            parts.append(_time(statement.length))
        return " ".join(parts)

    if isinstance(statement, DataFile):
        parts = ["DATAFILE", _quote(statement.filename)]
        if statement.offset is not None:
            parts.append(f"#{statement.offset}")
        if statement.length is None:
            return " ".join(parts)
        parts.append(_time(statement.length))
        line = " ".join(parts)
        # cdrdao annotates data lengths, but not ones it wrote as FILE.
        if track.mode is not TrackMode.AUDIO:
            line += _length_comment(statement.length, track)
        return line

    if isinstance(statement, Fifo):
        line = f"FIFO {_quote(statement.filename)} {_time(statement.length)}"
        # cdrdao only annotates a FIFO whose length lands on a block boundary,
        # which is exactly when it writes the length as MSF.
        if isinstance(statement.length, Msf):
            line += _length_comment(statement.length, track)
        return line

    if isinstance(statement, Silence):
        return f"SILENCE {_time(statement.length)}"

    if isinstance(statement, Zero):
        parts = ["ZERO"]
        if statement.data_mode is not None:
            parts.append(statement.data_mode.value)
        if statement.sub_channel_mode is not None:
            parts.append(statement.sub_channel_mode.value)
        parts.append(_time(statement.length))
        return " ".join(parts)

    if isinstance(statement, Start):
        return (
            "START"
            if statement.position is None
            else f"START {_time(statement.position)}"
        )

    if isinstance(statement, End):
        return (
            "END" if statement.position is None else f"END {_time(statement.position)}"
        )

    raise TypeError(f"Unsupported track statement: {statement!r}")  # pragma: no cover


def _track(track: Track) -> list[str]:
    header = f"TRACK {track.mode.value}"
    if track.sub_channel_mode is not None:
        header += f" {track.sub_channel_mode.value}"
    lines = [header]

    if track.copy_permitted is not None:
        lines.append("COPY" if track.copy_permitted else "NO COPY")
    if track.pre_emphasis is not None:
        lines.append("PRE_EMPHASIS" if track.pre_emphasis else "NO PRE_EMPHASIS")
    if track.channels is not None:
        lines.append(
            "FOUR_CHANNEL_AUDIO" if track.channels == 4 else "TWO_CHANNEL_AUDIO"
        )
    if track.isrc is not None:
        lines.append(f"ISRC {_quote(track.isrc)}")
    if track.cd_text is not None:
        lines.extend(_cd_text(track.cd_text))
    if track.pregap is not None:
        lines.append(f"PREGAP {_time(track.pregap)}")

    lines.extend(_statement(statement, track) for statement in track.statements)
    lines.extend(f"INDEX {_time(index)}" for index in track.indexes)
    return lines


def dumps(toc: Toc) -> str:
    """Render *toc* as TOC file text.

    Models can be changed after they are built, so *toc* is validated again
    first: an invalid one raises instead of producing a file cdrdao rejects.
    """
    toc = Toc.model_validate(toc.model_dump())
    lines: list[str] = [toc.disc_type.value, ""]
    if toc.catalog is not None:
        lines.append(f"CATALOG {_quote(toc.catalog)}")
    if toc.first_track_number is not None:
        lines.append(f"FIRST_TRACK_NO {toc.first_track_number}")
    if toc.cd_text is not None:
        lines.extend(_cd_text(toc.cd_text))

    number = toc.first_track_number if toc.first_track_number is not None else 1
    for offset, track in enumerate(toc.tracks):
        lines.append("")
        lines.append(f"// Track {number + offset}")
        lines.extend(_track(track))
        lines.append("")

    return "\n".join(lines) + "\n"


def dump(toc: Toc, path: str | PathLike[str], *, encoding: str = "utf-8") -> None:
    """Write *toc* to the file at *path*."""
    Path(path).write_text(dumps(toc), encoding=encoding)
