#!/usr/bin/env python3
"""Add a TOC file to ``tests/corpus/``.

Reads the disc in the drive with cdrdao, or takes a ``.toc`` file cdrdao wrote
earlier, and installs it as the next number. Set ``CDRDAO_DEVICE`` to choose a
drive; ``cdrdao scanbus`` lists them.

A TOC file describes one session and cdrdao reads one session at a time, so a
multi-session disc becomes one corpus file per session: a CD-Extra's audio is
session 1 and its data track session 2. Every session is read unless
``--session`` asks for one, since nothing about a disc announces that it has
more than the one cdrdao reads by default.

One read per session, because that is all some drives will do. Each read is
compared against the corpus two ways before it is kept: by its bytes, and by
where the disc says its tracks begin, which recognizes a disc already here even
when a second reading of it would not be byte-identical.

``--verify`` reads a session a second time and keeps it only if the two reads
agree. A read can quietly come back poorer than the disc really is, short of
pregaps or ISRCs, and cdrdao reports success either way. It costs a second read,
which not every drive gives up willingly.

Each file installed is listed in ``tests/corpus/cdrdao-versions.csv`` with the
cdrdao version that wrote it: the installed one for a disc read here, and
``--cdrdao-version`` (default: unknown) for a TOC_FILE written elsewhere.

Run it through ``just add-toc``.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from tocparser import DataFile, Fifo, File, Msf, Silence, Start, TocError, Zero, dumps, parse_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = PROJECT_ROOT / "tests" / "corpus"
#: Corpus files are numbered; README.md and anything else there is not one.
NUMBERED = re.compile(r"\d{5}\.toc")
#: Which cdrdao version wrote each corpus file.
VERSIONS = CORPUS_DIR / "cdrdao-versions.csv"
CDRDAO_VERSION = re.compile(r"[0-9]+(\.[0-9]+)+|unknown")


def die(message: str) -> NoReturn:
    print(f"add-toc: {message}", file=sys.stderr)
    raise SystemExit(1)


def corpus_files() -> list[Path]:
    return sorted(path for path in CORPUS_DIR.glob("*.toc") if NUMBERED.fullmatch(path.name))


def drive_status() -> tuple[str, int] | None:
    """The disc's ``/dev`` node and session count, or None when the drive is empty.

    An empty drive prints no ``Name:`` line. Worth telling apart, because cdrdao
    answers a read of an empty drive with a SCSI illegal request that reads like
    a bad command line rather than a missing disc.
    """
    result = subprocess.run(["drutil", "status"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    status = result.stdout
    disc = re.search(r"Name:\s+(/dev/\S+)", status)
    sessions = re.search(r"Sessions:\s+(\d+)", status)
    if disc is None or sessions is None:
        return None
    return disc.group(1), int(sessions.group(1))


def disc_sessions(requested: int | None) -> list[int]:
    """Which sessions of the disc in the drive to read."""
    if sys.platform != "darwin":
        # drutil is macOS. Elsewhere, take cdrdao's own default of the first.
        return [requested] if requested is not None else [1]

    status = drive_status()
    if status is None:
        die(
            "the drive reports no disc. If one is in there, the drive has lost track of "
            "it: eject it, put it back, and try again."
        )
    _, sessions = status
    if requested is not None:
        return [requested]
    if sessions > 1:
        print(f"add-toc: {sessions} sessions on this disc, reading each one.", flush=True)
    return list(range(1, sessions + 1))


def _unmount(disc: str, *, force: bool) -> subprocess.CompletedProcess[str]:
    command = ["diskutil", "unmountDisk", *(["force"] if force else []), disc]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def disc_gone() -> bool:
    """True when the drive holds no disc, on a platform that can tell."""
    return sys.platform == "darwin" and drive_status() is None


def unmount_disc() -> bool:
    """Hand the drive over to cdrdao. Done before every read, for two reasons.

    A mounted disc locks cdrdao out of the device, and the OS can pick the disc
    back up between reads. It also fails plainly when the drive reports no disc,
    which cdrdao otherwise answers with a SCSI illegal request that reads like a
    bad command line. A drive can report that about a disc that never moved.
    """
    if sys.platform != "darwin":
        return True
    status = drive_status()
    if status is None:
        # Losing the disc mid-run leaves whatever was already installed intact,
        # so report it and let the caller finish rather than exiting here.
        print(
            "add-toc: the drive reports no disc. It can lose track of a disc that never "
            "moved; eject it, put it back, and run add-toc again.",
            file=sys.stderr,
        )
        return False
    disc = status[0]
    attempt = _unmount(disc, force=False)
    if attempt.returncode == 0:
        return True

    # Something is holding the disc: an on-access virus scanner, in practice,
    # which also reads the drive while cdrdao is trying to. Forcing it is safe
    # on read-only media, and better than reading a drive two processes share.
    held_by = " ".join(
        line.strip()
        for line in (attempt.stderr + attempt.stdout).splitlines()
        if "dissent" in line.lower()
    )
    forced = _unmount(disc, force=True)
    if forced.returncode == 0:
        print(f"add-toc: had to force {disc} off the OS. {held_by}".rstrip(), flush=True)
        return True

    print(
        f"add-toc: cannot take {disc} from the OS. {held_by or forced.stderr.strip()}".rstrip(),
        file=sys.stderr,
    )
    return False


def env_flag(name: str) -> bool:
    """Read a yes/no environment variable, so that VERIFY=0 means no."""
    value = os.environ.get(name, "").strip().lower()
    if value in ("", "0", "false", "no", "off"):
        return False
    if value in ("1", "true", "yes", "on"):
        return True
    die(f"{name} must be 1 or 0, not {value!r}.")


def env_session() -> int | None:
    value = os.environ.get("CDRDAO_SESSION")
    if value is not None and not value.isdigit():
        die(f"CDRDAO_SESSION must be a session number, not {value!r}.")
    return int(value) if value is not None else None


def cdrdao_command(destination: Path, session: int) -> list[str]:
    """How to ask cdrdao for one session.

    --datafile keeps the FILE lines saying track.wav like the rest of the corpus,
    and no --fast-toc, because the slow read is what finds the pregaps, index
    marks and ISRCs that make these files worth testing against. Session 1 is
    cdrdao's own default and is left unsaid, so an ordinary single-session disc
    is read with exactly the command the rest of the corpus was read with.
    """
    command = ["cdrdao", "read-toc", "--datafile", "track.wav"]
    device = os.environ.get("CDRDAO_DEVICE")
    if device:
        command += ["--device", device]
    if session > 1:
        command += ["--session", str(session)]
    return [*command, str(destination)]


def read_session(destination: Path, session: int) -> bool:
    """Write the TOC of one session to ``destination``, or say why it could not."""
    if not unmount_disc():
        return False
    try:
        subprocess.run(cdrdao_command(destination, session), check=True)
    except FileNotFoundError:
        die("cdrdao is not installed.")
    except subprocess.CalledProcessError as error:
        # One unreadable session does not spoil the sessions that did read.
        print(
            f"add-toc: cdrdao failed on session {session} with exit code {error.returncode}.",
            file=sys.stderr,
        )
        return False
    return True


def _frames(value: object) -> int | None:
    """A time as a frame count.

    Zero is zero in any unit, and cdrdao writes the first track's start as a bare
    ``0``. Any other bare integer counts samples or bytes, which cannot be
    compared with frames, so it gives None.
    """
    if isinstance(value, Msf):
        return value.total_frames
    return 0 if value == 0 else None


def disc_signature(path: Path) -> tuple[tuple[int, ...], int] | None:
    """Where each track sits on the disc, and where the disc ends.

    This is what two readings of one disc agree on even when their bytes do not.
    A read that finds a pregap moves it into the track that follows and records
    it as START, so a track's position is its file start plus its pregap either
    way, and comes back to the position the disc's own table of contents gives.
    None when a file counts in samples or bytes, or writes START without a time,
    neither of which can be compared this way.
    """
    try:
        toc = parse_file(path)
    except TocError:
        return None

    positions: list[int] = []
    end = 0
    for track in toc.tracks:
        start: int | None = None
        length: int | None = None
        pregap = 0
        for statement in track.statements:
            if isinstance(statement, Start):
                if statement.position is None:
                    return None
                written = _frames(statement.position)
                if written is None:
                    return None
                pregap = written
            elif start is None and isinstance(statement, File | DataFile | Fifo | Silence | Zero):
                # Only FILE carries an offset into its data file; the rest begin
                # where the track begins.
                offset = statement.start if isinstance(statement, File) else Msf(0, 0, 0)
                start = _frames(offset)
                length = _frames(statement.length) if statement.length is not None else None
        if start is None:
            return None
        positions.append(start + pregap)
        if length is not None:
            end = start + length
    return tuple(positions), end


def same_disc_as(candidate: Path) -> Path | None:
    """The corpus file describing the same disc, by where its tracks begin."""
    signature = disc_signature(candidate)
    if signature is None:
        return None
    return next((path for path in corpus_files() if disc_signature(path) == signature), None)


def duplicate_of(candidate: Path) -> Path | None:
    """The corpus file holding exactly these bytes, if there is one."""
    contents = candidate.read_bytes()
    return next((path for path in corpus_files() if path.read_bytes() == contents), None)


def describe(path: Path) -> str:
    """What a TOC file holds, in the terms a flaky read gets wrong."""
    text = path.read_text()
    counts = (
        len(re.findall(r"^TRACK ", text, re.MULTILINE)),
        len(re.findall(r"^START", text, re.MULTILINE)),
        len(re.findall(r"^ISRC ", text, re.MULTILINE)),
    )
    return "{} tracks, {} pregaps, {} ISRCs, {} bytes".format(*counts, path.stat().st_size)


def reread_agrees(work: Path, session: int, first: Path) -> bool:
    """Read a session again, and say whether it came back the same."""
    print(f"add-toc: reading session {session} again to check it. Leave the disc in.", flush=True)
    second = work / f"session{session}-again.toc"
    if not read_session(second, session):
        return False
    if first.read_bytes() == second.read_bytes():
        return True

    print(
        f"add-toc: session {session} read differently twice, so neither read can be "
        f"trusted. Not added.\n"
        f"  read 1: {describe(first)}\n"
        f"  read 2: {describe(second)}\n"
        f"add-toc: try again, or drop --verify to keep the first read.",
        file=sys.stderr,
    )
    return False


def next_number() -> str:
    return f"{max((int(path.stem) for path in corpus_files()), default=0) + 1:05d}"


def install(candidate: Path, version: str) -> Path:
    """Copy ``candidate`` in as the next number, and record who wrote it.

    tests/test_corpus.py requires every corpus file to be listed in the versions
    file, and nothing else to be, so a failure part-way undoes both halves. If
    undoing one fails too, it says so and what to fix by hand; the original
    error is the one raised either way.
    """
    destination = CORPUS_DIR / f"{next_number()}.toc"
    listed = VERSIONS.stat().st_size
    try:
        shutil.copyfile(candidate, destination)
        destination.chmod(0o644)
        with VERSIONS.open("a", encoding="utf-8") as versions:
            versions.write(f"{destination.name},{version}\n")
    except BaseException:
        # Includes an interrupt, which can land between the two halves too.
        _undo(
            f"remove {destination.relative_to(PROJECT_ROOT)}",
            lambda: destination.unlink(missing_ok=True),
        )
        _undo(f"cut {VERSIONS.name} back to {listed} bytes", lambda: _truncate(VERSIONS, listed))
        raise
    print(
        f"add-toc: added {destination.relative_to(PROJECT_ROOT)} (cdrdao version: {version}).",
        flush=True,
    )
    return destination


def _truncate(path: Path, size: int) -> None:
    with path.open("r+b") as handle:
        handle.truncate(size)


def _undo(what: str, step: Callable[[], None]) -> None:
    """Run one cleanup step, reporting rather than raising if it fails."""
    try:
        step()
    except OSError as error:
        print(f"add-toc: could not {what} ({error}); do it by hand.", file=sys.stderr)


def installed_cdrdao_version() -> str:
    """The version of the cdrdao that will read the disc."""
    try:
        result = subprocess.run(["cdrdao", "version"], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        die("cdrdao is not installed.")
    # cdrdao prints "Cdrdao version 1.2.6 - (C) ..." on stderr.
    match = re.search(r"version (\S+)", result.stdout + result.stderr)
    if match is None or not CDRDAO_VERSION.fullmatch(match[1]):
        die(f"cannot tell the cdrdao version from: {(result.stdout + result.stderr).strip()!r}")
    return match[1]


def keep(candidate: Path, *, force: bool, version: str) -> Path | None:
    """Install a read, unless the corpus already has that disc."""
    duplicate = duplicate_of(candidate)
    if duplicate is not None:
        print(f"add-toc: identical to {duplicate.name}. Not added.", file=sys.stderr)
        return None

    if not force:
        known = same_disc_as(candidate)
        if known is not None:
            print(
                f"add-toc: this is the disc already in {known.name}, by where its tracks "
                f"begin, read differently. Not added. Pass --force to keep it anyway.",
                file=sys.stderr,
            )
            return None
    return install(candidate, version)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "toc_file",
        nargs="?",
        type=Path,
        help="a .toc file cdrdao wrote earlier; omit to read the disc in the drive",
    )
    parser.add_argument(
        "--session",
        type=int,
        default=env_session(),
        metavar="N",
        help="read only this session, e.g. 2 for the data track of a CD-Extra "
        "(default: $CDRDAO_SESSION, else every session on the disc)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        default=env_flag("VERIFY"),
        help="read each session a second time and keep it only if the reads agree, "
        "at the cost of a second read (default: $VERIFY)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=env_flag("FORCE"),
        help="keep the read even if the corpus already describes that disc (default: $FORCE)",
    )
    parser.add_argument(
        "--cdrdao-version",
        metavar="VERSION",
        help="the cdrdao version that wrote TOC_FILE, e.g. 1.2.6 (default: unknown); "
        "a disc read here records the installed cdrdao's version",
    )
    arguments = parser.parse_args()
    source: Path | None = arguments.toc_file
    session: int | None = arguments.session
    verify: bool = arguments.verify
    force: bool = arguments.force
    given_version: str | None = arguments.cdrdao_version
    if given_version is not None and not CDRDAO_VERSION.fullmatch(given_version):
        die(f"--cdrdao-version must look like 1.2.6, not {given_version!r}.")

    added: list[Path] = []
    unusable = 0
    if source is not None:
        installed = keep(source, force=force, version=given_version or "unknown")
        if installed is not None:
            added.append(installed)
    else:
        if given_version is not None:
            die("--cdrdao-version only applies to a TOC_FILE; a disc read here uses this cdrdao.")
        version = installed_cdrdao_version()
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            for number in disc_sessions(session):
                if disc_gone():
                    print(
                        "add-toc: the drive reports no disc, so nothing more can be read.",
                        file=sys.stderr,
                    )
                    unusable += 1
                    break
                new = work / f"session{number}.toc"
                if not read_session(new, number):
                    unusable += 1
                    continue
                if verify and not reread_agrees(work, number, new):
                    unusable += 1
                    continue
                installed = keep(new, force=force, version=version)
                if installed is not None:
                    added.append(installed)

    # tests/test_corpus.py requires cdrdao's own output back byte for byte, so
    # say now if a file does not manage it.
    for path in added:
        try:
            same = path.read_text() == dumps(parse_file(path))
        except TocError as error:
            print(f"add-toc: warning: {path.name} does not parse: {error}", file=sys.stderr)
            continue
        if not same:
            print(
                f"add-toc: warning: {path.name} does not round-trip byte for byte yet.",
                file=sys.stderr,
            )

    # Nothing added means every session read was already here.
    return 0 if added and not unusable else 1


if __name__ == "__main__":
    raise SystemExit(main())
