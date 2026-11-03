"""The screens a grant job runs on what it fetches, before any of it reaches a model (apolaki.intake, Garuda Layer 1).

A grant job takes in three kinds of outside text, and each goes through one of these first:
  - a Grants.gov listing: the search hit (its title, agency, dates) and the details fetched for it (synopsis,
    eligibility, the applicant types list, award, agency), both of which triage reads:
    admit_listing(key, {"hit": hit, "details": details});
  - a funder's page, as fetched, before a model reads it to list its calls: admit_page(url, text);
  - a call a model extracted from a page (the model read outside text, so its answer is outside text too):
    admit_listing(key, call, kind="watchlist call").
Each returns what it was given when every text in it is clean (or a person released it), and None when something in
it was quarantined: the job then leaves that listing or page out of triage, extraction and drafting, and a person
finds it with `python -m apolaki.intake list`.

The job itself lives with each deployment and has to call these; a job deployed before this package version
doesn't. Until it does, the only screen its outside text meets is the one on Apolaki's briefs (ApolakiAgent
.draft_content), which comes after the job's own triage and extraction calls. What Layer 1 can't catch is in
apolaki.intake.
"""
from __future__ import annotations

from .. import intake


def _strings(value, values: list, keys: list) -> None:
    """Every string in a JSON-shaped value, at any depth and in order: values into values, dict keys into keys."""
    if isinstance(value, str):
        if value.strip():
            values.append(value)
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str) and k.strip():
                keys.append(k)
            _strings(v, values, keys)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _strings(v, values, keys)
    elif value is not None and not isinstance(value, (bool, int, float)):
        raise TypeError(f"admit_listing takes JSON-shaped data (strings, numbers, lists, dicts), not "
                        f"{type(value).__name__}: decode it to text first, so the screen can read it")


def admit_listing(key: str, listing: dict, kind: str = "grants.gov listing") -> dict | None:
    """The listing, unchanged, when its text is clean; None when it was quarantined.

    Every string in it is screened, at any depth: a list such as fetch()'s applicant types, a dict inside it, the
    search hit and the details side by side ({"hit": hit, "details": details}, as docs/GRANT_JOB_HOOKS.md says). The
    strings are screened as one text, joined by line breaks, so a pattern that fires inside one fires inside the
    whole, and an instruction split across two fields or list items ("...ignore all previous" / "instructions
    and...") is seen whole; the whole is what a person reads in the quarantine (a flat listing's is its fields
    joined, as before, so a release made before still holds). The dict keys are screened too, as a second text
    (kind "... (field names)"): a call a model extracted is JSON the model chose, keys included. Numbers, booleans and
    None carry no text; any other type is refused (TypeError) rather than skipped unread."""
    values: list[str] = []
    keys: list[str] = []
    _strings(listing, values, keys)
    ok = intake.screen("\n".join(values), source=key, kind=kind).ok
    if keys:
        ok = intake.screen("\n".join(keys), source=key, kind=f"{kind} (field names)").ok and ok
    return listing if ok else None


def admit_page(url: str, text: str) -> str | None:
    """A funder page's text, unchanged, when clean; None when it was quarantined."""
    return text if intake.screen(text, source=url, kind="funder page").ok else None
