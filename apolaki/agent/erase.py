"""Erase a person from Apolaki's memory, everywhere it lives (2026-11-02 review, item 14 and adoption 9).

    python -m apolaki.engine erase-person "NAME" [--alias "OTHER NAME" ...]
        a dry run: lists everything it would remove, and gives a code
    python -m apolaki.engine erase-person "NAME" [--alias ...] --confirm CODE --by WHO --reason WHY
        removes exactly what that dry run listed

Apolaki's memory keeps things by design: archive_memory() hides a memory but keeps its row and its embedding, and
store() pulls the names of people and organisations into an entity graph and wiki pages that archiving never
touches. That is right for Apolaki's own beliefs and wrong for personal data about third parties. This is the one
path that deletes. It is a command a person runs; the MCP server has no erase tool.

What it removes, for the name and each alias (whole words; case, accents and look-alike letters folded, so "María
López" also finds "maria lopez"):
  - every memory whose text, tags or source names the person, archived ones included, each with its embedding (the
    row's blob and its vector-index entry);
  - the person's entity rows (an entity whose name contains the person's, such as "Dr. María López", counts), every
    mention row and triple that touches them or an erased memory, and every other entity left with no memory behind
    it, since it came only from what was erased;
  - the person's wiki page, file and row; every other page that names them, or belongs to an erased entity, is
    rebuilt from what remains or removed when nothing remains to rebuild it from;
  - the engine's beliefs that name the person, logged as removed without the name; and the person's name in the
    engine's belief log, replaced by "[erased]".
Then it rebuilds the vector indexes from what remains, VACUUMs the database (with secure_delete on) and truncates its
write-ahead log. Its check reads back every byte of the database files (folding case, accents, look-alike letters
and the common invisible characters, and looking for the erased embeddings), the wiki folder and the engine's belief
files, and runs the dry run again: if the name or an erased embedding is still there, that is an error, never a
success.

The dry run gives a code, a hash of exactly what it found. The erase runs only with that code, so what is removed is
what a person read; if anything changed in between, the code doesn't match and nothing is removed. Each erase is
recorded in $APOLAKI_HOME/erasures.jsonl: who, why, when and how much, never the name.

What it can't do:
  - find the person by anything but the name and aliases given. A nickname, initials, a pronoun, a role ("our board
    chair") or a misspelling isn't found; list such variants as aliases, and read what each finds in the dry run.
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


class EraseError(RuntimeError):
    """The erase was refused (nothing removed), or its check found something left (said where)."""


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


def _fold_bytes(raw: bytes) -> str:
    t = _untag(raw.decode("utf-8", errors="ignore"))
    t = _straighten(_COMMON_INVISIBLE.sub("", t))
    t = _unlook(_COMBINING.sub("", unicodedata.normalize("NFKD", t)))
    return t.casefold()


def _matcher(names: list[str]) -> re.Pattern:
    parts = []
    for n in names:
        tokens = _fold(n).split()
        if not tokens or len("".join(tokens)) < MIN_NAME_CHARS:
            raise EraseError(f"{n!r} is too short to erase by: give a name of at least {MIN_NAME_CHARS} letters")
        parts.append(r"\s+".join(re.escape(t) for t in tokens))
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)")


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
    vec_tables: list[str] = field(default_factory=list)
    code: str = ""

    def counts(self) -> dict:
        return {"memories": len(self.memories), "entities": len(self.entities), "mentions": len(self.mentions),
                "triples": len(self.triples), "wiki_pages": len(self.wiki_pages), "wiki_files": len(self.wiki_files),
                "beliefs": len(self.beliefs), "belief_log_lines": self.belief_log_lines}

    def empty(self) -> bool:
        return not any(self.counts().values())


def _paths(home: Path) -> dict:
    db = home / "db" / "apolaki.db"
    return {"db": db, "wal": Path(str(db) + "-wal"), "shm": Path(str(db) + "-shm"), "wiki": home / "wiki",
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
    con = sqlite3.connect(str(db), timeout=30)
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
        return any(hit.search(_fold(t)) for t in texts if t)

    if p["db"].is_file():
        con, out.vec_tables = _open(p["db"], readonly=True)
        try:
            ents = {r[0]: r for r in con.execute("SELECT id, name, entity_type FROM kg_entities")}
            person = {eid for eid, r in ents.items() if named(r[1])}
            mems = []
            # Every memory the graph links to the person names them in its text (an entity is taken from the text),
            # so the text match finds those too.
            for mid, content, tags, source, archived in con.execute(
                    "SELECT id, content, tags, source, archived FROM memories ORDER BY created_at"):
                if named(content, tags, source):
                    mems.append({"id": mid, "archived": bool(archived), "text": content})
            erased_mem = {m["id"] for m in mems}
            mention_rows = con.execute("SELECT id, entity_id, memory_id FROM kg_entity_mentions").fetchall()
            gone_mentions = {r[0] for r in mention_rows if r[1] in person or r[2] in erased_mem}
            # an entity whose every mention goes with the erased memories came only from them
            remaining = {}
            for mid_, eid, memid in mention_rows:
                remaining.setdefault(eid, 0)
                remaining[eid] += mid_ not in gone_mentions
            orphans = {eid for eid, left in remaining.items() if left == 0 and eid not in person}
            gone_ents = person | orphans
            out.entities = [{"id": eid, "name": ents[eid][1], "type": ents[eid][2],
                             "why": "names the person" if eid in person else "only in erased memories"}
                            for eid in sorted(gone_ents, key=lambda e: ents[e][1].lower()) if eid in ents]
            out.memories = mems
            out.mentions = sorted(gone_mentions)
            out.triples = sorted(r[0] for r in con.execute(
                "SELECT id, subject_entity_id, object_entity_id, source_memory_id FROM kg_triples")
                if r[1] in gone_ents or r[2] in gone_ents or r[3] in erased_mem)
            gone_names = {ents[e][1].lower() for e in gone_ents if e in ents}
            kept = {r[1] for e, r in ents.items() if e not in gone_ents}           # as written: page titles keep case
            kept_names = {n.lower() for n in kept}
            for (title, content) in con.execute("SELECT title, content FROM wiki_pages ORDER BY title"):
                if title.lower() in gone_names or named(title):
                    out.wiki_pages.append({"title": title, "action": "remove"})
                elif named(content) or any(n in (content or "").lower() for n in gone_names):
                    out.wiki_pages.append({"title": title, "action": "rebuild" if title.lower() in kept_names
                                           else "remove"})
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
            text = _fold_bytes(f.read_bytes())
        except OSError:
            out.elsewhere.append((str(f.relative_to(home)), -1))
            continue
        n = len(hit.findall(text))
        if n:
            out.elsewhere.append((str(f.relative_to(home)), n))

    ident = {"names": [_fold(n) for n in names], "memories": [m["id"] for m in out.memories],
             "entities": [e["id"] for e in out.entities], "mentions": out.mentions, "triples": out.triples,
             "wiki_pages": out.wiki_pages, "wiki_files": out.wiki_files, "beliefs": out.beliefs,
             "belief_log_lines": out.belief_log_lines}
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
    """Where the name, or one of the given embeddings, can still be read; [] when nowhere. Three checks:
    the bytes of the database, its write-ahead log and shared-memory file (a fast fold: see _fold_bytes), where the
    embeddings are looked for too; the wiki folder and the engine's belief files, with the full fold; and a second
    dry run, which reads every row with the full fold and must find nothing."""
    hit = _matcher(names)
    p = _paths(home)
    found = []
    for f in (p["db"], p["wal"], p["shm"]):
        try:
            raw = f.read_bytes()
        except FileNotFoundError:
            continue
        if hit.search(_fold_bytes(raw)):
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
        if hit.search(_fold(text)) or (p["wiki"] in f.parents and hit.search(_fold(f.name.replace("_", " ")))):
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
    names = p.names
    hit = _matcher(names)
    paths = _paths(home)
    blobs: list[bytes] = []
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
            con.execute("VACUUM")
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
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
            if not hit.search(_fold(line)):
                out.append(line)
                continue
            try:
                row = json.loads(line)
                row = {k: (REDACTED if isinstance(v, str) and hit.search(_fold(v)) else v) for k, v in row.items()}
                out.append(json.dumps(row, ensure_ascii=False))
            except ValueError:
                out.append(json.dumps({"kind": REDACTED}))
        tmp = paths["belief_log"].with_suffix(".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        tmp.replace(paths["belief_log"])
    if p.beliefs:
        from .. import learning
        learning.log_removed([{"id": b, "source": REDACTED} for b in p.beliefs], by="erase-person", redact=REDACTED)

    left = leftovers(names, home, blobs)
    record = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "by": by.strip(),
              "reason": reason.strip(), "code": p.code, "counts": p.counts(), "verified": not left,
              "other_files_naming_them": len(p.elsewhere)}
    if hit.search(_fold(record["reason"])) or hit.search(_fold(record["by"])):
        record["reason" if hit.search(_fold(record["reason"])) else "by"] = REDACTED
    with paths["ledger"].open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    if left:
        raise EraseError("the erase ran, but its check still reads the name or an erased embedding in: "
                         + "; ".join(left))
    return {"code": p.code, "counts": p.counts(), "elsewhere": p.elsewhere, "ledger": str(paths["ledger"])}


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
    if p.elsewhere:
        lines.append(f"\nNot memory, so NOT erased by this command; the name is also in ({len(p.elsewhere)}):")
        lines += [f"  {path} ({'unreadable' if n < 0 else f'{n} time(s)'})" for path, n in p.elsewhere]
        lines.append("  A person deals with these by hand (see docs/DATA_LIFECYCLE.md).")
    if not p.empty():
        aliases = "".join(f" --alias {a!r}" for a in p.names[1:])
        lines.append(f"\nTo erase exactly this: python -m apolaki.engine erase-person {p.names[0]!r}{aliases} "
                     f"--confirm {p.code} --by WHO --reason WHY")
    return "\n".join(lines)
