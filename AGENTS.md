# Instructions for coding agents

## Language

Write US English, every time, in everything you write for this project: code
comments, docstrings, error messages, identifiers, tests, documentation, commit
messages and replies. That means `-ize` and `-yze` (`normalize`, `analyze`),
`-or` (`behavior`, `honor`), `-er` (`center`), single `l` before a suffix
(`labeling`, `canceled`), `license` as both noun and verb, and `catalog`.

Optical media are "discs" in US English too, so write "CD" and "disc". "Disk"
stays correct for other storage, and in cdrdao names such as `disk-info`.

Leave other people's text as it is:

- cdrdao's own error messages, which tocparser reproduces word for word;
- CD-TEXT and other data in `tests/corpus/` and `tests/fixtures/`;
- `LICENSE.txt`.

## Type checking

Use strict mypy (`just type-check`). ty was evaluated (0.0.84) and not adopted: it
does not yet cover all the checks this project relies on.
