"""python -m apolaki.grants: record a grant application's outcome, and summarise them (apolaki.grants.outcomes)."""
from __future__ import annotations

import argparse
import sys

from . import outcomes as o


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apolaki.grants")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("outcome", help="record what happened to an application (appended to grant-hunt/outcomes.jsonl)")
    r.add_argument("key", help="the listing's key in grant-hunt/seen.json")
    r.add_argument("outcome", choices=("applied", "awarded", "declined", "no_reply", "no-reply"))
    r.add_argument("--date", required=True, help="YYYY-MM-DD, the day it happened")
    r.add_argument("--by", required=True, help="who is recording it")
    r.add_argument("--reason", default="", help="the one primary reason, if known (needs --source)")
    r.add_argument("--source", default="", help="who or what gave the reason")
    r.add_argument("--confidence", default="", choices=("", "low", "high"), help="of the reason (default low)")
    r.add_argument("--note", default="")
    r.add_argument("--unlisted", action="store_true", help="an application the hunt never saw")
    s = sub.add_parser("outcomes", help="the summary, in counts with n")
    s.add_argument("--since", default=None, help="YYYY-MM-DD: applications whose latest record is on or after it")
    s.add_argument("--list", action="store_true", help="each application, its latest outcome and reason")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "outcome":
            rec = o.record(a.key, a.outcome.replace("-", "_"), a.date, a.by, reason=a.reason, source=a.source,
                           confidence=a.confidence, note=a.note, unlisted=a.unlisted)
            print(f"recorded: {rec['key']} {rec['outcome']} {rec['date']} ({o.outcomes_path()})")
            return 0
        if a.list:
            lines = o.listing()
            print("\n".join(lines) if lines else "no outcomes recorded")
            return 0
        print(o.summary_text(o.summary(a.since)))
        return 0
    except ValueError as e:              # a refusal: nothing was written
        print(f"not recorded: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
