"""Exceptions raised by :mod:`tocparser`."""

from __future__ import annotations

from typing import TypeAlias

__all__ = [
    "Loc",
    "TocError",
    "TocParseError",
    "TocValidationError",
]

#: A path into a model, made of field names and indexes, e.g.
#: ``("tracks", 0, "statements", 2)``.
Loc: TypeAlias = tuple[str | int, ...]


class TocError(Exception):
    """Base class for every error raised by :mod:`tocparser`."""


class TocParseError(TocError):
    """The input is not syntactically valid.

    Mirrors cdrdao's ``file:line: message`` reporting.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        column: int | None = None,
        filename: str | None = None,
    ) -> None:
        self.message = message
        self.line = line
        self.column = column
        self.filename = filename
        super().__init__(_format_location(message, filename, line, column))


class TocValidationError(TocError):
    """The input breaks a rule cdrdao itself enforces.

    ``loc`` locates the problem inside the model that raised it, so an error
    raised while building models by hand still says where it is. ``line`` is
    only known when the error comes from parsing text.
    """

    def __init__(
        self,
        message: str,
        *,
        line: int | None = None,
        filename: str | None = None,
        loc: Loc = (),
    ) -> None:
        self.message = message
        self.line = line
        self.filename = filename
        self.loc = loc
        super().__init__(_format_location(message, filename, line, None))


def _format_location(
    message: str,
    filename: str | None,
    line: int | None,
    column: int | None,
) -> str:
    location = ""
    if filename is not None:
        location += f"{filename}:"
    if line is not None:
        location += f"{line}:"
        if column is not None:
            location += f"{column}:"
    return f"{location} {message}" if location else message
