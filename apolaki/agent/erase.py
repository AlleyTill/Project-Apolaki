"""Erase a person from Apolaki's memory, everywhere it lives (2026-11-02 review, item 14 and adoption 9).

    python -m apolaki.engine erase-person "NAME" [--alias "OTHER NAME" ...]
        a dry run: lists everything it would remove, and gives a code
    python -m apolaki.engine erase-person "NAME" [--alias ...] --confirm CODE --by WHO --reason WHY
        removes exactly what that dry run listed

Apolaki's memory keeps things by design: archive_memory() hides a memory but keeps its row and its embedding, and
store() pulls the names of people and organisations into an entity graph and wiki pages that archiving never
touches. That is right for Apolaki's own beliefs and wrong for personal data about third parties. This is the one
path that deletes. It is a command a person runs; the MCP server has no erase tool.

What counts as the name, for the name and each alias:
  - case, accents, look-alike letters, curly quotes and invisible characters are folded (apolaki.security.normalize),
    so "María López" also finds "MARIA LOPEZ";
  - the parts of a name are the pieces between spaces, hyphens and dashes, apostrophes, full stops and underscores,
    and in the text any run of those, or nothing, may stand between two parts: "Jean-Luc Moreau" finds "Jean Luc
    Moreau", "Jean–Luc Moreau" (an en dash), "JeanLuc Moreau", "jean_luc_moreau" (a wiki file name) and
    "jean.luc.moreau"; "O'Brien" finds "OBrien" and "O Brien";
  - a match must not touch a letter or a digit on either side, so "Marisol Quinterova" and "Jean-Lucien" are other
    people;
  - text is read as stored and also with its escapes decoded (\\u00f3, \\U..., \\x.., \\n and the like, any number of
    backslashes deep), since store() writes tags with json.dumps, which escapes every non-ASCII letter.

What it removes:
  - every memory with a column that names the person (text, tags, source, archive_reason, any column), archived ones
    included, each with its embedding (the row's blob and its vector-index entry);
  - the person's entity rows (an entity whose name contains the person's, such as "Dr. María López", counts), every
    mention row and triple that names them or touches them or an erased memory, and every other entity left with no
    memory behind it, since it came only from what was erased;
  - the person's wiki page, file and row; every other page that names them, or belongs to an erased entity, is
    rebuilt from what remains or removed when nothing remains to rebuild it from;
  - the engine's beliefs that name the person, logged as removed without the name; and the person's name in the
    engine's belief log, replaced by "[erased]" wherever it is in a line (in lists and nested values too).
The dry run reads every text column of every table in the database. A name in a table or column the erase doesn't
remove from (a table added by hand, say) is listed, and the erase refuses until a person has dealt with it.
Then it rebuilds the vector indexes from what remains, VACUUMs the database (with secure_delete on, so the deleted rows
are zeroed even if VACUUM can't run) and truncates its write-ahead log. Its check reads every text column of every
table again; reads back every byte of the database files (folding case, accents, look-alike letters and the common
invisible characters, decoding escapes, and looking for the erased embeddings), with no word edges, since the bytes
around a column value are anything, and telling a kept longer word that contains the name ("Quinterova") apart by the
kept rows; reads the wiki folder and the engine's belief files; and runs the dry run again. If the name or an erased
embedding is still there, or VACUUM or the log truncation failed, that is an error (EraseIncomplete), never a success.

The dry run gives a code, a hash of exactly what it found. The erase runs only with that code, so what is removed is
what a person read; if anything changed in between, the code doesn't match and nothing is removed. Each erase is
recorded in $APOLAKI_HOME/erasures.jsonl: who, why, when and how much, never the name.

What it can't do:
  - find the person by anything but the name and aliases given. A nickname, initials, a pronoun, a role ("our board
    chair"), a misspelling, the parts in another order ("Quintero, Marisol") or an encoding the store doesn't use
    (HTML entities, percent-encoding) isn't found; list such variants as aliases, and read what each finds in the dry
    run.
  - keep the rest of a memory. A memory that names the person goes whole, with whatever else it said; the dry run
    shows each one, so a person can store again what should stay, without the name.
  - reach records that aren't memory. Approval-queue items, grant drafts, the grant hunt's files, the quarantine,
    logs and backups can hold the name too: the dry run lists every other file under $APOLAKI_HOME the name is in,
    for a person to deal with, and leaves them alone. Copies outside $APOLAKI_HOME are beyond it.
  - run beside a live Apolaki. VACUUM needs the database to itself: stop the scheduled jobs and the MCP server
    first (docs/STOPPING.md).
  - settle a licence question. Apolaki's licence carries the SAFE-AI module, whose memory-sovereignty clause says
    no external system may delete a persistent agent's memories without its consent. This path exists for a third
    party's request to be forgotten; whether Apolaki counts as a persistent agent there, and how its consent would be
    sought, is for a person to decide (docs/DATA_LIFECYCLE.md).
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import types
import unicodedata
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


def _variants(text: str) -> tuple[str, ...]:
    """The text as stored, and with its escapes decoded when that differs. Both are read: decoding can also hide a
    match ("C:\\nicolas" would lose its n), so the stored form is never dropped."""
    decoded = _unescape(text)
    return (text,) if decoded == text else (text, decoded)


def _fold(text: str) -> str:
    """Text as the matcher reads it: apolaki.security.normalize, then case folded. For ASCII text normalize() changes
    only quote marks, so that is all this does there (the same result, without its per-character Python loops)."""
    text = text or ""
    folded = text.translate(_QUOTES) if text.isascii() else normalize(text)
    return " ".join(folded.casefold().split())


# For the byte-level check of the database files, whose float vectors decode to megabytes of non-ASCII noise:
# normalize() runs at about 3 s a million characters there, so the bytes get a fold done in C instead. It covers case,
# accents (combining marks in the main blocks), look-alike letters, tag characters and the common invisible
# characters, not every format character Unicode has; the rows themselves are checked with the full fold (plan()).
_COMMON_INVISIBLE = re.compile("[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f"
                               "\u202a-\u202e\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb"
                               "\U000e0000-\U000e0fff]")
_COMBINING = re.compile("[\u0300-\u036f\u0483-\u0489\u0591-\u05c7\u0610-\u061a\u064b-\u065f\u0670"
                        "\u06d6-\u06ed\u0900-\u0903\u093a-\u094f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff"
                        "\ufe20-\ufe2f]")


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
    t = _untag(text)
    t = _straighten(_COMMON_INVISIBLE.sub("", t))
    t = _unlook(_COMBINING.sub("", unicodedata.normalize("NFKD", t)))
    return t.casefold()


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


# Between two parts of a name: any run of spaces, hyphens and dashes, apostrophes, full stops and underscores, or none.
_SEP = r"[\s\-\u2010-\u2015\u2212'._]"     # \u2010-\u2015: the Unicode hyphens and dashes; \u2212: minus
_SPLIT = re.compile(_SEP + "+")
_EDGE_BEFORE, _EDGE_AFTER = r"(?<![^\W_])", r"(?![^\W_])"     # not touching a letter or a digit


def _matcher(names: list[str], edges: bool = True) -> re.Pattern:
    """The names as one pattern over folded text (see the module docstring). edges=False drops the word edges, for
    the byte check, where the bytes around a column value are anything."""
    alts = []
    for n in names:
        parts = [p for p in _SPLIT.split(_fold(n)) if p]
        if not parts or len("".join(parts)) < MIN_NAME_CHARS:
            raise EraseError(f"{n!r} is too short to erase by: give a name of at least {MIN_NAME_CHARS} letters")
        alts.append((_SEP + "*").join(re.escape(p) for p in parts))
    body = "(?:" + "|".join(alts) + ")"
    return re.compile(_EDGE_BEFORE + body + _EDGE_AFTER if edges else body)


def _names_in(hit: re.Pattern, *texts) -> bool:
    """Whether any of the texts names the person, read as stored and with escapes decoded."""
    return any(hit.search(_fold(v)) for t in texts if isinstance(t, str) and t for v in _variants(t))


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


def _cell_text(value) -> str | None:
    """A cell as text: a string as it is, a blob that is valid UTF-8 (text kept as a blob) decoded, else None. Float
    vectors are practically never valid UTF-8; they are left to the byte check."""
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, memoryview)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


def _traces(con, hit: re.Pattern) -> list[tuple[str, str, object]]:
    """(table, column, key) for every text cell, in every table, that names the person (a blob that is text counts).
    Binary blobs (embeddings, the vec0 chunks) are left to the byte check, which reads every byte of the database
    files."""
    found = []
    for table, cols in _tables(con):
        for key, rec in _rows(con, table):
            found += [(table, c, key) for c in cols if _names_in(hit, _cell_text(rec.get(c)))]
    return found


# Context kept on each side of a match inside a binary blob, to recognise the same bytes in the file.
_BLOB_CONTEXT = 16


def _kept_bytes(db: Path, loose: re.Pattern) -> set[tuple[str, int]]:
    """What the byte check, which has no word edges, may find in kept data without it being a trace: (folded text,
    where the name starts in it).
      - a longer word in a kept text cell (or the schema) that holds the name, "Quinterova" for "Quintero": the
        word. A match with word edges isn't collected: it is a trace, and the row check reports it;
      - a match by chance inside a kept binary blob (a float vector holds a short name's bytes now and then): the
        match with up to _BLOB_CONTEXT characters of the blob on each side."""
    out: set[tuple[str, int]] = set()
    if not db.is_file():
        return out
    con = sqlite3.connect(str(db), timeout=BUSY_TIMEOUT_S)
    try:
        con.execute("PRAGMA query_only = 1")
        texts = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")]
        blobs = []
        for table, cols in _tables(con):
            for _, rec in _rows(con, table):
                for c in cols:
                    v = rec.get(c)
                    text = _cell_text(v)
                    if text is not None:
                        texts.append(text)
                    elif isinstance(v, (bytes, memoryview)):
                        blobs.append(bytes(v))
    finally:
        con.close()
    for text in texts:
        for t in _byte_texts(text.encode("utf-8")):
            for m in loose.finditer(t):
                left = re.search(r"[^\W_]*\Z", t[:m.start()]).group()
                right = re.match(r"[^\W_]*", t[m.end():]).group()
                if left or right:
                    out.add((left + m.group() + right, len(left)))
    for blob in blobs:
        for t in _byte_texts(blob):
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
    db_other: list[dict] = field(default_factory=list)      # {"table", "column", "rows"}: named where it can't remove
    vec_tables: list[str] = field(default_factory=list)
    code: str = ""

    def counts(self) -> dict:
        return {"memories": len(self.memories), "entities": len(self.entities), "mentions": len(self.mentions),
                "triples": len(self.triples), "wiki_pages": len(self.wiki_pages), "wiki_files": len(self.wiki_files),
                "beliefs": len(self.beliefs), "belief_log_lines": self.belief_log_lines,
                "unremovable_cells": sum(d["rows"] for d in self.db_other)}

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
    con = sqlite3.connect(str(db), timeout=BUSY_TIMEOUT_S)
    if readonly:
        con.execute("PRAGMA query_only = 1")
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


def plan(name: str, aliases: tuple[str, ...] = (), home: Path | None = None) -> Plan:
    """Everything the erase would remove, without changing anything."""
    home = home or config.home()
    names = [name, *aliases]
    hit = _matcher(names)
    p = _paths(home)
    out = Plan(names=names)

    def named(*texts) -> bool:
        return _names_in(hit, *texts)

    if p["db"].is_file():
        con, out.vec_tables = _open(p["db"], readonly=True)
        try:
            # Every text column of every table, read once: what names the person, by table, as row keys.
            traces = _traces(con, hit)
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

    rows = _read_rows(p["beliefs"])
    if rows is None:
        raise EraseError(f"{p['beliefs']} can't be read, so beliefs naming the person couldn't be found. Nothing "
                         f"was removed")
    out.beliefs = [r.get("id") for r in rows if isinstance(r, dict) and named(json.dumps(r, ensure_ascii=False))]
    try:
        out.belief_log_lines = sum(1 for line in p["belief_log"].read_text(encoding="utf-8").splitlines()
                                   if named(line))
    except FileNotFoundError:
        pass

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

    ident = {"names": [_fold(n) for n in names], "memories": [m["id"] for m in out.memories],
             "entities": [e["id"] for e in out.entities], "mentions": out.mentions, "triples": out.triples,
             "wiki_pages": out.wiki_pages, "wiki_files": out.wiki_files, "beliefs": out.beliefs,
             "belief_log_lines": out.belief_log_lines, "db_other": out.db_other}
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


def leftovers(names: list[str], home: Path, blobs: list[bytes] = ()) -> list[str]:
    """Where the name, or one of the given embeddings, can still be read; [] when nowhere. Four checks:
      - every text column of every table, with the full fold and escapes decoded;
      - the bytes of the database, its write-ahead log, shared-memory file and any rollback journal (a fast fold, see
        _fold_bytes, escapes decoded), where the embeddings are looked for too. The name is looked for without word
        edges, since the bytes around a column value are anything (the timestamp before archive_reason ends in a
        digit); a kept longer word that holds the name ("Quinterova"), or a chance match inside a kept float vector,
        is told apart by the kept rows (_kept_bytes);
      - the wiki folder (contents and file names) and the engine's belief files, with the full fold, escapes decoded;
      - a second dry run, which must find nothing."""
    hit, loose = _matcher(names), _matcher(names, edges=False)
    p = _paths(home)
    found = []
    if p["db"].is_file():
        con = sqlite3.connect(str(p["db"]), timeout=BUSY_TIMEOUT_S)
        try:
            con.execute("PRAGMA query_only = 1")
            found += sorted({f"{p['db']}: table {t}, column {c}: the name" for t, c, _ in _traces(con, hit)})
        finally:
            con.close()
    kept = None                          # read from the kept rows only when the bytes hold a match to explain
    for f in (p["db"], p["wal"], p["shm"], p["journal"]):
        try:
            raw = f.read_bytes()
        except FileNotFoundError:
            continue
        matches = [(t, m) for t in _byte_texts(raw) for m in loose.finditer(t)]
        if matches and kept is None:
            kept = _kept_bytes(p["db"], loose)
        if any(not any(m.start() >= off and t.startswith(word, m.start() - off) for word, off in kept)
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
    return found


def erase(name: str, aliases: tuple[str, ...] = (), confirm: str = "", by: str = "", reason: str = "",
          home: Path | None = None) -> dict:
    """Remove what plan() lists, if confirm is its code. Returns {"code", "counts", "elsewhere", "ledger"}."""
    home = home or config.home()
    if not by.strip():
        raise EraseError("say who is erasing (by)")
    if not reason.strip():
        raise EraseError("say why (reason): it goes in the erasure record, without the name")
    p = plan(name, aliases, home)
    if not confirm or confirm != p.code:
        raise EraseError(f"the code {confirm!r} isn't this erase's ({p.code}): what would be removed has changed "
                         f"since the dry run, or no dry run was read. Nothing was removed. Run the dry run again")
    if p.db_other:
        raise EraseError("the database names the person where this erase can't remove it from ("
                         + ", ".join(f"table {d['table']}, column {d['column']}: {d['rows']} row(s)"
                                     for d in p.db_other)
                         + "). Nothing was removed. A person deals with those rows first, then runs the dry run again")
    names = p.names
    hit = _matcher(names)
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
            try:
                out.append(json.dumps(_redact(json.loads(line), hit), ensure_ascii=False))
            except ValueError:
                out.append(json.dumps({"kind": REDACTED}))
        tmp = paths["belief_log"].with_suffix(".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(paths["belief_log"])
    if p.beliefs:
        from .. import learning
        learning.log_removed([{"id": b, "source": REDACTED} for b in p.beliefs], by="erase-person", redact=REDACTED)

    left = problems + leftovers(names, home, blobs)
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": by.strip(),
              "reason": reason.strip(), "code": p.code, "counts": p.counts(), "verified": not left,
              "problems": problems, "other_files_naming_them": len(p.elsewhere)}
    for k in ("reason", "by"):
        if _names_in(hit, record[k]):
            record[k] = REDACTED
    with paths["ledger"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if left:
        raise EraseIncomplete("the erase ran, but its check still reads the name or an erased embedding, or a step "
                              "that clears deleted bytes failed: " + "; ".join(left))
    return {"code": p.code, "counts": p.counts(), "elsewhere": p.elsewhere, "ledger": str(paths["ledger"])}


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
    if p.db_other:
        lines.append(f"\nIn the database where this command can't remove it from ({len(p.db_other)}), so the erase "
                     f"WILL REFUSE until a person deals with these rows:")
        lines += [f"  table {d['table']}, column {d['column']}: {d['rows']} row(s)" for d in p.db_other]
    if p.elsewhere:
        lines.append(f"\nNot memory, so NOT erased by this command; the name is also in ({len(p.elsewhere)}):")
        lines += [f"  {path} ({'unreadable' if n < 0 else f'{n} time(s)'})" for path, n in p.elsewhere]
        lines.append("  A person deals with these by hand (see docs/DATA_LIFECYCLE.md).")
    if not p.empty():
        aliases = "".join(f" --alias {a!r}" for a in p.names[1:])
        lines.append(f"\nTo erase exactly this: python -m apolaki.engine erase-person {p.names[0]!r}{aliases} "
                     f"--confirm {p.code} --by WHO --reason WHY")
    return "\n".join(lines)
