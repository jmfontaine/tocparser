# tocparser

tocparser parses cdrdao's TOC files into Pydantic models and writes them back out.

- It supports the full TOC format. Older files mostly parse the same, with two
  exceptions described below.
- It validates files like cdrdao, matching its error messages and line numbers. See
  Limits for exceptions.
- Writing preserves every value. Unedited files usually serialize byte for byte
  identically, though hand-written comments are dropped and some formatting is
  normalized. See What is written back for details.
- It is fully typed and depends only on `lark` and `pydantic`.

## Install

```
uv add tocparser
```

Requires Python 3.10 or newer.

## Usage

```python
from tocparser import dump, parse_file

toc = parse_file("the_downward_spiral.toc")

toc.disc_type                    # <DiscType.CD_DA: 'CD_DA'>
toc.catalog                      # '0602498647295'
toc.cd_text[0].title             # 'The Downward Spiral - Deluxe Edition [ Disc 1 ] '
toc.cd_text[0].performer         # 'Nine Inch Nails'

track = toc.tracks[4]
track.mode                       # <TrackMode.AUDIO: 'AUDIO'>
track.isrc                       # 'USIR19400529'
track.cd_text[0].title           # 'Closer'
track.content[0].start           # Msf(minutes=15, seconds=47, frames=32)
track.content[0].length          # Msf(minutes=6, seconds=13, frames=23)

# "The Becoming" starts with a 00:02:30 pre-gap: 2 seconds and 30 frames.
toc.tracks[6].start              # Start(kind='start', position=Msf(minutes=0, seconds=2, frames=30))
```

Models are ordinary Pydantic models, so `model_dump()`, `model_dump_json()` and
`Toc.model_validate_json()` all work and preserve the parsed values.

### Times

A position or length can be written as `MM:SS:FF`, where frames are counted at 75 per
second, or as a bare integer representing samples on an audio track and bytes on a data
track. These formats are not interchangeable. If a sample count is not frame-aligned, it
has no `MM:SS:FF` equivalent, so tocparser preserves the format in which it was written.
Frame-based values become `Msf`, while bare integers remain `int`.

```python
from tocparser import Msf

position = Msf(15, 47, 32)       # where "Closer" starts
position.total_frames            # 71057
position.to_samples()            # 41781516
position.to_bytes(2352)          # 167126064
str(position)                    # '15:47:32'
Msf.from_frames(71057)           # Msf(minutes=15, seconds=47, frames=32)
```

`Msf` is ordered and hashable, so positions sort and can be used as keys.

### CD-TEXT

CD-TEXT values are `str`, or `list[int]` for binary packs. Each language block uses
ISO-8859-1 unless the disc's `CD_TEXT` specifies an `ENCODING_*` value. Track blocks
follow the disc block with the same number, as they do in cdrdao.
`toc.cd_text_encoding(n)` returns the encoding used for block `n`.

Strings follow cdrdao's rules. Non-ASCII text is UTF-8 and must fit the block's
encoding: `TITLE "日本"` requires `ENCODING_MS_JIS`, because ISO-8859-1 cannot represent
Japanese. Plain ASCII strings may contain `\NNN` octal escapes, which represent bytes in
the block's encoding. For example, `"caf\351"` decodes to `'café'`, and under
`ENCODING_MS_JIS`, `"\223\372\226\173"` decodes to `'日本'`.

cdrdao treats `UPC_EAN` and `ISRC` as the same pack, as well as `RESERVED4` and
`CLOSED`. A block retains the spelling written last, and `block.upc_ean` and
`block.isrc` both access it.

### Errors

```python
from tocparser import TocParseError, TocValidationError, parse

parse(
    'CD_DA\nCATALOG "0602498647"\nTRACK AUDIO\nFILE "hurt.wav" 0\n',
    filename="the_downward_spiral.toc",
)
# TocValidationError: the_downward_spiral.toc:2: Illegal catalog number: 0602498647.
```

`TocParseError` covers syntax errors and `TocValidationError` covers input that parses
but breaks a rule cdrdao enforces. Both derive from `TocError` and carry `line`, and
`TocParseError` also carries `column`. `parse_file` reads files as UTF-8 and raises
`TocParseError` for bytes that do not decode; pass `encoding=` for other encodings.

The models enforce the same rules, so building one by hand that cdrdao would reject
raises `TocValidationError`, whose `loc` locates the problem inside that model, e.g.
`("statements", 2)`. A value cdrdao's syntax cannot express, such as a value of the
wrong type or a negative number, raises Pydantic's `ValidationError` instead. Models can
be changed after they are built, so `dumps` validates its argument again before writing
it.

## What is written back

Serializing preserves meaning, though not always the exact bytes. In practice, the
output is usually byte-for-byte identical. Differences are limited to the following:

- Hand-written comments are dropped. cdrdao-generated comments—the `// Track N` headers
  and the `// length in bytes:` annotations on data lengths—are regenerated.
- `MM:SS:FF` values are zero-padded: `0:10:0` becomes `00:10:00`. Bare integers remain
  unchanged.
- When a CD-TEXT item appears more than once, only its last instance is written. An
  empty string does not replace an earlier value because cdrdao drops it. Repeated
  LANGUAGE blocks are merged into the first, as in cdrdao's output.
- Text is written as UTF-8, so `\NNN` escapes are replaced by the characters they
  represent. A backslash followed by three digits is written as `\134`, because cdrdao
  would interpret even an escaped backslash as an octal escape. cdrdao does not accept
  escapes in non-ASCII text, so such text cannot contain that sequence; `dumps` raises
  an error if it does.
- Unwritten flags are not added. A track without a `COPY` line keeps
  `copy_permitted is None` and has no `COPY` line in the output. The effective values
  are available through `is_copy_permitted`, `has_pre_emphasis`, and `channel_count`.

## Limits

tocparser follows cdrdao 1.2.6, but some checks require the audio and data files
referenced by a TOC file. Because tocparser reads only the TOC file, it cannot check the
four-second minimum track length, an `INDEX` beyond the track end, `START` or `END` past
the track end, an `END` within the pre-gap, or a requested length that exceeds the file.
It also skips the CD-TEXT completeness checks that cdrdao performs only before writing a
disc. tocparser checks everything else that `cdrdao show-toc` checks, with these
differences:

- If a file contains several errors, tocparser raises one, but not necessarily the one
  cdrdao reports first.
- For two syntax errors—a `PREGAP` after track data and a `LANGUAGE_MAP` inside a
  track's `CD_TEXT`—cdrdao's parser stops at a different token than tocparser does.
- cdrdao reports a `FIFO` that mixes audio and data on line 0; tocparser reports the
  `FIFO`'s own line.
- tocparser rejects `\NNN` bytes that are not text in their block's encoding—for
  example, a lone CP932 lead byte or a byte above 127 in an `ENCODING_ASCII` block.
  cdrdao keeps these bytes, at most issuing a warning, but could not read back the text
  it would write for them.
- cdrdao drops CD-TEXT items with empty strings. tocparser preserves an empty item when
  no other value is provided and writes it back. Like cdrdao, it also allows a track to
  contain an empty item that is valid only at the disc level.
- Escapes in file names are decoded like CD-TEXT (as ISO-8859-1) and written back as
  UTF-8.

## TOC files from older cdrdao

Files written by cdrdao 1.2.2 through 1.2.4 are mostly read the same way, with two
exceptions that also apply to later releases. Releases before 1.2.2 were not checked.

- cdrdao 1.2.2 through 1.2.4 wrote backslashes in strings unchanged. Since 1.2.5, a
  backslash must begin an escape, so `"AC\DC"` is rejected with `Illegal token: \`, and
  `"C:\\x"` now reads as `C:\x`, with one backslash rather than two. This applies to all
  strings, including file names.
- cdrdao 1.2.2 through 1.2.4 wrote bytes above 127 as octal escapes, at least under the
  default C locale, and omitted `ENCODING_*`, so the text is read as ISO-8859-1. Latin
  text remains intact, but text in another encoding, such as Japanese, does not.

## Contributing

Contributions are welcome. See CONTRIBUTING.md for development setup, test comparisons
between tocparser and cdrdao, and the pull request process.

## License

tocparser is licensed under the Apache License 2.0.
