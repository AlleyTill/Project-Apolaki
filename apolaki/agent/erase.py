"""Erase a person from Apolaki's memory, everywhere it lives (2026-11-02 review, item 14 and adoption 9).

    python -m apolaki.engine erase-person "NAME" [--alias "OTHER NAME" ...]
        a dry run: lists everything it would remove, every near-match it would keep, and gives a code
    python -m apolaki.engine erase-person "NAME" [--alias ...] --confirm CODE --by WHO --reason WHY \\
        [--not-them WORD ...]
        removes exactly what that dry run listed

Apolaki's memory keeps things by design: archive_memory() hides a memory but keeps its row and its embedding, and
store() pulls the names of people and organisations into an entity graph and wiki pages that archiving never
touches. That is right for Apolaki's own beliefs and wrong for personal data about third parties. This is the one
path that deletes. It is a command a person runs; the MCP server has no erase tool.

What counts as the name, for the name and each alias:
  - case, accents, look-alike letters, curly quotes and invisible characters are folded (apolaki.security.normalize),
    so "María López" also finds "MARIA LOPEZ";
  - the parts of a name are the pieces between spaces, hyphens and dashes, apostrophes, full stops, underscores and
    markup characters (* [ ] ( ) { } < > / \\ | # ~ ^ = +), and in the text any run of those, or nothing, may stand
    between two parts: "Jean-Luc Moreau" finds "Jean Luc Moreau", "Jean–Luc Moreau" (an en dash), "JeanLuc Moreau",
    "jean_luc_moreau" (a wiki file name) and "jean.luc.moreau"; "O'Brien" finds "OBrien" and "O Brien"; "Marisol
    Quintero" finds "**Marisol** Quintero" and "Marisol/Quintero";
  - a match must not touch a letter or a digit of a script written with spaces before it, nor such a letter after it.
    A digit after the name is still the name ("marisol.quintero85@...", "@MarisolQuintero1990"). A character of a
    script written without spaces (Chinese, Japanese, Thai, Lao, Khmer, Myanmar, Tibetan, Yi) or of Korean, whose
    particles attach to a name, is a separator ("Marisol Quintero" + a Japanese honorific), and a name written in one
    of those scripts keeps no word edge at all, since a mention inside a sentence touches letters on both sides. An
    Arabic name may carry an attached prefix (wa, fa, bi, li, ka, al, and their combinations: "with Muhammad");
  - text is read as stored, with its escapes decoded (\\u00f3, \\U..., \\x.., \\n and the like, any number of
    backslashes deep, since store() writes tags with json.dumps, which escapes every non-ASCII letter), and with its
    markup taken out: a Markdown link or image ("[Marisol](url) Quintero"), an HTML tag, an HTML entity
    ("Mar&iacute;a") and percent-encoding.
A near-match is the name inside a longer word: what the pattern finds without the word edges that it doesn't find
with them ("Marisol Quinterova", "xMarisol Quintero"). It may be another person, or her. The dry run lists every
near-match in what the erase keeps (any column of any kept row, the schema, kept wiki pages, kept beliefs, what the
belief log's redaction leaves), and the erase refuses until a person rules on each word: someone else (--not-them
WORD, which names it exactly as the dry run prints it), or the person (give it as an --alias and dry-run again, and it
is erased). The ledger records each ruled near-match by where it is, with the ruling, never by the word, which holds
the name.

What it removes:
  - every memory with a column that names the person (text, tags, source, archive_reason, any column), archived ones
    included, each with its embedding (the row's blob and its vector-index entry). A blob counts as text unless it
    reads as an embedding's float numbers (all under 128; text in another encoding doesn't), so a name in a blob of
    Latin-1 text is found; and every blob is read as UTF-16 and UTF-32 as well, in either byte order, with a byte-order
    mark or without (round 4), so a name stored in one of those is found too, and so is every text cell that holds a
    NUL or another control character, which is how such text in a TEXT cell reads back (round 5), and that text with
    its NULs taken out. The vector indexes' chunks are the one exception: they hold copies of the rows' embeddings, and
    the erase drops and refills them from the rows;
  - the person's entity rows (an entity whose name contains the person's, such as "Dr. María López", counts), every
    mention row and triple that names them or touches them or an erased memory, and every other entity left with no
    memory behind it, since it came only from what was erased;
  - the person's wiki page, file and row; every other page that names them, or belongs to an erased entity, is
    rebuilt from what remains or removed when nothing remains to rebuild it from;
  - the engine's beliefs that name the person, logged as removed without the name; and the person's name in the
    engine's belief log, replaced by "[erased]" wherever it is in a line (in lists and nested values too).
The dry run reads every text column of every table in the database, and the schema (table, view, trigger and index
names and definitions, column defaults included). A name in a table or column the erase doesn't remove from (a table
added by hand, say), or in the schema, is listed, and the erase refuses before changing anything until a person has
dealt with it. So is a TEXT cell whose bytes aren't valid UTF-8 (written with CAST(... AS TEXT), or by a program
writing another encoding), whether or not it seems to name the person, since what it says can't be read with
certainty: the dry run lists it, and the erase refuses (EraseUnreadable, exit code 4) until a person rewrites or
removes it. Before round A such a cell stopped the dry run with a Python error.
Then it rebuilds the vector indexes from what remains, VACUUMs the database (with secure_delete on, so the deleted rows
are zeroed even if VACUUM can't run) and truncates its write-ahead log. Its check reads every text column of every
table again; reads back every byte of the database files (folding case, accents, look-alike letters and invisible
characters, decoding escapes, and looking for the erased embeddings), with no word edges, since the bytes around a
column value are anything, and accepts a match there only where a near-match a person ruled someone else stands in a
kept row, or by chance inside a kept vector; reads the wiki folder and the engine's belief files; and runs the dry run
again, which must find nothing to remove or refuse on and no near-match nobody ruled on. If the name or an erased
embedding is still there, or VACUUM or the log truncation failed, that is an error (EraseIncomplete), never a success.

The dry run gives a code, a hash of exactly what it found, near-matches included. The erase runs only with that code,
so what is removed is what a person read; if anything changed in between, the code doesn't match and nothing is
removed. Each erase is recorded in $APOLAKI_HOME/erasures.jsonl: who, why, when, how much, and each near-match ruled
someone else (where it is), never the name.

What it can't do:
  - find the person by anything but the name and aliases given. A nickname, initials, a pronoun, a role ("our board
    chair"), a misspelling or the parts in another order ("Quintero, Marisol") isn't found; list such variants as
    aliases, and read what each finds in the dry run. The byte check of the database files doesn't take markup out,
    nor read UTF-16 or UTF-32 (the rows are read with markup taken out, and in both: every blob, and every text cell
    with a control character in it; a text cell of wide text that has none is not: UTF-16 of a single-word Devanagari,
    Gurmukhi or Malayalam name, whose high bytes are tab, line feed or carriage return, which the hint ignores; or
    UTF-16 of a Chinese name alone, whose bytes happen to be valid UTF-8. See docs/KNOWN_LIMITS.md section 5).
  - erase by a name shorter than three letters (a two-character Chinese name included): it would match inside too much.
  - keep the rest of a memory. A memory that names the person goes whole, with whatever else it said; the dry run
    shows each one, so a person can store again what should stay, without the name.
  - reach records that aren't memory. Approval-queue items, grant drafts, the grant hunt's files, the quarantine,
    logs and backups can hold the name too: the dry run lists every other file under $APOLAKI_HOME the name (or a
    near-match) is in, for a person to deal with, and leaves them alone. Copies outside $APOLAKI_HOME are beyond it.
  - run beside a live Apolaki. VACUUM needs the database to itself: stop the scheduled jobs and the MCP server
    first (docs/STOPPING.md).
  - settle a licence question. Apolaki's licence carries the SAFE-AI module, whose memory-sovereignty clause says
    no external system may delete a persistent agent's memories without its consent. This path exists for a third
    party's request to be forgotten; whether Apolaki counts as a persistent agent there, and how its consent would be
    sought, is for a person to decide (docs/DATA_LIFECYCLE.md).
"""
from __future__ import annotations

import array
import functools
import hashlib
import html
import json
import re
import sqlite3
import types
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import config
from ..security.normalize import _LOOKALIKES, _QUOTES, _TAG_ASCII, normalize   # the same tables, for _fold_bytes

MIN_NAME_CHARS = 3
REDACTED = "[erased]"
# How long a statement waits for another connection's lock before it fails. The erase needs the database to itself
# (docs/STOPPING.md), so this only bounds the wait when something else still holds it; then the erase refuses, or
# reports itself incomplete, instead of hanging.
BUSY_TIMEOUT_S = 30


class EraseError(RuntimeError):
    """The erase was refused (nothing removed), or its check found something left (said where)."""


class EraseIncomplete(EraseError):
    """The erase ran, but its check found the name or an erased embedding still there, or a step that clears deleted
    bytes (VACUUM, the log truncation) failed. Recorded in the ledger as not verified."""


class EraseUnreadable(EraseError):
    """The erase was refused (nothing removed) because a text cell's bytes aren't valid UTF-8, so the name in it can't
    be read with certainty. The command line exits 4 for this, apart from other refusals (2)."""


class _Undecodable(str):
    """A TEXT cell whose bytes aren't valid UTF-8 (written with CAST(... AS TEXT), or by a program writing another
    encoding), read with each bad byte as U+FFFD, so the code that reads text can still read it; raw is the bytes as
    stored."""
    raw = b""


def _text_cell(raw: bytes) -> str:
    """The text factory of every connection the erase opens. sqlite3's own stops the whole read with an error at the
    first TEXT cell that isn't valid UTF-8 (a Python traceback, exit 1, before round A); this reads that cell as an
    _Undecodable instead, which the dry run lists and the erase refuses on."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        cell = _Undecodable(raw.decode("utf-8", errors="replace"))
        cell.raw = raw
        return cell


def _connect(db: Path, readonly: bool):
    con = sqlite3.connect(str(db), timeout=BUSY_TIMEOUT_S)
    con.text_factory = _text_cell
    if readonly:
        con.execute("PRAGMA query_only = 1")
    return con


# Escapes, any number of backslashes deep (json.dumps of json.dumps doubles them): \uXXXX (surrogate pairs joined),
# \UXXXXXXXX, \xXX, and the one-letter ones. Only what the matcher reads is decoded; nothing stored is changed.
_ESCAPED = re.compile(r"\\+(?:u([0-9a-fA-F]{4})|U([0-9a-fA-F]{8})|x([0-9a-fA-F]{2})|([\"'/bfnrt]))")
_ONE_LETTER = {'"': '"', "'": "'", "/": "/", "b": " ", "f": " ", "n": "\n", "r": "\n", "t": "\t"}
_SURROGATE = re.compile("[\ud800-\udfff]")


def _unescape(text: str) -> str:
    if "\\" not in text:
        return text

    def one(m):
        u, big, x, letter = m.groups()
        if letter:
            return _ONE_LETTER[letter]
        cp = int(u or big or x, 16)
        return chr(cp) if cp <= 0x10FFFF else m.group()
    out = _ESCAPED.sub(one, text)
    if _SURROGATE.search(out):          # "\ud83d\ude00" decodes to two halves: join them, a lone half becomes U+FFFD
        out = out.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return out


# Markup a reader doesn't see, for the form of a text with it taken out: a Markdown link or image ("[Marisol](url)"
# reads "Marisol"), a reference link ("[Marisol][1]"), an HTML tag, an HTML entity ("Mar&iacute;a") and
# percent-encoding ("Mar%C3%ADa").
_MD_LINK = re.compile(r"!?\[([^\]\n]{0,300})\](?:\([^)\n]{0,1000}\)|\[[^\]\n]{0,100}\])")
_TAG = re.compile(r"<[^<>\n]{0,1000}>")
_MARKUP = re.compile(r"\]\(|\]\[|<[^<>\n]{0,1000}>|&#?\w{1,32};|%[0-9a-fA-F]{2}")


def _demarked(text: str) -> tuple[str, ...]:
    """The text with its markup taken out, a tag taken as nothing ("Mari<b>sol</b>") and as a space ("Marisol<br>
    Quintero"); () when it has none."""
    if not _MARKUP.search(text):
        return ()
    t = _MD_LINK.sub(lambda m: m.group(1), text)
    t = urllib.parse.unquote(html.unescape(t)) if ("&" in t or "%" in t) else t
    return (_TAG.sub("", t), _TAG.sub(" ", t))


def _variants(text: str) -> tuple[str, ...]:
    """The text as stored, with its escapes decoded, and with its markup taken out (_demarked), each when it differs.
    All are read: decoding can also hide a match ("C:\\nicolas" would lose its n), so the stored form is never
    dropped."""
    out = [text]
    decoded = _unescape(text)
    for t in (decoded, *_demarked(text), *(_demarked(decoded) if decoded != text else ())):
        if t not in out:
            out.append(t)
    return tuple(out)


def _fold(text: str) -> str:
    """Text as the matcher reads it: apolaki.security.normalize, then case folded. For ASCII text normalize() changes
    only quote marks, so that is all this does there (the same result, without its per-character Python loops)."""
    text = text or ""
    folded = text.translate(_QUOTES) if text.isascii() else normalize(text)
    return " ".join(folded.casefold().split())


# For the byte-level check of the database files, whose float vectors decode to megabytes of non-ASCII noise:
# normalize() runs at about 3 s a million characters there, so the bytes get the same fold done in C instead (regular
# expressions and unicodedata): tag characters, every format character (Unicode category Cf) and the Hangul fillers
# out, quotes straight, compatibility decomposition, every combining mark (Mn, Me) out, look-alike letters folded,
# composition, case folded. The classes are built from unicodedata on first use (about a second), since only an erase
# needs them.
def _class_of(codes: list[int]) -> re.Pattern:
    runs: list[list[int]] = []
    for c in sorted(codes):
        if runs and c == runs[-1][1] + 1:
            runs[-1][1] = c
        else:
            runs.append([c, c])
    return re.compile("[" + "".join(re.escape(chr(x)) + (f"-{re.escape(chr(y))}" if y > x else "")
                                    for x, y in runs) + "]")


_ASTRAL = re.compile("[\U00010000-\U0010ffff]")


@functools.lru_cache(maxsize=1)
def _byte_fold_strip():
    """(invisible, marks, astral): character classes of the format characters (Cf) and Hangul fillers, and of the
    combining marks (Mn, Me), each within the Basic Multilingual Plane, where a class is a bitmap the regex engine
    tests in one step; and a function that drops the ones past it (a class of ranges there is tested range by range,
    which took 40 s on a vector index's chunks), found by one range and looked up only where one stands."""
    codes = [*range(0x20000), *range(0xE0000, 0xE1000)]
    cats = list(map(unicodedata.category, map(chr, codes)))
    invisible = [c for c, k in zip(codes, cats) if k == "Cf"] + [0x115F, 0x1160, 0x3164, 0xFFA0]
    marks = [c for c, k in zip(codes, cats) if k in ("Mn", "Me")]
    far = frozenset(chr(c) for c in invisible + marks if c > 0xFFFF)
    return (_class_of([c for c in invisible if c <= 0xFFFF]), _class_of([c for c in marks if c <= 0xFFFF]),
            lambda text: _ASTRAL.sub(lambda m: "" if m.group() in far else m.group(), text))


def _swap(table: dict):
    """str.translate(table) as a regex substitution: translate looks every character up, which on megabytes of
    non-ASCII noise took 25 s in a test; the regex scans in C and calls back only on the characters in the table."""
    to = {chr(k): (chr(v) if isinstance(v, int) else v or "") for k, v in table.items()}
    runs, codes = [], sorted(table)                 # as ranges: a class of 95 single astral characters scans slowly
    for c in codes:
        if runs and c == runs[-1][1] + 1:
            runs[-1][1] = c
        else:
            runs.append([c, c])
    pattern = re.compile("[" + "".join(re.escape(chr(a)) + (f"-{re.escape(chr(b))}" if b > a else "")
                                       for a, b in runs) + "]")
    return lambda text: pattern.sub(lambda m: to[m.group()], text)


_untag, _straighten, _unlook = _swap(_TAG_ASCII), _swap(_QUOTES), _swap(_LOOKALIKES)


def _fold_fast(text: str) -> str:
    invisible, marks, far = _byte_fold_strip()
    t = _straighten(invisible.sub("", _untag(text)))
    t = _unlook(far(marks.sub("", unicodedata.normalize("NFKD", t))))
    return _straighten(unicodedata.normalize("NFC", t)).casefold()


def _fold_bytes(raw: bytes) -> str:
    return _fold_fast(raw.decode("utf-8", errors="ignore"))


# A match that only escape decoding reveals contains a decoded escape, so it lies within this many characters of one.
_ESCAPE_WINDOW = 512


def _byte_texts(raw: bytes) -> list[str]:
    """Bytes as the byte check reads them, fast-folded: the whole as stored, then each stretch around an escape
    sequence with its escapes decoded (the stretches, not the whole: a database's float vectors hold a backslash every
    few hundred bytes, and folding megabytes twice doubled the check's time)."""
    text = raw.decode("utf-8", errors="ignore")
    out = [_fold_fast(text)]
    spans: list[list[int]] = []
    for m in _ESCAPED.finditer(text):
        a, b = max(0, m.start() - _ESCAPE_WINDOW), m.end() + _ESCAPE_WINDOW
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    return out + [_fold_fast(_unescape(text[a:b])) for a, b in spans]


# Between two parts of a name: any run of spaces, hyphens and dashes, apostrophes, full stops, underscores and markup
# characters (* [ ] ( ) { } < > / \ | # ~ ^ = +), or none.
# \u2010-\u2015 are the Unicode hyphens and dashes; \u2212 is the minus sign.
_SEP = r"[\s\-\u2010-\u2015\u2212'._*\[\](){}<>/\\|#~^=+]"
_SPLIT = re.compile(_SEP + "+")
# Scripts written without spaces between words (Chinese, Japanese, Thai, Lao, Khmer, Myanmar, Tibetan, Yi), and
# Korean, whose particles and honorifics attach to a name: a name written in one has no word edge to keep, and a
# character of one next to a name in another script is a separator ("Quintero\u3055\u3093").
_NO_SPACE = ("\u0e00-\u0eff\u0f00-\u0fff\u1000-\u109f\u1780-\u17ff\u19e0-\u19ff"   # Thai, Lao, Tibetan, Myanmar, Khmer
             "\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff"                 # Hangul
             "\u2e80-\u2fdf\u3005-\u3007\u3021-\u3029\u3031-\u3035\u303b\u303c"     # CJK radicals, marks, numbers
             "\u3040-\u30ff\u31f0-\u31ff\u3100-\u312f\u31a0-\u31bf"                 # kana, Bopomofo
             "\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ua000-\ua4cf"                 # ideographs, Yi
             "\U00020000-\U0003134f")                                              # ideographs, extensions B-G
_NO_SPACE_CHAR = re.compile(f"[{_NO_SPACE}]")
# A letter or digit that ends a word: one of a script written with spaces. A digit after the name doesn't ("Quintero85",
# "@MarisolQuintero1990" are her handles).
_LETTER = rf"(?![{_NO_SPACE}])[^\W_]"
_EDGE_BEFORE, _EDGE_AFTER = rf"(?<!{_LETTER})", rf"(?!(?!\d){_LETTER})"
# Arabic writes a conjunction (wa, fa), a preposition (bi, li, ka) and the article (al) joined to the next word:
# "\u0628\u0645\u062d\u0645\u062f" is "with Muhammad". Each such prefix may stand before an Arabic name.
_ARABIC = re.compile("[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]")
_ARABIC_PREFIXES = sorted({c + p + a for c in ("", "\u0648", "\u0641") for p in ("", "\u0628", "\u0644", "\u0643")
                           for a in ("", "\u0627\u0644")} | {c + "\u0644\u0644" for c in ("", "\u0648", "\u0641")}
                          - {""}, key=lambda x: (len(x), x))


def _matcher(names: list[str], edges: bool = True) -> re.Pattern:
    """The names as one pattern over folded text (see the module docstring). edges=False drops the word edges: what it
    finds that the pattern with edges doesn't is a near-match, the name inside a longer word."""
    alts = []
    for n in names:
        parts = [p for p in _SPLIT.split(_fold(n)) if p]
        if not parts or len("".join(parts)) < MIN_NAME_CHARS:
            raise EraseError(f"{n!r} is too short to erase by: give a name of at least {MIN_NAME_CHARS} letters")
        body = (_SEP + "*").join(re.escape(p) for p in parts)
        if edges:
            first, last = parts[0][0], parts[-1][-1]
            before = "" if _NO_SPACE_CHAR.match(first) else _EDGE_BEFORE
            if _ARABIC.match(first):
                before = "(?:" + "|".join([_EDGE_BEFORE] + [f"(?<=(?<!{_LETTER}){re.escape(x)})"
                                                            for x in _ARABIC_PREFIXES]) + ")"
            body = before + body + ("" if _NO_SPACE_CHAR.match(last) else _EDGE_AFTER)
        alts.append(body)
    return re.compile("(?:" + "|".join(alts) + ")")


_WORD_CHAR = re.compile(r"[^\W_]")


def _word_around(text: str, start: int, end: int) -> tuple[str, int]:
    """The run of letters and digits around text[start:end], and where text[start:end] starts in it."""
    a, b = start, end
    while a > 0 and _WORD_CHAR.match(text[a - 1]):
        a -= 1
    while b < len(text) and _WORD_CHAR.match(text[b]):
        b += 1
    return text[a:b], start - a


def _near_in(hit: re.Pattern, loose: re.Pattern, folded: str) -> list[str]:
    """The near-matches in a folded text: each word a match without edges stands in where no match with edges starts."""
    return [_word_around(folded, m.start(), m.end())[0] for m in loose.finditer(folded)
            if not hit.match(folded, m.start())]


def _near_words(hit: re.Pattern, loose: re.Pattern, *texts, fold=_fold) -> list[str]:
    """The near-matches in any of the texts, read as stored, with escapes decoded and with markup taken out."""
    out: list[str] = []
    for t in texts:
        if isinstance(t, str) and t:
            for v in _variants(t):
                out += [w for w in _near_in(hit, loose, fold(v)) if w not in out]
    return out


def _names_in(hit: re.Pattern, *texts, fold=_fold) -> bool:
    """Whether any of the texts names the person, read as stored and with escapes decoded."""
    return any(hit.search(fold(v)) for t in texts if isinstance(t, str) and t for v in _variants(t))


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _tables(con) -> list[tuple[str, list[str]]]:
    """Every ordinary table and its columns. A virtual table (the vec0 indexes) is read through its shadow tables,
    which are ordinary ones."""
    out = []
    for name, sql in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table' ORDER BY name").fetchall():
        if (sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
            continue
        out.append((name, [r[1] for r in con.execute(f"PRAGMA table_info({_q(name)})")]))
    return out


def _rows(con, table: str):
    """(key, {column: value}) for every row: the key is the row's id column when it has one, else its rowid."""
    try:
        cur = con.execute(f"SELECT rowid AS erase_rowid_, * FROM {_q(table)}")
    except sqlite3.OperationalError:                     # a WITHOUT ROWID table
        cur = con.execute(f"SELECT * FROM {_q(table)}")
    names = [d[0] for d in cur.description]
    for row in cur:
        rec = dict(zip(names, row))
        yield rec.get("id", rec.get("erase_rowid_")), rec


# What an embedding's numbers can be: store() writes normalised vectors (each component under 1), and the vector indexes
# hold the same floats. A blob counts as numbers when, read as little-endian float32, no float in it reaches 128 or is
# infinite or not a number: a float's top byte holds its sign and most of its exponent, and that byte must be at most
# 0x42 once the sign is masked off. Text in another encoding isn't one: a lower-case letter, or a capital from C on, in
# a float's top byte makes it 128 or more, and natural text puts letters in a quarter of those bytes.
_TOP_BYTE_LIMIT = 0x42
_UNSIGNED = bytes(b & 0x7F for b in range(256))


def _is_vector(raw: bytes) -> bool:
    """Whether a blob reads as float32 numbers of an embedding's size (see above). Checked in C, byte by byte: the
    vector indexes' chunks are megabytes."""
    if len(raw) < 16 or len(raw) % 4:
        return False
    return max(raw[3::4].translate(_UNSIGNED)) <= _TOP_BYTE_LIMIT


def _cell_text(value) -> str | None:
    """A cell as text: a string as it is; a blob that is valid UTF-8 decoded; a blob that reads as an embedding's
    numbers (_is_vector) None, since its bytes are numbers, left to the byte check; any other blob decoded as Latin-1,
    since it may be text in another encoding and the name in it must be found. A blob is read in the wide encodings
    too (_wide_texts)."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, memoryview)):
        raw = bytes(value)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return None if _is_vector(raw) else raw.decode("latin-1")
    return None


# Text in a blob can be UTF-16 or UTF-32, in either byte order, with a byte-order mark or without (round 4: the round 3
# verifier stored a name so, and the erase recorded verified:true; read as float numbers, or as UTF-8 with a NUL between
# the letters, it was never seen). Every blob is read in each, at each alignment a header could leave it at. A vector
# read so is noise that holds the name or doesn't, like any other text. The one exception is a vector index's chunks
# (_vector_chunk_tables): megabytes of copies of the rows' own embeddings, which are read, and dropped and refilled
# from those rows by every erase (_rebuild_vec).
_WIDE = (("utf-16-le", 2), ("utf-16-be", 2), ("utf-32-le", 4), ("utf-32-be", 4))
# For UTF-32 without the codec's error handler, which runs once for each unit past U+10FFFF, most of a vector's units
# (3 ms a vector): such a unit is read as NUL instead. Its top byte is not 0, or the next one is past 0x10.
_PAST_TOP = bytes([0] + [1] * 255)
_PAST_MID = bytes([0] * 0x11 + [1] * 0xEF)
_KEEP_UNIT = bytes([0xFF, 0x00]) + bytes(254)


def _utf32(raw: bytes, little: bool) -> str:
    """raw, a whole number of units, as UTF-32, each unit past U+10FFFF read as NUL (a surrogate as U+FFFD)."""
    top, mid = (raw[3::4], raw[2::4]) if little else (raw[0::4], raw[1::4])
    past = int.from_bytes(top.translate(_PAST_TOP), "big") | int.from_bytes(mid.translate(_PAST_MID), "big")
    keep = past.to_bytes(len(top), "big").translate(_KEEP_UNIT)
    mask = bytearray(len(raw))
    for k in range(4):
        mask[k::4] = keep
    clean = (int.from_bytes(raw, "big") & int.from_bytes(mask, "big")).to_bytes(len(raw), "big")
    return clean.decode("utf-32-le" if little else "utf-32-be", errors="replace")


# Wide text can sit in a TEXT cell too (round 5: the round 4 verifier found a false success there). CAST(... AS TEXT)
# keeps its bytes, and Python reads them back as UTF-8 when they are valid: an ASCII name in UTF-16 or UTF-32 comes back
# with a NUL between its letters, a Cyrillic one in UTF-16 with control characters; a writer that read the bytes as
# Latin-1 stores each byte as a character. Such a str holds a NUL or another control character, which text doesn't (a
# tab, a line feed and a carriage return don't count, so ordinary text isn't read wide, which would slow every erase).
_WIDE_TEXT_HINT = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _wide_bytes(value) -> list[bytes]:
    """The bytes a cell's wide readings start from: a blob's own; a str's UTF-8 bytes (what CAST stored) and, when
    every character fits, its Latin-1 bytes, when it holds a control character (_WIDE_TEXT_HINT); [] for anything
    else."""
    if isinstance(value, (bytes, memoryview)):
        return [bytes(value)]
    if not isinstance(value, str) or not _WIDE_TEXT_HINT.search(value):
        return []
    out = [value.encode("utf-8")]
    if not value.isascii() and max(value) <= "\xff":
        out.append(value.encode("latin-1"))
    return out


def _wide_texts(value) -> list[str]:
    """A cell's readings in the wide encodings (_WIDE), from each of its _wide_bytes, each from each starting byte
    within one character; [] for a cell that has none."""
    out = []
    for raw in _wide_bytes(value):
        for encoding, width in _WIDE:
            for start in range(width):
                end = start + (len(raw) - start) // width * width
                if end > start:
                    unit = raw[start:end]
                    out.append(_utf32(unit, encoding.endswith("le")) if width == 4
                               else unit.decode(encoding, errors="replace"))
    return out


@functools.lru_cache(maxsize=8)
def _noise(pattern: str) -> re.Pattern:
    """Runs of characters that can't stand inside a match of the pattern, for a wide reading: a vector's is mostly
    such characters (a float's top bytes read as ideographs and Hangul), and folding them all took 14 ms a vector. A
    character of the Basic Multilingual Plane is one when it isn't printable ASCII (escapes and markup are written in
    it), and what it folds to is something, holds no separator, and shares no character, nor a character of its
    decomposition, with the pattern or the pattern's decomposition (so Hangul jamo and other parts of a composed letter
    stay). Each run reads as one NUL, which no name holds; next to the name it reads as an edge, so a near-match there
    reads as the name (the safe way: a trace)."""
    codes = [c for c in range(1, 0x10000) if not 0xD800 <= c <= 0xDFFF]
    folds = _fold_fast("\x00".join(map(chr, codes))).split("\x00")
    if len(folds) != len(codes):                         # not expected: then only NUL is noise
        return re.compile("\x00+")
    name, sep = set(pattern) | set(unicodedata.normalize("NFKD", pattern)), re.compile(_SEP)
    return re.compile(_class_of([0] + [c for c, f in zip(codes, folds) if f and not 0x20 <= c <= 0x7E
                                       and not sep.search(f)
                                       and not (set(f) | set(unicodedata.normalize("NFKD", f))) & name]).pattern
                      + "+")


def _readings(value, hit: re.Pattern, wide: bool = True) -> list[tuple[str, object]]:
    """(text, fold) for each reading of a cell: _cell_text's, folded as text is (_fold), and with its NULs taken out
    when it holds one (a NUL between the letters, or between the parts of the name, round 5); and unless wide is False
    the wide ones, each run of _noise read as one NUL and folded in C (_fold_fast), since normalize() in Python takes
    seconds a million characters."""
    text = _cell_text(value)
    noise = _noise(hit.pattern)
    plain = [text, text.replace("\x00", "")] if text and "\x00" in text else [text] if text else []
    return [(t, _fold) for t in plain] + [(noise.sub("\x00", t), _fold_fast)
                                          for t in (_wide_texts(value) if wide else ())]


def _vector_chunk_tables(con) -> set[str]:
    """The tables of float vectors behind each vec0 index (sqlite-vec's NAME_vector_chunksNN), which the erase drops
    and refills from the rows that remain."""
    vec = _vec_tables(con)
    return {t for t, _ in _tables(con) for v in vec if re.fullmatch(re.escape(v) + r"_vector_chunks\d+", t)}


def _scan(con, hit: re.Pattern, loose: re.Pattern) -> tuple[list, list, list]:
    """Every text cell, in every table (a blob that may be text counts, _cell_text): (traces, nears, unreadable). A
    trace is (table, column, key) for a cell that names the person; a near is (table, column, key, word, text) for each
    word in a cell that holds the name inside a longer word; unreadable is (table, column, key) for a TEXT cell whose
    bytes aren't valid UTF-8 (_Undecodable), which is read as best it can be and refused on. Vectors are left to the
    byte check, which reads every byte of the database files."""
    traces, nears, unreadable = [], [], []
    chunks = _vector_chunk_tables(con)
    for table, cols in _tables(con):
        for key, rec in _rows(con, table):
            for c in cols:
                if isinstance(rec.get(c), _Undecodable):
                    unreadable.append((table, c, key))
                readings = _readings(rec.get(c), hit, wide=table not in chunks)
                if any(_names_in(hit, text, fold=fold) for text, fold in readings):
                    traces.append((table, c, key))
                words: list[str] = []
                for text, fold in readings:
                    for w in _near_words(hit, loose, text, fold=fold):
                        if w not in words:
                            words.append(w)
                            nears.append((table, c, key, w, text))
    return traces, nears, unreadable


def _traces(con, hit: re.Pattern) -> list[tuple[str, str, object]]:
    """(table, column, key) for every text cell, in every table, that names the person in any reading (see _scan)."""
    chunks = _vector_chunk_tables(con)
    return [(t, c, k) for t, cols in _tables(con) for k, rec in _rows(con, t) for c in cols
            if any(_names_in(hit, text, fold=fold) for text, fold in _readings(rec.get(c), hit, wide=t not in chunks))]


def _undecodable(con) -> list[tuple[str, str]]:
    """(table, column) for each column, in every table, with a TEXT cell whose bytes aren't valid UTF-8."""
    return sorted({(t, c) for t, cols in _tables(con) for _, rec in _rows(con, t) for c in cols
                   if isinstance(rec.get(c), _Undecodable)})


def _schema(con, hit: re.Pattern, loose: re.Pattern) -> tuple[list[dict], list]:
    """The schema objects (tables, views, triggers, indexes) whose name or definition names the person (a column default
    is in its table's definition), and the near-matches in them as _scan gives them, keyed by the object's name."""
    found, nears = [], []
    for kind, name, sql in con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY type, name"):
        where = [w for w, text in (("name", name), ("definition", sql)) if _names_in(hit, text)]
        if where:
            found.append({"type": kind, "name": name, "where": " and ".join(where)})
        for col, text in (("name", name), ("sql", sql)):
            nears += [("sqlite_master", col, name, w, text) for w in _near_words(hit, loose, text)]
    return found, nears


# Context kept on each side of a match inside a vector, to recognise the same bytes in the file.
_BLOB_CONTEXT = 16


def _explained_bytes(db: Path, hit: re.Pattern, loose: re.Pattern, ruled: set[str]) -> set[tuple[str, int]]:
    """What the byte check, which reads the name without word edges, may find in kept data without it being a trace:
    (fast-folded text, where the name starts in it). Nothing else is explained, and an unexplained match is a trace.
      - a near-match a person ruled someone else (ruled, folded words), where a kept text cell, or the schema, holds it:
        the word. A near-match nobody ruled on isn't collected, nor is a match with edges;
      - a match by chance inside a kept vector (a float vector holds a short name's bytes now and then, in the low
        bytes of a float): the match with up to _BLOB_CONTEXT characters of the vector on each side."""
    out: set[tuple[str, int]] = set()
    if not db.is_file():
        return out
    con = _connect(db, readonly=True)
    try:
        raws = [(r[0] or "").encode("utf-8") for r in con.execute("SELECT name FROM sqlite_master")]
        raws += [r[0].encode("utf-8") for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")]
        vectors = []
        for table, cols in _tables(con):
            for _, rec in _rows(con, table):
                for c in cols:
                    v = rec.get(c)
                    if isinstance(v, str):
                        raws.append(v.raw if isinstance(v, _Undecodable) else v.encode("utf-8"))
                    elif isinstance(v, (bytes, memoryview)):
                        (raws if _cell_text(v) is not None else vectors).append(bytes(v))
    finally:
        con.close()
    for raw in raws:
        for t in _byte_texts(raw):
            for m in loose.finditer(t):
                if hit.match(t, m.start()):
                    continue                      # the name itself, in a kept row: a trace, never explained
                word, off = _word_around(t, m.start(), m.end())
                if _fold(word) in ruled:
                    out.add((word, off))
    for raw in vectors:
        for t in _byte_texts(raw):
            for m in loose.finditer(t):
                a, b = max(0, m.start() - _BLOB_CONTEXT), m.end() + _BLOB_CONTEXT
                out.add((t[a:b], m.start() - a))
    return out


@dataclass
class Plan:
    names: list[str]
    memories: list[dict] = field(default_factory=list)      # {"id", "archived", "text"}
    entities: list[dict] = field(default_factory=list)      # {"id", "name", "type", "why"}
    mentions: list[str] = field(default_factory=list)
    triples: list[str] = field(default_factory=list)
    wiki_pages: list[dict] = field(default_factory=list)    # {"title", "action": "remove" | "rebuild"}
    wiki_files: list[dict] = field(default_factory=list)    # {"file", "action": "remove" | "rebuild", "title"}
    beliefs: list[str] = field(default_factory=list)
    belief_log_lines: int = 0
    elsewhere: list[tuple[str, int]] = field(default_factory=list)
    elsewhere_near: list[tuple[str, int]] = field(default_factory=list)   # files with near-matches only
    db_other: list[dict] = field(default_factory=list)      # {"table", "column", "rows"}: named where it can't remove
    unreadable: list[dict] = field(default_factory=list)    # {"table", "column", "rows"}: TEXT that isn't valid UTF-8
    schema: list[dict] = field(default_factory=list)        # {"type", "name", "where"}: schema objects that name them
    near: list[dict] = field(default_factory=list)          # {"word", "place", "text"}: kept, until a person rules
    vec_tables: list[str] = field(default_factory=list)
    code: str = ""

    def counts(self) -> dict:
        return {"memories": len(self.memories), "entities": len(self.entities), "mentions": len(self.mentions),
                "triples": len(self.triples), "wiki_pages": len(self.wiki_pages), "wiki_files": len(self.wiki_files),
                "beliefs": len(self.beliefs), "belief_log_lines": self.belief_log_lines,
                "unremovable_cells": sum(d["rows"] for d in self.db_other), "schema_objects": len(self.schema),
                "unreadable_cells": sum(d["rows"] for d in self.unreadable)}

    def near_words(self) -> list[str]:
        return sorted({n["word"] for n in self.near})

    def empty(self) -> bool:
        return not any(self.counts().values())


def _paths(home: Path) -> dict:
    db = home / "db" / "apolaki.db"
    return {"db": db, "wal": Path(str(db) + "-wal"), "shm": Path(str(db) + "-shm"),
            "journal": Path(str(db) + "-journal"), "wiki": home / "wiki",
            "beliefs": home / "engine_beliefs.json", "belief_log": home / "engine_beliefs_log.jsonl",
            "ledger": home / "erasures.jsonl"}


def _vec_tables(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type = 'table'")
            if r[0] in ("memory_vec", "entity_vec") and "vec0" in (r[1] or "").lower()]


def _load_vec(con) -> bool:
    try:
        import sqlite_vec
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        return True
    except Exception:  # noqa: BLE001 - absent or unloadable: the caller refuses if vec tables exist
        return False


def _open(db: Path, readonly: bool):
    con = _connect(db, readonly)
    vec = _vec_tables(con)
    if vec and not _load_vec(con):
        con.close()
        raise EraseError(f"the database has vector indexes ({', '.join(vec)}) and sqlite-vec can't be loaded here, so "
                         f"their entries couldn't be removed. Nothing was removed. Run this where Apolaki runs, or "
                         f"pip install sqlite-vec")
    return con, vec


def _wiki_name(title: str) -> str:
    """The file name ApolakiMemoryStore.generate_wiki_page gives a page."""
    return title.lower().replace(" ", "_").replace("/", "_") + ".md"


def _read_rows(path: Path) -> list | None:
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        return None
    return rows if isinstance(rows, list) else None


def _snippet(text: str, word: str) -> str:
    """Up to 110 characters of a text, around where the near-match word is, for the dry run."""
    flat = " ".join((text or "").split())
    at = _fold(flat).find(word)
    start = max(0, at - 40) if at >= 0 else 0
    return ("..." if start else "") + flat[start:start + 110]


def plan(name: str, aliases: tuple[str, ...] = (), home: Path | None = None) -> Plan:
    """Everything the erase would remove, and every near-match it would keep, without changing anything."""
    home = home or config.home()
    names = [name, *aliases]
    hit, loose = _matcher(names), _matcher(names, edges=False)
    p = _paths(home)
    out = Plan(names=names)
    nears: list[tuple[dict, str, str]] = []      # (place, word, text) for each near-match in what the erase keeps

    def named(*texts) -> bool:
        return _names_in(hit, *texts)

    if p["db"].is_file():
        con, out.vec_tables = _open(p["db"], readonly=True)
        try:
            # Every text column of every table, read once: what names the person, by table, as row keys; and the
            # schema (table, view, trigger and index names and definitions, column defaults included).
            traces, cell_nears, unreadable = _scan(con, hit, loose)
            bad: dict[tuple[str, str], int] = {}
            for table, col, _ in unreadable:
                bad[(table, col)] = bad.get((table, col), 0) + 1
            out.unreadable = [{"table": t, "column": c, "rows": n} for (t, c), n in sorted(bad.items())]
            out.schema, schema_nears = _schema(con, hit, loose)
            in_table: dict[str, set] = {}
            for table, _, key in traces:
                in_table.setdefault(table, set()).add(key)
            ents = {r[0]: r for r in con.execute("SELECT id, name, entity_type FROM kg_entities")}
            person = {eid for eid in in_table.get("kg_entities", ()) if eid in ents}
            # Every memory the graph links to the person names them in its text (an entity is taken from the text),
            # so the column match finds those too.
            named_mem = in_table.get("memories", set())
            mems = [{"id": mid, "archived": bool(archived), "text": content} for mid, content, archived in con.execute(
                "SELECT id, content, archived FROM memories ORDER BY created_at") if mid in named_mem]
            erased_mem = {m["id"] for m in mems}
            mention_rows = con.execute("SELECT id, entity_id, memory_id FROM kg_entity_mentions").fetchall()
            with_memory = {r[0] for r in mention_rows if r[1] in person or r[2] in erased_mem}
            gone_mentions = with_memory | (in_table.get("kg_entity_mentions", set()) & {r[0] for r in mention_rows})
            # an entity whose every mention goes with the erased memories came only from them (a mention that goes
            # only because its own context names the person leaves its entity's memory, and so the entity, in place)
            remaining = {}
            for mid_, eid, memid in mention_rows:
                remaining.setdefault(eid, 0)
                remaining[eid] += mid_ not in with_memory
            orphans = {eid for eid, left in remaining.items() if left == 0 and eid not in person}
            gone_ents = person | orphans
            out.entities = [{"id": eid, "name": ents[eid][1], "type": ents[eid][2],
                             "why": "names the person" if eid in person else "only in erased memories"}
                            for eid in sorted(gone_ents, key=lambda e: ents[e][1].lower()) if eid in ents]
            out.memories = mems
            out.mentions = sorted(gone_mentions)
            out.triples = sorted(r[0] for r in con.execute(
                "SELECT id, subject_entity_id, object_entity_id, source_memory_id FROM kg_triples")
                if r[1] in gone_ents or r[2] in gone_ents or r[3] in erased_mem
                or r[0] in in_table.get("kg_triples", ()))
            gone_names = {ents[e][1].lower() for e in gone_ents if e in ents}
            kept = {r[1] for e, r in ents.items() if e not in gone_ents}           # as written: page titles keep case
            kept_names = {n.lower() for n in kept}
            gone_pages = set()
            for (pid, title, content) in con.execute("SELECT id, title, content FROM wiki_pages ORDER BY title"):
                if title.lower() in gone_names or named(title):
                    out.wiki_pages.append({"title": title, "action": "remove"})
                elif pid in in_table.get("wiki_pages", ()) or any(n in (content or "").lower() for n in gone_names):
                    out.wiki_pages.append({"title": title, "action": "rebuild" if title.lower() in kept_names
                                           else "remove"})
                else:
                    continue
                gone_pages.add(pid)        # the row goes either way; a rebuilt page is a new row from what remains
            # What names the person in a row this erase doesn't remove: it refuses until a person deals with it.
            removed = {"memories": erased_mem, "kg_entities": gone_ents, "kg_entity_mentions": gone_mentions,
                       "kg_triples": set(out.triples), "wiki_pages": gone_pages}
            other: dict[tuple[str, str], int] = {}
            for table, col, key in traces:
                if key not in removed.get(table, ()):
                    other[(table, col)] = other.get((table, col), 0) + 1
            out.db_other = [{"table": t, "column": c, "rows": n} for (t, c), n in sorted(other.items())]
            nears += [({"table": t, "column": c, "row": key}, w, text)
                      for t, c, key, w, text in cell_nears + schema_nears if key not in removed.get(t, ())]
        finally:
            con.close()
    else:
        gone_names, kept = set(), set()

    page_action = {_wiki_name(w["title"]): w for w in out.wiki_pages}
    kept_by_file = {_wiki_name(n): n for n in kept}
    if p["wiki"].is_dir():
        for f in sorted(p["wiki"].rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(p["wiki"]))
            text = f.read_text(encoding="utf-8", errors="ignore")
            if rel in page_action:
                out.wiki_files.append({"file": rel, "action": page_action[rel]["action"],
                                       "title": page_action[rel]["title"]})
            elif named(rel.replace("_", " "), text) or f.name in {_wiki_name(n) for n in gone_names}:
                title = kept_by_file.get(f.name)
                out.wiki_files.append({"file": rel, "action": "rebuild" if title else "remove", "title": title})
            else:                 # a page the erase leaves alone: its name and text can still hold a near-match
                nears += [({"file": "wiki/" + rel}, w, t) for t in (rel.replace("_", " "), text)
                          for w in _near_words(hit, loose, t)]

    rows = _read_rows(p["beliefs"])
    if rows is None:
        raise EraseError(f"{p['beliefs']} can't be read, so beliefs naming the person couldn't be found. Nothing "
                         f"was removed")
    for r in rows:
        text = json.dumps(r, ensure_ascii=False)
        if isinstance(r, dict) and named(text):
            out.beliefs.append(r.get("id"))
        else:
            nears += [({"file": p["beliefs"].name, "row": r.get("id") if isinstance(r, dict) else None}, w, text)
                      for w in _near_words(hit, loose, text)]
    try:
        log = p["belief_log"].read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        log = []
    for i, line in enumerate(log, 1):
        if named(line):
            out.belief_log_lines += 1
        kept_text = _redacted_line(line, hit) if named(line) else line      # what the redaction leaves of the line
        nears += [({"file": p["belief_log"].name, "row": i}, w, kept_text) for w in _near_words(hit, loose, kept_text)]
    out.near = [{"word": w, "place": place, "text": _snippet(text, w)} for place, w, text in nears]

    handled = {p["db"], p["wal"], p["shm"], p["beliefs"], p["belief_log"], p["ledger"]}
    for f in sorted(home.rglob("*")) if home.is_dir() else []:
        if not f.is_file() or f in handled or p["wiki"] in f.parents:
            continue
        try:
            texts = _byte_texts(f.read_bytes())
        except OSError:
            out.elsewhere.append((str(f.relative_to(home)), -1))
            continue
        n = max(len(hit.findall(t)) for t in texts)
        if n:
            out.elsewhere.append((str(f.relative_to(home)), n))
        elif any(_near_in(hit, loose, t) for t in texts):
            out.elsewhere_near.append((str(f.relative_to(home)), max(len(_near_in(hit, loose, t)) for t in texts)))

    ident = {"names": [_fold(n) for n in names], "memories": [m["id"] for m in out.memories],
             "entities": [e["id"] for e in out.entities], "mentions": out.mentions, "triples": out.triples,
             "wiki_pages": out.wiki_pages, "wiki_files": out.wiki_files, "beliefs": out.beliefs,
             "belief_log_lines": out.belief_log_lines, "db_other": out.db_other, "schema": out.schema,
             "unreadable": out.unreadable,
             "near": sorted(json.dumps([n["word"], n["place"]], sort_keys=True, default=str) for n in out.near)}
    out.code = hashlib.sha256(json.dumps(ident, sort_keys=True).encode()).hexdigest()[:12]
    return out


def _rebuild_vec(con, table: str) -> None:
    """Drop a vec0 index and fill it again from the rows that remain, so no erased vector survives in its chunks."""
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,)).fetchone()[0]
    con.execute(f"DROP TABLE {table}")
    con.execute(sql)
    if table == "memory_vec":
        con.execute("INSERT INTO memory_vec (id, embedding) SELECT id, embedding FROM memories "
                    "WHERE archived = 0 AND embedding IS NOT NULL")
    else:
        con.execute("INSERT INTO entity_vec (id, embedding) SELECT id, embedding FROM kg_entities "
                    "WHERE embedding IS NOT NULL")


def _in_rows(con, table: str, ids: list[str]) -> list:
    if not ids:
        return []
    return con.execute(f"SELECT id, embedding FROM {table} WHERE id IN (%s)" % ",".join("?" * len(ids)),
                       tuple(ids)).fetchall()


def _delete(con, table: str, ids: list[str]) -> None:
    for i in range(0, len(ids), 500):
        chunk = ids[i:i + 500]
        con.execute(f"DELETE FROM {table} WHERE id IN (%s)" % ",".join("?" * len(chunk)), tuple(chunk))


def leftovers(names: list[str], home: Path, blobs: list[bytes] = (), others: tuple[str, ...] = ()) -> list[str]:
    """Where the name, or one of the given embeddings, can still be read; [] when nowhere. others are the near-match
    words a person ruled someone else (erase's not_them). Four checks:
      - every text column of every table, with the full fold, escapes decoded and markup taken out;
      - the bytes of the database, its write-ahead log, shared-memory file and any rollback journal (a fast fold, see
        _fold_bytes, escapes decoded), where the embeddings are looked for too. The name is looked for without word
        edges, since the bytes around a column value are anything (the timestamp before archive_reason ends in a
        digit). A match is accepted only where kept data explains it (_explained_bytes): a near-match ruled someone
        else, in a kept row, or a chance match inside a kept vector. A longer word nobody ruled on explains nothing;
      - the wiki folder (contents and file names) and the engine's belief files, with the full fold, escapes decoded;
      - a second dry run, which must find nothing to remove or refuse on, and no near-match nobody ruled on."""
    hit, loose = _matcher(names), _matcher(names, edges=False)
    ruled = {_fold(w) for w in others}
    p = _paths(home)
    found = []
    if p["db"].is_file():
        con = _connect(p["db"], readonly=True)
        try:
            found += sorted({f"{p['db']}: table {t}, column {c}: the name" for t, c, _ in _traces(con, hit)})
            found += [f"{p['db']}: table {t}, column {c}: text that isn't valid UTF-8, which the check can't read"
                      for t, c in _undecodable(con)]
        finally:
            con.close()
    explained = None                     # read from the kept rows only when the bytes hold a match to explain
    for f in (p["db"], p["wal"], p["shm"], p["journal"]):
        try:
            raw = f.read_bytes()
        except FileNotFoundError:
            continue
        matches = [(t, m) for t in _byte_texts(raw) for m in loose.finditer(t)]
        if matches and explained is None:
            explained = _explained_bytes(p["db"], hit, loose, ruled)
        if any(not any(m.start() >= off and t.startswith(word, m.start() - off) for word, off in explained)
               for t, m in matches):
            found.append(f"{f}: the name")
        if any(b and b in raw for b in blobs):
            found.append(f"{f}: an erased embedding")
    files = [p["beliefs"], p["belief_log"]]
    if p["wiki"].is_dir():
        files += [f for f in sorted(p["wiki"].rglob("*")) if f.is_file()]
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except FileNotFoundError:
            continue
        if _names_in(hit, text) or (p["wiki"] in f.parents and _names_in(hit, f.name)):
            found.append(f"{f}: the name")
    again = plan(names[0], tuple(names[1:]), home)
    if not again.empty():
        found.append(f"a second dry run still finds {', '.join(f'{v} {k}' for k, v in again.counts().items() if v)}")
    unruled = [w for w in again.near_words() if w not in ruled]
    if unruled:
        found.append(f"{len(unruled)} near-match nobody ruled on (the name inside a longer word, in what was kept)")
    return found


def erase(name: str, aliases: tuple[str, ...] = (), confirm: str = "", by: str = "", reason: str = "",
          home: Path | None = None, not_them: tuple[str, ...] = ()) -> dict:
    """Remove what plan() lists, if confirm is its code. Returns {"code", "counts", "elsewhere", "near", "ledger"}.

    not_them is a person's ruling on the plan's near-matches (the name inside a longer word, in what is kept): each word
    named there is someone else, and stays. It must name every near-match word the plan lists and nothing else, or the
    erase refuses before changing anything. A near-match that is the person is given as an alias instead, which erases
    it. The ledger records each ruled near-match by where it is, never by the word, which contains the name."""
    home = home or config.home()
    if not by.strip():
        raise EraseError("say who is erasing (by)")
    if not reason.strip():
        raise EraseError("say why (reason): it goes in the erasure record, without the name")
    p = plan(name, aliases, home)
    if not confirm or confirm != p.code:
        raise EraseError(f"the code {confirm!r} isn't this erase's ({p.code}): what would be removed has changed "
                         f"since the dry run, or no dry run was read. Nothing was removed. Run the dry run again")
    if p.unreadable:
        raise EraseUnreadable("the database holds text that isn't valid UTF-8 (" + ", ".join(
            f"table {d['table']}, column {d['column']}: {d['rows']} cell(s)" for d in p.unreadable) + "), written "
            "with CAST(... AS TEXT) or by a program writing another encoding, so whether it names the person can't be "
            "read with certainty. Nothing was removed. A person rewrites those cells as UTF-8 text (or as a blob), or "
            "removes them, then runs the dry run again")
    if p.db_other:
        raise EraseError("the database names the person where this erase can't remove it from ("
                         + ", ".join(f"table {d['table']}, column {d['column']}: {d['rows']} row(s)"
                                     for d in p.db_other)
                         + "). Nothing was removed. A person deals with those rows first, then runs the dry run again")
    if p.schema:
        raise EraseError("the database's schema names the person (" + ", ".join(
            f"{s['type']} {s['name']!r}: its {s['where']}" for s in p.schema) + "), and this erase doesn't change the "
            "schema. Nothing was removed. A person renames or drops those first, then runs the dry run again")
    ruled = sorted({_fold(w) for w in not_them if w.strip()})
    wanted = p.near_words()
    if sorted(set(ruled) - set(wanted)):
        raise EraseError(f"--not-them names {len(set(ruled) - set(wanted))} word(s) the dry run didn't list as a "
                         f"near-match (each must be a near-match word exactly as the dry run prints it). Nothing was "
                         f"removed")
    if sorted(set(wanted) - set(ruled)):
        raise EraseError(f"the dry run lists {len(set(wanted) - set(ruled))} near-match(es) nobody has ruled on (the "
                         f"name inside a longer word, in something the erase keeps). Nothing was removed. If each is "
                         f"someone else, name it with --not-them WORD; if it is the person, give it as an --alias and "
                         f"run the dry run again")
    names = p.names
    hit, loose = _matcher(names), _matcher(names, edges=False)
    paths = _paths(home)
    blobs: list[bytes] = []
    problems: list[str] = []
    if paths["db"].is_file():
        con, vec = _open(paths["db"], readonly=False)
        try:
            con.execute("PRAGMA secure_delete = ON")
            con.execute("PRAGMA foreign_keys = ON")
            mem_ids = [m["id"] for m in p.memories]
            ent_ids = [e["id"] for e in p.entities]
            gone = {r[1] for r in _in_rows(con, "memories", mem_ids) + _in_rows(con, "kg_entities", ent_ids) if r[1]}
            _delete(con, "kg_entity_mentions", p.mentions)
            _delete(con, "kg_triples", p.triples)
            _delete(con, "memories", mem_ids)
            _delete(con, "kg_entities", ent_ids)
            remaining = {r[0] for r in con.execute("SELECT embedding FROM memories WHERE embedding IS NOT NULL")}
            remaining |= {r[0] for r in con.execute("SELECT embedding FROM kg_entities WHERE embedding IS NOT NULL")}
            blobs = [b for b in gone if b not in remaining]     # an identical vector kept for a kept row isn't theirs
            for w in p.wiki_pages:
                con.execute("DELETE FROM wiki_pages WHERE title = ?", (w["title"],))
            con.commit()
            for table in vec:
                _rebuild_vec(con, table)
            con.commit()
            from .memory_store import ApolakiMemoryStore     # its page format; it reads only conn and wiki_path
            pages = types.SimpleNamespace(conn=con, wiki_path=paths["wiki"])
            for f in p.wiki_files:
                (paths["wiki"] / f["file"]).unlink(missing_ok=True)
            rebuild = {w["title"] for w in p.wiki_pages if w["action"] == "rebuild"}
            rebuild |= {f["title"] for f in p.wiki_files if f["action"] == "rebuild" and f["title"]}
            for title in sorted(rebuild):
                if paths["wiki"].is_dir() and ApolakiMemoryStore.generate_wiki_page(pages, title) is None:
                    (paths["wiki"] / _wiki_name(title)).unlink(missing_ok=True)
            con.commit()
            # The deletes are committed: from here a failure is reported, never raised past the check and the ledger.
            try:
                con.execute("VACUUM")
            except sqlite3.Error as e:      # e.g. no room for the copy VACUUM writes: secure_delete zeroed the rows
                problems.append(f"VACUUM failed ({e}), so the database file wasn't rebuilt; the deleted rows were "
                                f"zeroed by secure_delete. Free space the size of the database and run the erase again")
            try:
                busy = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
            except sqlite3.Error as e:
                busy, problems = 0, problems + [f"the write-ahead log couldn't be emptied ({e})"]
            if busy:
                problems.append("the write-ahead log couldn't be emptied: another connection is reading the database. "
                                "Stop it (docs/STOPPING.md) and run the erase again")
        finally:
            con.close()
    else:                                    # no database: nothing to rebuild a page from
        for f in p.wiki_files:
            (paths["wiki"] / f["file"]).unlink(missing_ok=True)

    if p.beliefs:
        rows = _read_rows(paths["beliefs"]) or []
        kept = [r for r in rows if not (isinstance(r, dict) and r.get("id") in p.beliefs)]
        tmp = paths["beliefs"].with_suffix(".tmp")
        tmp.write_text(json.dumps(kept, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(paths["beliefs"])
    if p.belief_log_lines:
        lines = paths["belief_log"].read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            if not _names_in(hit, line):
                out.append(line)
                continue
            out.append(_redacted_line(line, hit))
        tmp = paths["belief_log"].with_suffix(".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(paths["belief_log"])
    if p.beliefs:
        from .. import learning
        learning.log_removed([{"id": b, "source": REDACTED} for b in p.beliefs], by="erase-person", redact=REDACTED)

    left = problems + leftovers(names, home, blobs, others=tuple(ruled))

    def unnamed(value):                  # a ledger value that names the person, even inside a longer word, isn't kept
        return REDACTED if isinstance(value, str) and (_names_in(hit, value) or _near_words(hit, loose, value)) \
            else value
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": unnamed(by.strip()),
              "reason": unnamed(reason.strip()), "code": p.code, "counts": p.counts(), "verified": not left,
              "problems": problems, "other_files_naming_them": len(p.elsewhere),
              "near_matches": [{"place": {k: unnamed(v) for k, v in n["place"].items()}, "ruling": "someone else"}
                               for n in p.near]}
    with paths["ledger"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if left:
        raise EraseIncomplete("the erase ran, but its check still reads the name or an erased embedding, or a step "
                              "that clears deleted bytes failed: " + "; ".join(left))
    return {"code": p.code, "counts": p.counts(), "elsewhere": p.elsewhere, "near": len(p.near),
            "ledger": str(paths["ledger"])}


def _redacted_line(line: str, hit: re.Pattern) -> str:
    """A belief-log line with every string that names the person replaced (_redact); a line that isn't JSON goes
    whole."""
    try:
        return json.dumps(_redact(json.loads(line), hit), ensure_ascii=False)
    except ValueError:
        return json.dumps({"kind": REDACTED})


def _redact(value, hit: re.Pattern):
    """A belief-log row with every string that names the person replaced, however deep it sits."""
    if isinstance(value, str):
        return REDACTED if _names_in(hit, value) else value
    if isinstance(value, list):
        return [_redact(v, hit) for v in value]
    if isinstance(value, dict):
        return {(REDACTED if _names_in(hit, k) else k): _redact(v, hit) for k, v in value.items()}
    return value


def describe(p: Plan) -> str:
    """The dry run, for a person to read."""
    lines = [f"Erase {' / '.join(repr(n) for n in p.names)}: a dry run. Nothing has been changed."]
    if p.empty():
        lines.append("Apolaki's memory holds nothing under these names.")
    if p.memories:
        lines.append(f"\nMemories that go whole ({len(p.memories)}), with their embeddings:")
        lines += [f"  {m['id'][:8]}{' (archived)' if m['archived'] else ''}: {' '.join(m['text'].split())[:110]}"
                  for m in p.memories]
    if p.entities:
        lines.append(f"\nEntities ({len(p.entities)}):")
        lines += [f"  {e['name']} ({e['type']}): {e['why']}" for e in p.entities]
    if p.mentions or p.triples:
        lines.append(f"\nGraph rows: {len(p.mentions)} mention(s), {len(p.triples)} triple(s)")
    if p.wiki_pages or p.wiki_files:
        lines.append("\nWiki:")
        lines += [f"  page {w['title']!r}: {w['action']}" for w in p.wiki_pages]
        lines += [f"  file {f['file']}: {f['action']}" for f in p.wiki_files]
    if p.beliefs or p.belief_log_lines:
        lines.append(f"\nEngine beliefs: {len(p.beliefs)} removed; {p.belief_log_lines} belief-log line(s) redacted")
    if p.vec_tables:
        lines.append(f"\nVector indexes rebuilt from what remains: {', '.join(p.vec_tables)}")
    if p.unreadable:
        lines.append(f"\nText that isn't valid UTF-8 ({len(p.unreadable)}), so whether it names the person can't be read "
                     f"with certainty. The erase WILL REFUSE (exit code 4) until a person rewrites these cells as "
                     f"UTF-8 text, or removes them:")
        lines += [f"  table {d['table']}, column {d['column']}: {d['rows']} cell(s)" for d in p.unreadable]
    if p.db_other:
        lines.append(f"\nIn the database where this command can't remove it from ({len(p.db_other)}), so the erase "
                     f"WILL REFUSE until a person deals with these rows:")
        lines += [f"  table {d['table']}, column {d['column']}: {d['rows']} row(s)" for d in p.db_other]
    if p.schema:
        lines.append(f"\nIn the database's schema ({len(p.schema)}), which this command doesn't change, so the erase "
                     f"WILL REFUSE until a person renames or drops these:")
        lines += [f"  {s['type']} {s['name']!r}: its {s['where']}" for s in p.schema]
    if p.near:
        lines.append(f"\nNear-matches ({len(p.near)}): the name inside a longer word, in what this erase keeps. The "
                     f"erase WILL REFUSE until a person rules on each word: someone else (--not-them WORD), or the "
                     f"person (give it as an --alias and run the dry run again, and it is erased):")
        for n in p.near:
            where = ", ".join(f"{k} {str(v)[:8] if k == 'row' and isinstance(v, str) else v}"
                              for k, v in n["place"].items())
            lines.append(f"  {n['word']!r}: {where}: {n['text']}")
    if p.elsewhere:
        lines.append(f"\nNot memory, so NOT erased by this command; the name is also in ({len(p.elsewhere)}):")
        lines += [f"  {path} ({'unreadable' if n < 0 else f'{n} time(s)'})" for path, n in p.elsewhere]
        lines.append("  A person deals with these by hand (see docs/DATA_LIFECYCLE.md).")
    if p.elsewhere_near:
        lines.append(f"\nNot memory, and NOT touched; the name inside a longer word is in ({len(p.elsewhere_near)}):")
        lines += [f"  {path} ({n} near-match(es))" for path, n in p.elsewhere_near]
    if not p.empty():
        aliases = "".join(f" --alias {a!r}" for a in p.names[1:])
        lines.append(f"\nTo erase exactly this: python -m apolaki.engine erase-person {p.names[0]!r}{aliases} "
                     f"--confirm {p.code} --by WHO --reason WHY")
        if p.near:
            lines.append("  with, only if a person has read each near-match above and it is someone else: "
                         + " ".join(f"--not-them {w!r}" for w in p.near_words()))
    return "\n".join(lines)
