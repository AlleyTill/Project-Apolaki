# Third-party notices

## What in Apolaki is derived from Unicode data

Two tables in this repository are derived from Unicode, Inc.'s data, which is under the Unicode License v3 (its full
text is at the end of this file):

- **`apolaki/agent/erase.py`, `_SKELETON`: the 29 Cherokee entries.** These are the Cherokee letters that
  `confusables.txt` maps to a Latin letter, and U+13B1, which it maps to the Greek capital gamma. Each is keyed as the
  erase's fold leaves it (a Cherokee small letter case-folds to its capital). The source is
  [Unicode Technical Standard #39, Unicode Security Mechanisms](https://www.unicode.org/reports/tr39/), data file
  `confusables.txt`, version 18.0.0, dated 2026-08-06. Rounds A and A2 (commits 0a73e38, 2026-11-07, and 3c4e60f,
  2026-11-08) took them from it. On 2026-11-11 all 29 were checked again against a fresh copy of the file
  (https://www.unicode.org/Public/security/latest/confusables.txt, still 18.0.0, sha256
  `6ed3ee967c9dfdf6677d563c9985182fbc50a2efb7d6059cd57b2e2ce18f5b92`), and all 29 agree with it.
- **`tests/agent/test_erase_person.py`, `CHEROKEE_CONFUSABLES`.** This is the test's own copy of the same 29
  prototypes from the same file, so that a wrong entry in `_SKELETON` fails a test.

Listed here as well, to be safe:

- **`apolaki/agent/erase.py`, `_SKELETON`: the 24 small capitals.** Each is read as the letter its Unicode character
  name gives (LATIN LETTER SMALL CAPITAL G is read as g). The names come from the Unicode Character Database, read
  through Python's `unicodedata`, and not from `confusables.txt`, which maps small capital M to a turned w. That file
  agrees with the table for 9 of the 24.

## The other look-alike tables, and where they came from

- **`apolaki/security/normalize.py`: `_LOOKALIKE_PAIRS`, `_APOSTROPHES` and `_DOUBLE_QUOTES`.** These are 82 letter
  pairs (Cyrillic, Greek and Armenian letters that look Latin, and five Latin letters that stand in for others) and 40
  quote look-alikes. Commits fb19567 (2026-11-02) and 4d87cd0 (2026-11-03, the Armenian letters) wrote them. Neither
  those commits nor the code name a source, so **where they came from can't be shown.** They were compared with
  `confusables.txt` 18.0.0 on 2026-11-11:
  - Of the 82 letter pairs, 69 agree with it. Nine map a letter to something else: it maps Cyrillic small ve to small
    capital B where the table has b, and Greek beta to sharp s. Four aren't in it: Cyrillic Komi De, Greek small chi
    and omega, and small capital L.
  - Of the 40 quote marks, 29 agree with it, 3 map to something else (the low-9 and single angle quotation marks) and
    8 aren't in it.

  So the tables aren't a copy of that file. Whether any part of them was written from it can't be shown either way.
- **What is built at run time.** These come from the copy of the Unicode Character Database inside the Python that
  runs Apolaki: the erase's separator class (`_sep`), its classes of format characters and combining marks
  (`_byte_fold_strip`) and its noise class (`_noise`), and normalize()'s compatibility decomposition and category
  tests. No file in this repository holds any of it.
- **The code-point ranges written in `erase.py`** (`_NO_SPACE`, the scripts written without spaces, and `_ARABIC`) are
  ranges of Unicode blocks. No source is recorded for them. They aren't look-alike tables.

## Vendored code

- `apolaki/security/garuda/`: Layer 1 of Liberation Labs' Project-Garuda, with its licence beside it
  (`apolaki/security/garuda/LICENSE.md`).
- `apolaki/kintsugi_vendor/`: modules of Liberation Labs' Project-Kintsugi. `apolaki/kintsugi_vendor/README.md` names
  the commit they were copied from and their licence.

## Unicode License v3

This text was fetched from https://www.unicode.org/license.txt on 2026-11-11 at 10:39:56 UTC. The server gave its
Last-Modified date as Mon, 05 Jan 2026 15:17:23 GMT. Between the fences below is that file exactly, byte for byte:
1,995 bytes of UTF-8, ending with a newline, sha256
`e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96`. `tests/test_third_party_notices.py` checks that hash.

```text
UNICODE LICENSE V3

COPYRIGHT AND PERMISSION NOTICE

Copyright © 1991-2026 Unicode, Inc.

NOTICE TO USER: Carefully read the following legal agreement. BY
DOWNLOADING, INSTALLING, COPYING OR OTHERWISE USING DATA FILES, AND/OR
SOFTWARE, YOU UNEQUIVOCALLY ACCEPT, AND AGREE TO BE BOUND BY, ALL OF THE
TERMS AND CONDITIONS OF THIS AGREEMENT. IF YOU DO NOT AGREE, DO NOT
DOWNLOAD, INSTALL, COPY, DISTRIBUTE OR USE THE DATA FILES OR SOFTWARE.

Permission is hereby granted, free of charge, to any person obtaining a
copy of data files and any associated documentation (the "Data Files") or
software and any associated documentation (the "Software") to deal in the
Data Files or Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, and/or sell
copies of the Data Files or Software, and to permit persons to whom the
Data Files or Software are furnished to do so, provided that either (a)
this copyright and permission notice appear with all copies of the Data
Files or Software, or (b) this copyright and permission notice appear in
associated Documentation.

THE DATA FILES AND SOFTWARE ARE PROVIDED "AS IS", WITHOUT WARRANTY OF ANY
KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT OF
THIRD PARTY RIGHTS.

IN NO EVENT SHALL THE COPYRIGHT HOLDER OR HOLDERS INCLUDED IN THIS NOTICE
BE LIABLE FOR ANY CLAIM, OR ANY SPECIAL INDIRECT OR CONSEQUENTIAL DAMAGES,
OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THE DATA
FILES OR SOFTWARE.

Except as contained in this notice, the name of a copyright holder shall
not be used in advertising or otherwise to promote the sale, use or other
dealings in these Data Files or Software without prior written
authorization of the copyright holder.
```
