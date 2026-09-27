#!/usr/bin/env python
"""Smoke-check an installed tocparser.

Run it with the interpreter of an environment where the wheel or sdist was
installed from its published metadata, not from ``uv.lock``. It checks that the
package is imported from that environment rather than from a checkout, that the
dependency floors the metadata declares were honored, and that the grammar
shipped by parsing and writing a TOC file.

The pydantic floor is the interesting part. Python 3.15 needs pydantic 2.14 or
newer, whose pydantic-core ships Python 3.15 wheels, and environment markers
are easy to write in a way that silently skips that floor on a release
candidate, leaving the install with an unbuildable pydantic-core, or with no
pydantic at all.
"""

from __future__ import annotations

import sys
import sysconfig
from importlib.metadata import version
from pathlib import Path

import lark
import pydantic

import tocparser

MINIMUM_LARK = (1, 2)
MINIMUM_PYDANTIC = (2, 9)
# KLUDGE: mirrors the temporary Python 3.15 clause in pyproject.toml. When that
# clause becomes `pydantic>=2.14; python_version == '3.15'`, drop only the
# upper bound here: the 3.15 branch must keep checking the 2.14 minimum.
PYDANTIC_RANGE_315 = ((2, 14), (2, 15))


def fail(message: str) -> None:
    print(f"check_installed_package: {message}", file=sys.stderr)
    raise SystemExit(1)


def major_minor(text: str) -> tuple[int, int]:
    major, minor = text.split(".")[:2]
    return int(major), int(minor)


def check_location() -> None:
    package = Path(tocparser.__file__).resolve().parent
    site_packages = Path(sysconfig.get_paths()["purelib"]).resolve()
    if not package.is_relative_to(site_packages):
        fail(f"tocparser was imported from {package}, not from {site_packages}")
    if not (package / "py.typed").is_file():
        fail("the installed package has no py.typed marker")
    print(f"check_installed_package: imported from {package}")


def check_dependencies() -> None:
    lark_version = major_minor(lark.__version__)
    if lark_version < MINIMUM_LARK:
        fail(f"lark {lark.__version__} is below the declared floor")

    pydantic_version = major_minor(pydantic.VERSION)
    if sys.version_info[:2] == (3, 15):
        low, high = PYDANTIC_RANGE_315
        if not low <= pydantic_version < high:
            fail(
                f"pydantic {pydantic.VERSION} is outside the Python 3.15 range "
                f"{low}..{high}"
            )
    elif pydantic_version < MINIMUM_PYDANTIC:
        fail(f"pydantic {pydantic.VERSION} is below the declared floor")
    print(
        f"check_installed_package: lark {lark.__version__}, pydantic {pydantic.VERSION}"
    )


def check_round_trip() -> None:
    if tocparser.__version__ != version("tocparser"):
        fail(
            f"__version__ {tocparser.__version__} does not match the installed metadata"
        )
    source = (
        'CD_DA\nCATALOG "0602498647295"\n'
        'CD_TEXT { LANGUAGE 0 { TITLE "The Downward Spiral" '
        'PERFORMER "Nine Inch Nails" } }\n'
        'TRACK AUDIO\nISRC "USIR19400529"\nFILE "closer.wav" 0 06:13:23\n'
    )
    toc = tocparser.parse(source)
    if tocparser.parse(tocparser.dumps(toc)) != toc:
        fail("a TOC file did not survive a round trip")
    print(
        f"check_installed_package: tocparser {tocparser.__version__} parses and writes"
    )


def main() -> None:
    check_location()
    check_dependencies()
    check_round_trip()


if __name__ == "__main__":
    main()
