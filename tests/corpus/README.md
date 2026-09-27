# Corpus

Real TOC files produced by cdrdao, used to test the parser against output no
one wrote by hand.

**Nothing in here may be edited.** `tests/test_corpus.py` asserts that every
file serializes back byte for byte identically, so a hand-tweaked file fails
the suite. Files written to exercise a particular construct belong in
[`../fixtures/`](../fixtures/) instead.

Files are numbered rather than named after the disc they came from, and nothing
maps them back, so no filename here names an artist or a release. These are
cdrdao's bytes untouched, so the files carrying CD-TEXT do name them; that is
the coverage they are here for. To add one, run `just add-toc`, which reads
every session of the disc in the drive with cdrdao, skips any whose bytes are
already here, and installs the rest as the next numbers. A multi-session disc
lands as one file per session, because a TOC file describes one session.

Each session is read once, because that is all some drives will do. The read is
compared against what is here two ways: by its bytes, and by where the disc says
its tracks begin. The second catches a disc already here whose second reading
came back different, which happens when a read misses pregaps the disc has.
`--force` keeps it anyway.

`--verify` reads a session twice and keeps it only if the two reads agree, which
is the only way to know a read came back as good as the disc. It costs a second
read, and a drive that dislikes consecutive reads will make you pay for it.

`cdrdao-versions.csv` records which cdrdao version wrote each file, since
cdrdao's output has changed between versions and the files themselves do not
say. `just add-toc` fills it in: with the installed cdrdao's version for a disc
it reads, and with `--cdrdao-version` (default `unknown`) for a `.toc` file
written elsewhere. `tests/test_corpus.py` fails if a file is missing from it.
Files `00001.toc` to `00200.toc` were read in August 2026 with Homebrew's
cdrdao, installed just before as its latest version. Homebrew's formula history
shows that version was 1.2.6, which it had been since December 2025.

Test ids are rebuilt from each file's contents, so a failure still says what it
was working on:

```
FAILED test_corpus_file_round_trips[00027-cd_da-14t-cdtext]
```
