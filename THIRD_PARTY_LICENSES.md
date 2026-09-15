# Third-party assets

This project uses open-source Unicode fonts to render volunteers' native
language names -- and their own names/usernames, if entered in a non-Latin
script -- correctly on printed labels (`volunteers/labels.py`).

**These font files are not committed to the git repository.** They are
downloaded on demand from their upstream sources (either explicitly via
`python manage.py download_fonts`, or lazily the first time a label PDF is
generated) into `volunteers/static/fonts/` (gitignored), and verified
against a pinned SHA-256 checksum before use, so the exact bytes served are
always the ones referenced below. This keeps the repository small while
still allowing full Unicode script coverage.

Why this is needed: PDF generation (via ReportLab) only ships Latin-1-only
base fonts (Helvetica, Times, Courier) by default, so scripts like
Cyrillic, Arabic, Hindi, Chinese, Japanese, Korean, Thai etc. would
otherwise render as boxes or garbage.

The full manifest of fonts, their download URLs, and their pinned
checksums lives in `volunteers/fonts_manifest.py`.

## DejaVu Sans

- **Source:** https://dejavu-fonts.github.io/ (DejaVu Fonts project, version 2.37)
- **License:** Bitstream Vera License, with additional glyphs contributed
  under a compatible permissive license by Tavmjong Bah (Arev fonts). The
  full text is downloaded alongside the font (from the same release
  archive) as `volunteers/static/fonts/DejaVuSans-LICENSE.txt`; like the
  font binary, this file is gitignored and fetched on demand rather than
  committed.
- **Scripts covered:** Latin, Cyrillic, Greek, Armenian, Georgian, Hebrew,
  Arabic (isolated forms).

## Noto Sans / Noto Serif (Google Fonts)

- **Source:** https://github.com/google/fonts (the `ofl/` directory), and
  the upstream https://notofonts.github.io/ project.
- **License:** SIL Open Font License, Version 1.1. Each font family's own
  `OFL.txt` (including its specific copyright notice) is downloaded
  alongside it as `volunteers/static/fonts/OFL-<family>.txt` by the same
  download step that fetches the font.
- **Families and scripts covered:**
  - Noto Sans JP -- Japanese (Kanji, Hiragana, Katakana)
  - Noto Sans KR -- Korean (Hangul, Hanja)
  - Noto Sans SC -- Chinese (Simplified)
  - Noto Sans TC -- Chinese (Traditional)
  - Noto Sans Devanagari -- Hindi, Marathi, Sanskrit, Nepali, ...
  - Noto Sans Bengali -- Bengali, Assamese
  - Noto Sans Gujarati -- Gujarati
  - Noto Sans Gurmukhi -- Punjabi
  - Noto Sans Kannada -- Kannada
  - Noto Sans Malayalam -- Malayalam
  - Noto Sans Oriya -- Oriya
  - Noto Sans Tamil -- Tamil
  - Noto Sans Telugu -- Telugu
  - Noto Sans Sinhala -- Sinhala
  - Noto Sans Thai -- Thai
  - Noto Sans Khmer -- Khmer
  - Noto Serif Tibetan -- Tibetan (no Noto Sans variant exists upstream)
  - Noto Sans Ethiopic -- Amharic, Tigrinya, ...
  - Noto Sans Yi -- Yi (Nuosu)
  - Noto Sans Myanmar -- Burmese
  - Noto Sans Thaana -- Divehi/Dhivehi (Maldivian)

## License compatibility

Both the Bitstream Vera License and the SIL Open Font License are
permissive, royalty-free licenses that allow use, copying, modification and
redistribution of the fonts, without imposing copyleft obligations on the
surrounding project. Both are compatible with this project's AGPLv3
license. Per their terms, each font's license/attribution notice travels
alongside it wherever the font file itself is downloaded/distributed.
