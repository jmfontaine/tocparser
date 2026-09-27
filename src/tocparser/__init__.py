"""Parse and write cdrdao TOC files.

>>> from tocparser import parse, dumps
>>> toc = parse('CD_DA\\nTRACK AUDIO\\nFILE "hurt.wav" 0\\n')
>>> toc.tracks[0].mode.value
'AUDIO'
"""

from __future__ import annotations

from importlib.metadata import version

from tocparser.errors import (
    Loc,
    TocError,
    TocParseError,
    TocValidationError,
)
from tocparser.models import (
    CdText,
    CdTextBlock,
    CdTextEncoding,
    CdTextItemName,
    CdTextValue,
    ContentItem,
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
)
from tocparser.parser import parse, parse_file
from tocparser.serializer import dump, dumps
from tocparser.times import (
    FRAMES_PER_SECOND,
    SAMPLES_PER_FRAME,
    SECONDS_PER_MINUTE,
    Msf,
    Time,
)

__version__ = version("tocparser")

__all__ = [
    "FRAMES_PER_SECOND",
    "SAMPLES_PER_FRAME",
    "SECONDS_PER_MINUTE",
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
    "Loc",
    "Msf",
    "Silence",
    "Start",
    "SubChannelMode",
    "Time",
    "Toc",
    "TocError",
    "TocParseError",
    "TocValidationError",
    "Track",
    "TrackMode",
    "TrackStatement",
    "Zero",
    "__version__",
    "dump",
    "dumps",
    "parse",
    "parse_file",
]
