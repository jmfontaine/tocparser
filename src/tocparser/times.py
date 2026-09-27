"""Time values used in TOC files.

A position or a length is written either as an ``MM:SS:FF`` triple counting
frames (also called blocks) at 75 frames per second, or as a bare integer.
A bare integer means *samples* for audio tracks and *bytes* for data tracks,
so the two forms are not interchangeable: a sample count that is not frame
aligned has no MSF representation. Both forms are therefore preserved as
written, and :data:`Time` is the union of the two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TypeAlias

from tocparser.errors import TocValidationError

__all__ = [
    "FRAMES_PER_SECOND",
    "SAMPLES_PER_FRAME",
    "SECONDS_PER_MINUTE",
    "Msf",
    "Time",
]

FRAMES_PER_SECOND = 75
SECONDS_PER_MINUTE = 60
#: 44100 Hz / 75 frames per second.
SAMPLES_PER_FRAME = 588

_MSF_RE = re.compile(r"\A([0-9]+):([0-9]+):([0-9]+)\Z")


@dataclass(frozen=True, order=True)
class Msf:
    """A position or length expressed as minutes, seconds and frames."""

    minutes: int
    seconds: int
    frames: int

    def __post_init__(self) -> None:
        for field in (self.minutes, self.seconds, self.frames):
            if isinstance(field, bool) or not isinstance(field, int):
                raise TypeError(f"MSF fields must be integers, not {field!r}")
        if self.minutes < 0:
            raise TocValidationError(f"Illegal minute field: {self.minutes}")
        if not 0 <= self.seconds < SECONDS_PER_MINUTE:
            raise TocValidationError(f"Illegal second field: {self.seconds}")
        if not 0 <= self.frames < FRAMES_PER_SECOND:
            raise TocValidationError(f"Illegal fraction field: {self.frames}")

    @property
    def total_frames(self) -> int:
        """The value as a plain frame (block) count."""
        return (
            self.minutes * SECONDS_PER_MINUTE + self.seconds
        ) * FRAMES_PER_SECOND + self.frames

    @classmethod
    def from_frames(cls, frames: int) -> Msf:
        """Build an :class:`Msf` from a frame count."""
        if frames < 0:
            raise TocValidationError(f"Illegal frame count: {frames}")
        minutes, rest = divmod(frames, FRAMES_PER_SECOND * SECONDS_PER_MINUTE)
        seconds, remaining_frames = divmod(rest, FRAMES_PER_SECOND)
        return cls(minutes, seconds, remaining_frames)

    @classmethod
    def parse(cls, text: str) -> Msf:
        """Parse an ``MM:SS:FF`` string."""
        match = _MSF_RE.match(text)
        if match is None:
            raise TocValidationError(f"Illegal MSF value: {text}")
        return cls(int(match[1]), int(match[2]), int(match[3]))

    def to_samples(self) -> int:
        """The value as a count of 16-bit stereo samples."""
        return self.total_frames * SAMPLES_PER_FRAME

    def to_bytes(self, block_size: int) -> int:
        """The value as a byte count, given a track's block size."""
        return self.total_frames * block_size

    def __str__(self) -> str:
        return f"{self.minutes:02d}:{self.seconds:02d}:{self.frames:02d}"


#: A position or length, either frame-based (:class:`Msf`) or a raw
#: sample/byte count.
Time: TypeAlias = Msf | int
