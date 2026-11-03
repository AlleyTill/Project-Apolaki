"""The STOP file: how a person stops Apolaki's scheduled work (the nightly grant hunt) between one step and the next.

    python -m apolaki.stop now "WHY" --by NAME     # or: touch "$APOLAKI_HOME/STOP"
    python -m apolaki.stop status                   # exit 1 while stopped
    python -m apolaki.stop clear                    # or: rm "$APOLAKI_HOME/STOP"

While $APOLAKI_HOME/STOP exists, in any form (empty, unreadable, even a folder: a STOP made in a hurry still stops):
  - check(step) raises StopRequested. A job calls it before each step, so it stops at the next one.
  - ApolakiEngine.draft calls check("draft") first, so no draft starts and nothing is learned, from any caller.

What it can't do (docs/STOPPING.md has the whole procedure, including what stops the job today):
  - stop a step already running: a model call in flight finishes or times out first;
  - stop a job that never calls check(). A job deployed before this file existed checks nothing itself; it reaches
    the engine's check only when it drafts, and its other steps (searching, triage, posting) go on;
  - hold anything after the file is removed: removing it is how a person resumes.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from .agent import config

STOP_NAME = "STOP"


class StopRequested(RuntimeError):
    """A person asked Apolaki's scheduled work to stop. Carries the step that was refused and the file's reason."""

    def __init__(self, step: str, reason: str, path: Path):
        self.step, self.reason, self.path = step, reason, path
        super().__init__(f"stopped before {step!r}: {path} exists ({reason}). Nothing more runs until a person removes "
                         f"it: python -m apolaki.stop clear")


def stop_path() -> Path:
    """$APOLAKI_HOME/STOP, read from the environment each time (never cached at import)."""
    return config.home() / STOP_NAME


def stop_reason() -> str | None:
    """Why the work is stopped, or None when it isn't. Any STOP counts; one that can't be read still stops."""
    path = stop_path()
    if not (path.exists() or path.is_symlink()):
        return None
    try:
        text = path.read_text(errors="replace").strip()
    except OSError as e:                     # a folder, no permission, a dangling link: stopped all the same
        return f"the file can't be read ({type(e).__name__}), so it stops anyway"
    return " ".join(text.split())[:300] or "no reason given"


def check(step: str) -> None:
    """Raise StopRequested if a person has asked the work to stop. Call it before each step."""
    reason = stop_reason()
    if reason is not None:
        raise StopRequested(step, reason, stop_path())


def request(reason: str, by: str) -> Path:
    """Write the STOP file, saying why and who. Returns its path."""
    if not reason.strip():
        raise ValueError("say why: the next person to find the STOP file needs to know")
    if not by.strip():
        raise ValueError("say who is stopping it")
    path = stop_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{reason.strip()} (by {by.strip()}, {datetime.now(timezone.utc).isoformat(timespec='seconds')})\n")
    return path


def clear() -> bool:
    """Remove the STOP file. True if there was one."""
    path = stop_path()
    if path.is_dir() and not path.is_symlink():
        path.rmdir()
        return True
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apolaki.stop", description="Stop or resume Apolaki's scheduled work")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="say whether the work is stopped (exit 1 while it is)")
    n = sub.add_parser("now", help="stop it before its next step")
    n.add_argument("reason")
    n.add_argument("--by", required=True)
    sub.add_parser("clear", help="remove the STOP file, so the work resumes at its next run")
    a = ap.parse_args(argv)
    if a.cmd == "now":
        print(f"STOPPED: {request(a.reason, a.by)} written. A step already running finishes first; see docs/STOPPING.md")
        return 0
    if a.cmd == "clear":
        print(f"{stop_path()} removed" if clear() else f"there was no {stop_path()}")
        return 0
    reason = stop_reason()
    if reason is None:
        print(f"not stopped: no {stop_path()}")
        return 0
    print(f"STOPPED: {stop_path()} ({reason})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
