"""Garuda in front of external input: every text Apolaki takes in from outside is screened before anything uses it.

    python -m apolaki.intake list                         # what is held and what was released
    python -m apolaki.intake show QID                     # one entry, text included
    python -m apolaki.intake release QID --by NAME [--note WHY]

screen(text, source, kind) runs Garuda's Layer 1 (vendored in apolaki/security/garuda: 32 patterns for known
injection phrasings, chat-template tokens and authority spoofing) on the text as it came and on its normalised form
(apolaki.security.normalize: invisible characters removed, look-alike letters folded), so "Ig<zero-width
space>nore previous instructions" is caught as well. When the text has HTML in it (Grants.gov synopses do), it is also
tasted as a reader sees it: comments and tags taken out, once as nothing ("Ig<b>nore</b>") and once as a space
("previous<br>instructions"), then entities decoded ("Ignore&nbsp;all"), each as it is and normalised. The raw text
is still tasted, so a chat-template token a reader's view would take out as a tag is caught there; and so is the raw
text with its entities decoded and its tags kept, and the tags' attribute values as text (as_raw), since the model
reads an attribute that a reader's view takes out ('<img alt="Ignore&nbsp;all previous instructions">'). Since round
A every view decodes entities and percent-encoding again and again until nothing changes ("&amp;nbsp;", "%2520",
"&#37;20"), so text escaped twice is read as a reader or a model would read it, and a text still changing after
DECODE_PASSES passes is held for a person (UNSETTLED); a tag left open at the end of the text is closed first, an
attribute value left open with it; and each tag is also read with its name and brackets taken out and its words kept
in place (as_words), so "Ignore all <b previous instructions", whose words a browser hides as a tag's, is caught.
Since round A2 a "+" is also read as a space, as a form's query string writes one (as_form:
"Ignore+all+previous+instructions"); a text is held as UNSETTLED when any view's decoding hasn't settled, not only the
raw text's (a tag can hide the nesting from the raw text); and the two expressions that read tags and attributes run in
time linear in the text's length (a long run of letters in a tag took seconds before).
  - A hit quarantines the text for a person: $APOLAKI_HOME/quarantine/q_<sha256 prefix>.json holds the text, its
    sources, its kind, the patterns that fired and when it was seen. The same text seen again is the same entry
    (seen_count, sources), so a listing re-read every night doesn't raise a new alarm each time. Each event is a line
    in quarantine/log.jsonl and a warning in the log.
  - The caller gets ok=False and passes the text on to nothing: not the model, not memory.
  - A person reads it and releases it (release()). A release is bound to the text's sha256: the same text is
    admitted from then on, with its flags still noted, and any change to it is screened afresh.

Where it runs: the agent screens every brief before its ethics check and before any model call (the deployed grant
hunt puts listing and funder-page text in its briefs); the MCP server screens every memory it is asked to store;
apolaki.grants.intake has the screens for a grant job's own sources (Grants.gov listings, funder pages, the calls a
model extracts from them); screen_discord() is for Discord input.

What it can't do:
  - catch an injection it has no pattern for. Layer 1 is a list of known phrasings: a paraphrase, another language,
    or an instruction split across texts screened separately gets through (apolaki.grants.intake.admit_listing
    screens all of a listing as one text, so a split inside one listing is seen). Garuda's second layer, an LLM
    judge, isn't vendored.
  - decode what it doesn't know: a backslash escape ("\\u0069nstructions"), base64, rot13, a Markdown link between
    the words, a tag left open anywhere but the end, or an instruction partly inside a <script> block.
  - tell discussion from attack. "jailbreak" in a call for AI-safety research is held like an attack, and a person
    releases it. Garuda's own design note: Layer 1 is deliberately aggressive, better to flag and release than miss.
  - screen text it isn't given. respond(), the interactive chat with the person at the keyboard, isn't screened.
    Nothing reads Discord into Apolaki today; a reader must call screen_discord() first. A grant job deployed before
    this package version doesn't call apolaki.grants.intake, so its own model calls (triage, extracting calls from a
    page) still see unscreened text; only what reaches Apolaki's drafting, through the brief, is screened.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import re
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .agent import config
from .security.garuda import layer1
from .security.normalize import normalize

logger = logging.getLogger("apolaki.intake")

MAX_SOURCES = 20        # an entry keeps its first 20 distinct sources; seen_count keeps counting past them


@dataclass
class Screened:
    ok: bool
    flags: list[str] = field(default_factory=list)
    quarantine_id: str | None = None
    released: bool = False
    sha256: str = ""


def quarantine_dir() -> Path:
    return config.home() / "quarantine"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _entry_path(qid: str) -> Path | None:
    if not re.fullmatch(r"q_[0-9a-f]{16}", qid or ""):
        return None
    return quarantine_dir() / f"{qid}.json"


def _log(event: str, qid: str, kind: str, source: str, flags: list[str]) -> None:
    q = quarantine_dir()
    q.mkdir(parents=True, exist_ok=True)
    with (q / "log.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _now(), "event": event, "id": qid, "kind": kind, "source": source, "flags": flags},
                           ensure_ascii=False) + "\n")


# HTML a reader doesn't see: a comment (to its end, or to the end of the text when it is left open), and a tag (one
# that starts with a letter, "/", "!" or "?": "<|im_start|>" is no tag, and stays in the reader's view).
_HTML_COMMENT = re.compile(r"<!--.*?(?:-->|\Z)", re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z!?][^<>]*>")


# Decoding can take more than one pass (round A): entities escaped twice ("&amp;nbsp;" is "&nbsp;", then a no-break
# space), percent-encoding applied twice ("%2520"), an entity that writes a percent escape ("&#37;20") or the other way
# round ("%26nbsp;"). Each pass that changes the text shortens it, so decoding settles; the cap bounds the work on a
# text nested deeper than any reader would decode, and such a text is held for a person (UNSETTLED), never admitted.
# That holds for every view's decoding, not only the raw text's (round A2): a tag can hide the nesting from the raw
# text ("&<b></b>amp;amp;..." decodes once there, and 17 times over once the reader's view takes the tag out).
DECODE_PASSES = 16
UNSETTLED = f"encoded more than {DECODE_PASSES} times over"


def _decode(text: str) -> tuple[str, bool]:
    """(the text with its HTML entities and percent-encoding decoded again and again until nothing changes, whether it
    settled within DECODE_PASSES)."""
    for _ in range(DECODE_PASSES):
        t = urllib.parse.unquote(html.unescape(text))
        if t == text:
            return text, True
        text = t
    return text, False


def _decoded(text: str, unsettled: list | None = None) -> str:
    """The text decoded (_decode); a text whose decoding didn't settle is added to unsettled, when it is given."""
    out, settled = _decode(text)
    if not settled and unsettled is not None:
        unsettled.append(text)
    return out


# A tag left open at the end of the text ("Ignore all <b previous instructions"): a browser drops it, words and all,
# while a model reads them. It is closed before the views below take tags out (round A): ">" added, after a quote
# that closes an attribute value left open ('<img alt="Ignore all" title="previous instructions').
_OPEN_TAG = re.compile(r"</?[A-Za-z!?][^<>]*\Z")


def _closed(text: str) -> str:
    m = _OPEN_TAG.search(text)
    if not m:
        return text
    return text + next((q for q in ('"', "'") if m.group().count(q) % 2), "") + ">"


def _encoded(text: str) -> bool:
    return "<" in text or "&" in text or "%" in text


def as_read(text: str, unsettled: list | None = None) -> list[str]:
    """The text as a reader of its HTML sees it: comments and tags taken out (a tag left open at the end closed first),
    as nothing and as a space (an inline tag joins a word, a line break or a paragraph separates two), then HTML
    entities and percent-encoding decoded until nothing changes. [] when that changes nothing. Tags go before entities
    are decoded, as a browser reads them: "&lt;b&gt;" is text, not a tag. Each of these views (as_read, as_words,
    as_raw, as_form) adds to unsettled, when it is given, each text whose decoding didn't settle (_decoded)."""
    if not _encoded(text):
        return []
    out, closed = [], _closed(text)
    for gap in ("", " "):
        seen = _decoded(_HTML_TAG.sub(gap, _HTML_COMMENT.sub(gap, closed)), unsettled)
        if seen != text and seen not in out:
            out.append(seen)
    return out


# A tag: its name, and what it holds after the name. The name is matched possessively (round A2): given back a letter
# at a time to what follows, a long name with no ">" after it took time quadratic in its length (15 s for 8,000
# letters); the name ends where the run does either way, so what matches is the same.
_TAG_PARTS = re.compile(r"</?[A-Za-z!?][^\s<>/]*+([^<>]*)>")


def as_words(text: str, unsettled: list | None = None) -> list[str]:
    """The text as a model reads the words inside its tags (round A): each tag's name and brackets taken out and what
    it holds kept in place, so "Ignore all <b previous instructions" (left open, then closed) reads "Ignore all
    previous instructions", which the reader's view loses whole. The same for the text decoded first, so a tag that
    entities or percent-encoding wrote ("&amp;lt;b&amp;gt;") is taken out too; each decoded until nothing changes,
    a tag taken as nothing and as a space. [] when that changes nothing."""
    if not _encoded(text):
        return []
    out = []
    for base in (_closed(text), _closed(_decoded(text, unsettled))):
        for gap in ("", " "):
            seen = _decoded(_TAG_PARTS.sub(lambda m: gap + m.group(1) + gap, base), unsettled)
            if seen != text and seen not in out:
                out.append(seen)
    return out


# An attribute and its value, quoted either way or not at all, inside a tag (_HTML_TAG). A name starts only where a run
# of name characters starts (the lookbehind), and is matched possessively (round A2): tried from every letter of a long
# run with no "=" after it, each try ran to the end of the run, so a scan took time quadratic in the run's length
# ('<a ' and 8,000 letters took 6.5 s). A match can't start inside a run anyway, since the run's end is the same.
_ATTRIBUTE = re.compile(r"""(?<![^\s"'<>/=])[^\s"'<>/=]++\s*+=\s*+(?:"([^"]*)"|'([^']*)'|([^\s"'<>=`]+))""")


def as_raw(text: str, unsettled: list | None = None) -> list[str]:
    """The text as a model reading its raw HTML sees it (round 4: the reader's view takes a whole tag out before it
    decodes entities, so '<img alt="Ignore&nbsp;all previous instructions">' was admitted): the text with its entities
    and percent-encoding decoded until nothing changes and its tags kept, and every tag's attribute values (a tag left
    open at the end closed first), decoded the same way, one after another as one text (so an instruction split
    between two attributes is whole). [] when that changes nothing."""
    if not _encoded(text):
        return []
    out = []
    decoded = _decoded(text, unsettled)
    if decoded != text:
        out.append(decoded)
    values = " ".join(_decoded(next(v for v in m.groups() if v is not None), unsettled)
                      for tag in _HTML_TAG.finditer(_closed(text)) for m in _ATTRIBUTE.finditer(tag.group()))
    if values and values not in out:
        out.append(values)
    return out


def as_form(text: str, unsettled: list | None = None) -> list[str]:
    """The text as a form's query string is read (round A2): "+" as a space (urllib.parse.unquote_plus), in the text as
    it came and in the text decoded ("%2B" is a "+"), then decoded until nothing changes, so
    "Ignore+all+previous+instructions", in an href or anywhere, is read as words. [] when the text has no "+" either
    way."""
    out = []
    for base in dict.fromkeys((text, _decoded(text, unsettled) if _encoded(text) else text)):
        if "+" in base:
            seen = _decoded(urllib.parse.unquote_plus(base), unsettled)
            if seen != text and seen not in out:
                out.append(seen)
    return out


def scan(text: str) -> list[str]:
    """Garuda Layer 1's patterns that fire on the text, on its normalised form, or on what a reader of its HTML sees
    (as_read), a model reading the raw HTML sees (as_raw, as_words) or a form's reader sees (as_form), each as it is and
    normalised, in the order found; and UNSETTLED when any view's decoding doesn't settle within DECODE_PASSES."""
    if not text:
        return []
    # The raw scan is kept so the screen never rests on normalize() alone. No text is known that it catches and the
    # normalised scan misses, so a mutant that drops it lives; that is why. The reader's view is tasted as it is too,
    # for the same reason, and a mutant that drops that lives as well (round 3). The text as it came (raw and
    # normalised) is what catches a tag-shaped injection such as "<system>", which the reader's view takes out.
    flags = layer1(text)
    unsettled: list[str] = []
    views = dict.fromkeys(as_read(text, unsettled) + as_raw(text, unsettled) + as_words(text, unsettled)
                          + as_form(text, unsettled))                                 # each view once
    for t in (normalize(text), *(v for seen in views for v in (seen, normalize(seen)))):
        flags += [p for p in layer1(t) if p not in flags]
    if unsettled:
        flags.append(UNSETTLED)
    return flags


def screen(text: str, source: str, kind: str) -> Screened:
    """Screen one outside text. ok=False means it is quarantined and must not be passed on (see the module)."""
    if not isinstance(text, str):
        raise TypeError(f"screen() takes text, not {type(text).__name__}")
    flags = scan(text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not flags:
        return Screened(ok=True, sha256=digest)
    qid = f"q_{digest[:16]}"
    path = _entry_path(qid)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entry = None
    if entry and entry.get("sha256") == digest and entry.get("released") is True:
        _log("admitted (released)", qid, kind, source, flags)
        return Screened(ok=True, flags=flags, quarantine_id=qid, released=True, sha256=digest)
    now = _now()
    if entry and entry.get("sha256") == digest:
        entry["seen_count"] = int(entry.get("seen_count", 1)) + 1
        entry["last_seen"] = now
        if source not in entry.get("sources", []) and len(entry.get("sources", [])) < MAX_SOURCES:
            entry.setdefault("sources", []).append(source)
        event = "seen again"
    else:
        entry = {"id": qid, "sha256": digest, "kind": kind, "sources": [source], "flags": flags, "first_seen": now,
                 "last_seen": now, "seen_count": 1, "released": False, "text": text}
        event = "quarantined"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    _log(event, qid, kind, source, flags)
    logger.warning("intake: %s %s from %s (%s): Garuda layer 1 matched %s", event, qid, source, kind, flags)
    return Screened(ok=False, flags=flags, quarantine_id=qid, sha256=digest)


def screen_discord(message: str, author: str, channel: str) -> Screened:
    """A Discord message, before anything reads it. Nothing reads Discord into Apolaki yet; a reader starts here."""
    return screen(message, source=f"discord:{channel}:{author}", kind="discord message")


def release(qid: str, by: str, note: str = "") -> dict:
    """A person read the entry and lets its exact text through from now on. Returns the entry."""
    if not by.strip():
        raise ValueError("say who is releasing it (by)")
    path = _entry_path(qid)
    try:
        entry = json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        entry = None
    if not entry:
        raise ValueError(f"there is no quarantined text {qid!r} in {quarantine_dir()}")
    entry.update(released=True, released_by=by.strip(), released_at=_now(), release_note=note.strip())
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    _log("released", qid, entry.get("kind", ""), f"by {by.strip()}", entry.get("flags", []))
    return entry


def entries() -> list[dict]:
    """Every entry, newest first (by when last seen)."""
    out = []
    for p in quarantine_dir().glob("q_*.json") if quarantine_dir().exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return sorted(out, key=lambda e: e.get("last_seen", ""), reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apolaki.intake", description="Apolaki's quarantine of outside text")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="what is held and what was released")
    s = sub.add_parser("show", help="one entry, with its text")
    s.add_argument("qid")
    r = sub.add_parser("release", help="let this exact text through from now on, after reading it")
    r.add_argument("qid")
    r.add_argument("--by", required=True)
    r.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.cmd == "list":
        rows = entries()
        if not rows:
            print("nothing quarantined")
        for e in rows:
            state = f"released by {e.get('released_by')}" if e.get("released") else "held"
            print(f"{e['id']}  {state}  {e.get('kind')}  seen {e.get('seen_count')}x, last {e.get('last_seen')}  "
                  f"from {', '.join(e.get('sources', [])[:3])}  flags: {len(e.get('flags', []))}")
        return 0
    try:
        if a.cmd == "show":
            path = _entry_path(a.qid)
            if not path or not path.exists():
                raise ValueError(f"there is no quarantined text {a.qid!r} in {quarantine_dir()}")
            print(path.read_text(encoding="utf-8"))
            return 0
        e = release(a.qid, a.by, a.note)
        print(f"{e['id']} released by {e['released_by']}: this exact text is admitted from now on")
        return 0
    except ValueError as e:
        print(f"not done: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
