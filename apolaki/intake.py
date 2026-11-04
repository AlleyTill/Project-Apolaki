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
is still tasted, so a chat-template token a reader's view would take out as a tag is caught there.
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


def as_read(text: str) -> list[str]:
    """The text as a reader of its HTML sees it: comments and tags taken out, as nothing and as a space (an inline tag
    joins a word, a line break or a paragraph separates two), then HTML entities decoded. [] when that changes
    nothing. Tags go before entities are decoded, as a browser reads them: "&lt;b&gt;" is text, not a tag."""
    if "<" not in text and "&" not in text:
        return []
    out = []
    for gap in ("", " "):
        seen = html.unescape(_HTML_TAG.sub(gap, _HTML_COMMENT.sub(gap, text)))
        if seen != text and seen not in out:
            out.append(seen)
    return out


def scan(text: str) -> list[str]:
    """Garuda Layer 1's patterns that fire on the text, on its normalised form, or on what a reader of its HTML sees
    (as_read, as it is and normalised), in the order found."""
    if not text:
        return []
    # The raw scan is kept so the screen never rests on normalize() alone. No text is known that it catches and the
    # normalised scan misses, so a mutant that drops it lives; that is why. The text as it came (raw and normalised)
    # is what catches a tag-shaped injection such as "<system>", which the reader's view takes out.
    flags = layer1(text)
    for t in (normalize(text), *(v for seen in as_read(text) for v in (seen, normalize(seen)))):
        flags += [p for p in layer1(t) if p not in flags]
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
