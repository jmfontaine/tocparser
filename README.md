# tocparser

tocparser parses [cdrdao](https://cdrdao.sourceforge.net/)'s TOC files into
Pydantic models, and writes them back out.

- Parses every directive in cdrdao 1.2.6's own grammar, not just the documented
  ones, including the CD-TEXT `ENCODING_*` keywords added in cdrdao 1.2.5.
- Accepts what cdrdao accepts and rejects what cdrdao rejects, with the same
  error messages and line numbers. The few exceptions are listed under Limits
  below.
- Round-trips: `parse(dumps(toc)) == toc`, and the output is laid out the way
  cdrdao lays it out. The one value `dumps` cannot write is non-ASCII text
  holding a backslash followed by three digits, such as `café \123`; it raises
  instead.
- Fully type annotated, with only `lark` and `pydantic` as dependencies.

## Install

```console
uv add tocparser
```

Requires Python 3.10 or newer, including the Python 3.15 release candidates.
On 3.15 tocparser needs pydantic 2.14 or later, the first with Python 3.15
wheels, and asks for it itself: while 2.14 is in beta, that means its beta.

## Usage

```python
from tocparser import dump, dumps, parse, parse_file

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

dumps(toc)                       # -> str
dump(toc, "out.toc")
parse('CD_DA\nTRACK AUDIO\nFILE "hurt.wav" 0\n')
```

Models are ordinary Pydantic models, so `model_dump()`, `model_dump_json()`
and `Toc.model_validate_json()` all work and preserve the parsed values.

### Times

A position or a length is written either as `MM:SS:FF`, counting frames at 75
frames per second, or as a bare integer, which means samples on an audio track
and bytes on a data track. The two are not interchangeable — a sample count
that is not frame aligned has no `MM:SS:FF` form — so tocparser keeps whichever
form was written. Frame-based values become `Msf`, bare integers stay `int`.

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

CD-TEXT values are `str`, or `list[int]` for the binary packs. Each language
block is ISO-8859-1 unless the disc's `CD_TEXT` gives it an `ENCODING_*`;
track blocks follow the disc block with the same number, as they do in cdrdao.
`toc.cd_text_encoding(n)` returns the encoding in effect for block `n`.

Strings follow cdrdao's rules. Text with non-ASCII characters is UTF-8, and
must fit the block's encoding: `TITLE "日本"` needs `ENCODING_MS_JIS`, since
ISO-8859-1 has no Japanese. A string in plain ASCII may carry `\NNN` octal
escapes, which are bytes in the block's encoding, so `"caf\351"` reads as
`'café'` and, under `ENCODING_MS_JIS`, `"\223\372\226\173"` as `'日本'`.

cdrdao reads `UPC_EAN` and `ISRC` as the same pack, and `RESERVED4` and
`CLOSED` too. A block keeps whichever spelling was written last, and
`block.upc_ean` and `block.isrc` both find it.

### Errors

```python
from tocparser import TocParseError, TocValidationError, parse

parse(
    'CD_DA\nCATALOG "0602498647"\nTRACK AUDIO\nFILE "hurt.wav" 0\n',
    filename="the_downward_spiral.toc",
)
# TocValidationError: the_downward_spiral.toc:2: Illegal catalog number: 0602498647.
```

`TocParseError` covers syntax errors and `TocValidationError` covers input that
parses but breaks a rule cdrdao enforces. Both derive from `TocError` and carry
`line`, and `TocParseError` also carries `column`. `parse_file` also raises
`TocParseError` for bytes that do not decode as UTF-8, which is what cdrdao 1.2.5
and later write; pass `encoding=` for anything else.

The models enforce the same rules, so building one by hand that cdrdao would
reject raises `TocValidationError`, whose `loc` locates the problem inside that
model, e.g. `("statements", 2)`. A value cdrdao's syntax cannot express, such as
a value of the wrong type or a negative number, raises Pydantic's
`ValidationError` instead. Models can be changed after they are built, so
`dumps` validates its argument again before writing it.

## What is written back

Serializing is meaning-preserving rather than byte-exact, but in practice it is
usually both: every one of the real cdrdao files in `tests/corpus/` comes back
byte for byte identical. Differences are limited to the following.

- Hand-written comments are dropped. The two comments cdrdao generates itself,
  the `// Track N` headers and the `// length in bytes:` annotation on data
  lengths, are regenerated rather than preserved.
- `MM:SS:FF` values are zero-padded, so `0:10:0` becomes `00:10:00`. Bare
  integers are left alone.
- Only the last disc type flag is written, since cdrdao documents that the last
  one takes effect.
- A repeated CD-TEXT item collapses to the last one, and a repeated `LANGUAGE`
  block merges into the first, as cdrdao files them.
- Text is written as UTF-8, so `\NNN` escapes come back as the characters they
  stand for. A backslash followed by three digits is written `\134`, since
  cdrdao would read even an escaped one as an octal escape. cdrdao accepts no
  escape in non-ASCII text, so such text cannot hold that sequence and `dumps`
  raises.
- Flags that were not written are not invented: a track with no `COPY` line
  keeps `copy_permitted is None` and gets no `COPY` line back. The effective
  values are on `is_copy_permitted`, `has_pre_emphasis` and `channel_count`.

## Limits

cdrdao performs some checks that need the referenced media, which tocparser
does not read: the four second minimum track length, `INDEX` beyond the track
end, `START` and `END` behind the track end, `END` within the pre-gap, and a
requested length longer than the file. Nor does it run the CD-TEXT
completeness checks cdrdao only makes before writing a disc. Everything else
`cdrdao show-toc` 1.2.6 checks is checked, with these differences:

- A file with several errors raises one of them. It is not always the one cdrdao
  reports first.
- For two syntax errors, a `PREGAP` after the track's data and a
  `LANGUAGE_MAP` inside a track's `CD_TEXT`, cdrdao's parser stops at a
  different token than tocparser's.
- cdrdao reports a `FIFO` that mixes audio and data on line 0; tocparser gives
  the `FIFO`'s own line.
- `\NNN` bytes that are not text in their block's encoding, such as a lone
  CP932 lead byte, or a byte above 127 in an `ENCODING_ASCII` block, are
  rejected. cdrdao keeps them, warning at most, but could not read back the
  text it would write for them.
- cdrdao 1.2.6 ignores a CD-TEXT item whose string is empty. tocparser keeps it,
  so that it is written back, but like cdrdao does not hold it against a track.
- Escapes in file names decode like CD-TEXT, as ISO-8859-1, and are written
  back as UTF-8.

## TOC files from older cdrdao

tocparser reads TOC files the way cdrdao 1.2.6 does. Files written by cdrdao
1.2.2 to 1.2.4 mostly read the same, with two exceptions, both of which cdrdao
1.2.6 shares. They come from comparing cdrdao releases 1.2.2 to 1.2.6; releases
before 1.2.2 were not checked.

- cdrdao 1.2.2 to 1.2.4 wrote a backslash in a string as it was. Since 1.2.5 a
  backslash must start an escape, so `"AC\DC"` is rejected with
  `Illegal token: \`, and `"C:\\x"` now reads as `C:\x`, with one backslash
  rather than two. This applies to every string, file names included.
- cdrdao 1.2.2 to 1.2.4 wrote bytes above 127 as octal escapes, at least under
  the default C locale, and wrote no `ENCODING_*`, so that text reads as
  ISO-8859-1. Latin text comes through intact, but text in another encoding,
  such as Japanese, does not.

## Contributing

Contributions are welcome. See
[CONTRIBUTING.md](https://github.com/jmfontaine/tocparser/blob/main/CONTRIBUTING.md) for the
development setup, how the tests compare tocparser with cdrdao, and the pull request process.
