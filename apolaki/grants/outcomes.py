"""What happened to each grant application: a log a person fills in beside the grant hunt's seen-list, and a summary in
counts with n (2026-11-02 review, adoption 8: nothing recorded which applications were submitted, funded or
declined, or why).

    python -m apolaki.grants outcome KEY applied --date 2026-11-01 --by NAME
    python -m apolaki.grants outcome KEY declined --date 2026-12-15 --by NAME --reason WHY --source WHERE
    python -m apolaki.grants outcomes [--since 2026-10-01]      # the summary
    python -m apolaki.grants outcomes --list                    # each application, its state and reason

The log is $APOLAKI_HOME/grant-hunt/outcomes.jsonl, one JSON line per record, only ever appended to. An
application's state is its latest record, so a correction is a new record. Outcomes: applied, awarded, declined,
no_reply. KEY is the listing's key in the hunt's seen.json (a Grants.gov number, or a "watch:" key for a funder
page); an application the hunt never saw is recorded with unlisted=True (--unlisted).

The method follows the win-loss analysis in sales-enablement (coreyhaines31/marketingskills, MIT, at 88c79f6),
rewritten here rather than copied:
  - one primary reason per outcome, and no reason without its source (who or what said so);
  - a reason is low confidence unless the person recording it says high;
  - counts, never percentages: "2 of 7" says how much to trust it;
  - under 5 decided outcomes is a signal to watch, not a finding.

What it doesn't do: fetch anything, or learn. Nothing reads this log into triage or into learning; a test fails if
any other module of the package reads it. If outcomes are ever to shape triage or drafts, that feed goes under the
learning switch and its caps (apolaki.learning), and it is Thomas's decision first.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from ..agent import config

OUTCOMES = ("applied", "awarded", "declined", "no_reply")
DECIDED = ("awarded", "declined")
CONFIDENCE = ("low", "high")
WATCH_UNDER = 5          # the method's own line: under about five cases is a signal to watch, not a finding


def outcomes_path() -> Path:
    return config.home() / "grant-hunt" / "outcomes.jsonl"


def seen_path() -> Path:
    return config.home() / "grant-hunt" / "seen.json"


def _seen() -> dict:
    path = seen_path()
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise ValueError(f"there is no {path} to check the key against; for an application the hunt never saw, "
                         f"record it as unlisted (--unlisted)") from None
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} can't be read ({type(e).__name__}); fix it, or record the application as "
                         f"unlisted (--unlisted)") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path} isn't the hunt's seen-list (a JSON object)")
    return data


def _day(text: str) -> str:
    try:      # fromisoformat alone also takes "20261020" and "2026-W43-2"; the log keeps one form
        d = date.fromisoformat(text) if isinstance(text, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None
    except ValueError:
        d = None
    if d is None:
        raise ValueError(f"the date must be YYYY-MM-DD, not {text!r}")
    if d > date.today():
        raise ValueError(f"{text} is in the future: record an outcome on or after the day it happened")
    return d.isoformat()


def record(key: str, outcome: str, date: str, by: str, reason: str = "", source: str = "", confidence: str = "",
           note: str = "", unlisted: bool = False) -> dict:
    """Append one outcome. Raises ValueError, writing nothing, when a rule is broken. Returns the record."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, not {outcome!r}")
    day = _day(date)
    if not by.strip():
        raise ValueError("say who is recording it (by)")
    reason, source = reason.strip(), source.strip()
    if reason and not source:
        raise ValueError("no reason without a source: say who or what gave the reason (--source)")
    if source and not reason:
        raise ValueError("a source with no reason: give the reason it's the source for (--reason)")
    if confidence and confidence not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {CONFIDENCE}, not {confidence!r}")
    key = key.strip()
    if not key:
        raise ValueError("say which application (the listing's key in seen.json)")
    if not unlisted and key not in _seen():
        raise ValueError(f"{key!r} is not in {seen_path()}; for an application the hunt never saw, record it as "
                         f"unlisted (--unlisted)")
    rec = {"key": key, "outcome": outcome, "date": day, "by": by.strip(),
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if reason:
        rec.update(reason=reason, source=source, confidence=confidence or "low")
    if note.strip():
        rec["note"] = note.strip()
    if unlisted:
        rec["unlisted"] = True
    path = outcomes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _read() -> tuple[dict[str, dict], int]:
    """(each application's latest record, in the order first recorded; how many non-empty lines couldn't be read)."""
    out: dict[str, dict] = {}
    unreadable = 0
    try:
        lines = outcomes_path().read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return out, 0
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            rec = None
        if isinstance(rec, dict) and rec.get("outcome") in OUTCOMES and rec.get("key") and isinstance(rec.get("date"), str):
            out[rec["key"]] = rec
        else:
            unreadable += 1
    return out, unreadable


def latest() -> dict[str, dict]:
    """Each application's latest record, in the order first recorded."""
    return _read()[0]


def summary(since: str | None = None) -> dict:
    """Counts of each application's latest outcome. since (YYYY-MM-DD) keeps the applications whose latest record is
    dated on or after it."""
    if since is not None:
        since = _day(since)
    state, unreadable = _read()
    apps = [r for r in state.values() if since is None or r["date"] >= since]
    counts = {o: sum(1 for r in apps if r["outcome"] == o) for o in ("awarded", "declined", "no_reply", "applied")}
    reasons: dict[str, dict[str, list]] = {o: {} for o in DECIDED}       # outcome -> reason -> [(source, confidence)]
    for r in apps:
        if r["outcome"] in DECIDED and r.get("reason"):
            reasons[r["outcome"]].setdefault(r["reason"], []).append((r.get("source", ""), r.get("confidence", "low")))
    no_reason = sum(1 for r in apps if r["outcome"] in DECIDED and not r.get("reason"))
    return {"n": len(apps), "counts": counts, "decided": counts["awarded"] + counts["declined"], "reasons": reasons,
            "no_reason": no_reason, "since": since, "unreadable": unreadable}


def summary_text(s: dict) -> str:
    n, c = s["n"], s["counts"]
    where = outcomes_path().name + (f", since {s['since']}" if s.get("since") else "")
    if n == 0:
        return f"Grant outcomes ({where}): no outcomes recorded."
    lines = [f"Grant outcomes ({where}): n = {n} application{'s' if n != 1 else ''}",
             f"  awarded {c['awarded']} of {n}; declined {c['declined']} of {n}; no reply {c['no_reply']} of {n}; "
             f"still waiting {c['applied']} of {n}"]
    d = s["decided"]
    lines.append(f"  of the {d} decided, {c['awarded']} awarded and {c['declined']} declined")
    if d < WATCH_UNDER:
        lines.append(f"  Under {WATCH_UNDER} decided: a signal to watch, not a finding.")
    for outcome in DECIDED:
        for reason, given in sorted(s["reasons"][outcome].items(), key=lambda kv: (-len(kv[1]), kv[0])):
            sources = "; ".join(f"{source} ({conf} confidence)" for source, conf in given)
            lines.append(f"  {outcome}: {reason} ({len(given)}); source{'s' if len(given) != 1 else ''}: {sources}")
    if s["no_reason"]:
        lines.append(f"  {s['no_reason']} decided outcome{'s have' if s['no_reason'] != 1 else ' has'} no reason on "
                     f"record")
    if s.get("unreadable"):
        lines.append(f"  {s['unreadable']} line(s) of {outcomes_path().name} couldn't be read and aren't counted")
    return "\n".join(lines)


def listing() -> list[str]:
    """One line per application: key, title (from seen.json when it's there), latest outcome and date, reason."""
    try:
        seen = json.loads(seen_path().read_text())
        seen = seen if isinstance(seen, dict) else {}
    except (OSError, ValueError):
        seen = {}
    out = []
    for key, r in latest().items():
        title = (seen.get(key) or {}).get("title", "") if isinstance(seen.get(key), dict) else ""
        line = f"{key}  {r['outcome']} {r['date']}" + (f"  {title}" if title else "") + (" (unlisted)" if r.get(
            "unlisted") else "")
        if r.get("reason"):
            line += f"  | {r['reason']} (source: {r['source']}; {r.get('confidence', 'low')})"
        out.append(line)
    return out
