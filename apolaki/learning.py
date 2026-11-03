"""Learning's safeguards, held by the engine for every caller (2026-11-02 review, item 17).

Learning is reviewers' recorded decisions (agent.review_item) becoming the engine's beliefs and reaching the model, as
a reference block, with the next brief of that content type. It is off by default (ApolakiEngine(learn=False); see
engine.py for why). Until 2026-11-02 the safeguards below lived only in the grant hunt, so
`python -m apolaki.engine draft --learn` learned with none of them. The engine now applies them to every belief it
forms, from a draft with learn=True and from `sync`:

  switch       $APOLAKI_HOME/grant-hunt/learning.json, the file the grant hunt has read since 10-19, so one file holds
               the decision and the limits for every caller. When it is there, a draft learns only if it says
               {"on": true}, and its daily_cap and total_ceiling set the limits. When it can't be read (not JSON, not
               an object, a limit that isn't a whole number from 0 up) nothing is learned, by a draft or by sync.
               When it is absent, learn=True is the caller's own explicit choice (the grant hunt never passes it
               without its switch on) and the default limits hold.
  pause        $APOLAKI_HOME/grant-hunt/learning.paused (the grant hunt's pause file): while it exists no belief is
               formed and none reaches the model. Reaching a limit writes it; only a person removes it.
  daily cap    beliefs added or changed today, counted from the belief log, may not pass daily_cap. Removals don't
               count: unlearning is a reviewer's call.
  ceiling      beliefs in all may not pass total_ceiling.
  over a limit the run's new beliefs are held back: logged as "held back: added", never added, never shown to the
               model, and the pause is written. Fail closed: the excess is never used.
  belief log   $APOLAKI_HOME/engine_beliefs_log.jsonl: every belief the engine adds, holds back or removes, with its
               source and day, flagged when it reads as a goal.
  Butlin watch a draft must not change Apolaki's memory: the memories, kg_triples and wiki_pages tables are counted
               before and after it. Nor may the beliefs change while the agent drafts (the engine's own logged
               learning comes first). A failure is in the draft result's "watch", and the engine CLI exits 1.

What it can't do:
  - tell anyone. A pause is a file and a log line; the grant hunt's channel and bus notices are the grant hunt's.
  - log learning that isn't the engine's. A belief file edited by hand or by another program is caught only by the
    watch, and only during a draft.
  - judge a belief. The goal flag is a word list; a person reads the log.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from .agent import config

# The cap and ceiling are safety stops on belief changes, not resource limits. There was nothing to measure them
# against when the grant hunt set them (10-19: no reviewer decision had ever been recorded), so they start tight
# (Thomas 10-13: with no data, ship the tighter default) and a person loosens them in the switch file once decisions
# exist. These are the grant hunt's own numbers (its LEARNING_DEFAULTS).
DEFAULT_LIMITS = {"daily_cap": 5, "total_ceiling": 25}
WATCHED_TABLES = ("memories", "kg_triples", "wiki_pages")
GOAL_WORDS = re.compile(r"(?i)\b(goals?|targets?|strateg\w*|performance|pursue\w*|itself|apolaki)\b")


class LearningRefused(RuntimeError):
    """No belief may be formed now: learning is paused, or the switch file can't be read."""


def switch_path() -> Path:
    return config.home() / "grant-hunt" / "learning.json"


def pause_path() -> Path:
    return config.home() / "grant-hunt" / "learning.paused"


def log_path() -> Path:
    return config.home() / "engine_beliefs_log.jsonl"


def today() -> str:
    return datetime.now().date().isoformat()


def _read_switch() -> tuple[dict | None, str | None]:
    """(the switch's contents or None when there is no file, the problem with it or None)."""
    path = switch_path()
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return None, None
    except OSError as e:
        return None, f"{path} can't be read ({type(e).__name__})"
    try:
        cfg = json.loads(raw)
    except ValueError:
        return None, f"{path} isn't JSON"
    if not isinstance(cfg, dict):
        return None, f"{path} isn't a JSON object"
    for key in DEFAULT_LIMITS:
        if key in cfg and (type(cfg[key]) is not int or cfg[key] < 0):
            return None, f"{path}: {key} must be a whole number from 0 up, not {cfg[key]!r}"
    return cfg, None


def limits() -> dict:
    """The daily cap and the total ceiling in force. Raises LearningRefused when the switch file can't be read."""
    cfg, problem = _read_switch()
    if problem:
        raise LearningRefused(f"nothing is learned while {problem}")
    return {key: (cfg or {}).get(key, value) for key, value in DEFAULT_LIMITS.items()}


def why_not(draft: bool = True) -> str | None:
    """Why no belief may be formed now, or None. draft=True also honours the switch's "on" when the file is there
    (sync, which a person runs to record decisions, needs only the pause and a readable switch)."""
    pause = pause_path()
    if pause.exists():
        return f"learning is paused: {pause} exists; a person reads {log_path()} and removes it"
    cfg, problem = _read_switch()
    if problem:
        return f"nothing is learned while {problem}"
    if draft and cfg is not None and cfg.get("on") is not True:
        return f'the switch at {switch_path()} doesn\'t say {{"on": true}}'
    return None


def _todays_changes(day: str) -> int:
    try:
        lines = log_path().read_text().splitlines()
    except FileNotFoundError:
        return 0
    n = 0
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        n += row.get("day") == day and row.get("kind") in ("added", "changed")
    return n


def _log(rows: list[dict], kind: str, by: str, day: str, redact: str | None = None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            content = redact if redact is not None else r.get("content")
            f.write(json.dumps({"at": now, "day": day, "kind": kind, "id": r.get("id"), "source": r.get("source"),
                                "by": by, "content": content,
                                "flagged": bool(GOAL_WORDS.search(str(content or "")))}, ensure_ascii=False) + "\n")


def pause(reason: str) -> Path:
    """Write the pause (fail closed: learning holds until a person removes the file)."""
    path = pause_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"paused_at": datetime.now().isoformat(timespec="seconds"), "reason": reason,
                                "by": "apolaki.engine"}, indent=1))
    return path


def admit(new_rows: list[dict], total_before: int, by: str, day: str | None = None) -> dict:
    """May these new beliefs be added? Logs each one, as added or held back, and writes the pause when they would pass
    the daily cap or the total ceiling. Returns {"admitted", "over", "added", "held_back"}; the caller adds them only
    when admitted. Raises LearningRefused when the switch file can't be read."""
    if not new_rows:
        return {"admitted": True, "over": None, "added": 0, "held_back": 0}
    lim = limits()
    day = day or today()
    new_today = _todays_changes(day) + len(new_rows)
    total = total_before + len(new_rows)
    over = (f"{new_today} new or changed beliefs today, over the daily cap of {lim['daily_cap']}"
            if new_today > lim["daily_cap"] else
            f"{total} beliefs in all, over the ceiling of {lim['total_ceiling']}" if total > lim["total_ceiling"]
            else None)
    _log(new_rows, "held back: added" if over else "added", by, day)
    if over:
        pause(f"{over}; this run's {len(new_rows)} new belief(s) held back in {log_path().name}, none added")
        return {"admitted": False, "over": over, "added": 0, "held_back": len(new_rows)}
    return {"admitted": True, "over": None, "added": len(new_rows), "held_back": 0}


def log_removed(rows: list[dict], by: str, redact: str | None = None) -> None:
    """Log beliefs the engine removed (they don't count toward the cap). redact replaces their text in the log."""
    if rows:
        _log(rows, "removed", by, today(), redact=redact)


# ---- the Butlin watch ------------------------------------------------------------------------------------------
def memory_counts(db_path: Path) -> dict | None:
    """Row counts of the watched tables; all zero when there is no database; None when it can't be read.

    Not mode=ro: a read-only open of a WAL database fails while its -shm file is absent, and immutable=1 would skip
    rows still in the WAL, the very writes this exists to catch (the grant hunt's finding, 10-06). query_only blocks
    writes from this connection instead."""
    if not db_path.is_file():
        return {t: 0 for t in WATCHED_TABLES}
    try:
        # waits up to 30 s for a writer's lock, as the grant hunt's count does; a count that can't be taken is
        # reported as such, never guessed
        con = sqlite3.connect(str(db_path), timeout=30)
        try:
            con.execute("PRAGMA query_only = 1")
            have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in have else 0
                    for t in WATCHED_TABLES}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def beliefs_fingerprint(path: Path) -> str | None:
    """The belief file's sha256 ("absent" when there is none); None when it can't be read."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "absent"
    except OSError:
        return None


def butlin_failures(mem_before, mem_after, beliefs_before, beliefs_after) -> list[str]:
    """What the watch found wrong across one draft; [] when nothing."""
    failures = []
    if mem_before is None or mem_after is None:
        failures.append("Apolaki's memory could not be counted")
    elif mem_after != mem_before:
        changed = ", ".join(f"{t} {mem_before[t]}→{mem_after[t]}" for t in WATCHED_TABLES
                            if mem_after[t] != mem_before[t])
        failures.append(f"Apolaki's memory changed during the draft ({changed}); a draft must not write to it")
    if beliefs_before is None or beliefs_after is None:
        failures.append("the engine's beliefs could not be read")
    elif beliefs_after != beliefs_before:
        failures.append("the engine's beliefs changed during the draft, outside the engine's own logged learning")
    return failures
