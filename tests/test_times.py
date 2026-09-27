"""Tests for the MSF value type."""

from __future__ import annotations

import pytest

from tocparser import Msf, TocValidationError
from tocparser.times import SAMPLES_PER_FRAME


def test_total_frames_counts_at_75_fps() -> None:
    assert Msf(0, 0, 1).total_frames == 1
    assert Msf(0, 1, 0).total_frames == 75
    assert Msf(1, 0, 0).total_frames == 75 * 60
    assert Msf(1, 2, 3).total_frames == 4653


@pytest.mark.parametrize("frames", [0, 1, 74, 75, 4653, 75 * 60 * 99])
def test_from_frames_round_trips(frames: int) -> None:
    assert Msf.from_frames(frames).total_frames == frames


def test_parse_accepts_padded_and_unpadded() -> None:
    assert Msf.parse("00:02:48") == Msf(0, 2, 48)
    assert Msf.parse("0:10:0") == Msf(0, 10, 0)
    assert Msf.parse("000:002:000") == Msf(0, 2, 0)


def test_str_is_zero_padded() -> None:
    assert str(Msf(0, 2, 48)) == "00:02:48"
    assert str(Msf(1, 0, 0)) == "01:00:00"
    # Minutes are not capped at two digits.
    assert str(Msf(100, 0, 0)) == "100:00:00"


def test_conversions() -> None:
    msf = Msf(0, 1, 0)
    assert msf.to_samples() == 75 * SAMPLES_PER_FRAME
    assert msf.to_bytes(2352) == 75 * 2352
    assert msf.to_bytes(2048) == 75 * 2048


def test_ordering_and_hashing() -> None:
    assert Msf(0, 2, 0) < Msf(0, 2, 1) < Msf(0, 3, 0) < Msf(1, 0, 0)
    assert len({Msf(0, 2, 0), Msf(0, 2, 0)}) == 1


@pytest.mark.parametrize(
    ("minutes", "seconds", "frames"),
    [(-1, 0, 0), (0, 60, 0), (0, -1, 0), (0, 0, 75), (0, 0, -1)],
)
def test_out_of_range_fields_are_rejected(minutes: int, seconds: int, frames: int) -> None:
    with pytest.raises(TocValidationError):
        Msf(minutes, seconds, frames)


# The last one is written with Arabic-Indic digits, which are not ASCII digits.
@pytest.mark.parametrize(
    "text", ["", "1:2", "1:2:3:4", "a:b:c", "-1:0:0", "\u0660:\u0660\u0662:\u0660\u0660"]
)
def test_parse_rejects_malformed_input(text: str) -> None:
    with pytest.raises(TocValidationError):
        Msf.parse(text)


@pytest.mark.parametrize("fields", [(True, 0, 0), ("1", 2, 3), (0, 1.5, 0)])
def test_fields_must_be_integers(fields: tuple[object, object, object]) -> None:
    with pytest.raises(TypeError):
        Msf(*fields)  # type: ignore[arg-type]


def test_from_frames_rejects_negative() -> None:
    with pytest.raises(TocValidationError):
        Msf.from_frames(-1)
