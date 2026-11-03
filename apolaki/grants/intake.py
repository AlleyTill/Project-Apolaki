"""The screens a grant job runs on what it fetches, before any of it reaches a model (apolaki.intake, Garuda Layer 1).

A grant job takes in three kinds of outside text, and each goes through one of these first:
  - a Grants.gov listing (its title, synopsis, eligibility, award and agency): admit_listing(key, listing);
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


def admit_listing(key: str, listing: dict, kind: str = "grants.gov listing") -> dict | None:
    """The listing, unchanged, when its text is clean; None when it was quarantined. Its string fields are screened
    as one text, joined by line breaks: a pattern that fires inside one field fires inside the whole, and an
    instruction split across two fields ("...ignore all previous" / "instructions and...") is seen whole. The whole
    is what a person reads in the quarantine."""
    whole = "\n".join(v for v in listing.values() if isinstance(v, str) and v.strip())
    return listing if intake.screen(whole, source=key, kind=kind).ok else None


def admit_page(url: str, text: str) -> str | None:
    """A funder page's text, unchanged, when clean; None when it was quarantined."""
    return text if intake.screen(text, source=url, kind="funder page").ok else None
