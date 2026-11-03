"""Apolaki Fact Checker — adversarial verification agent.

Reads a draft document, extracts every factual claim, classifies
each as PUBLISHED/EXTERNAL/UNSOURCED/PROJECTION, and flags
likely confabulations.

Run after any Apolaki draft before human review.

It reads all of a document. A document longer than CHUNK_CHARS is checked in parts, each in full, split at paragraph
breaks where it can; every character is in exactly one part. Until 2026-11-02 it sent only the first 6,000 characters
and said nothing, so a 1,500-word concept paper was checked to about its middle. When a part fails or its claim list is
cut off at the output budget, check_document returns None and check_file says which characters went unchecked: a
partial check is never reported as the whole.
"""
import os
import json
import re
import requests

from . import config

OLLAMA_BASE = config.ollama_base()
# Same model family as the agent; a thinking model. Until 2026-09-23 this defaulted
# to qwen3:30b-a3b, read only message.content, and never set think=false, so a run
# whose token budget went to reasoning returned "" -> no JSON -> [] -> "0 suspect
# claims": a clean verdict on an absence, the same defect the agent had.
MODEL = os.environ.get("CHECKER_MODEL", os.environ.get("APOLAKI_MODEL", "qwen3.8:27b-mxfp8"))

_CHECKER_TEMPLATE = """You are a hostile fact-checker. Your ONLY job is to find claims that might be fabricated.

Read this document and extract EVERY factual claim (statistics, percentages, dollar amounts, user counts, accuracy metrics, market sizes, citations to external organizations).

For each claim, classify it:
{verified_line}
- EXTERNAL: Cites an external source (McKinsey, NHS, Gartner, EU regulation). Flag for human verification — might be real, might be fabricated.
- SUSPECT: A specific number with no clear source. Likely confabulated. Flag with HIGH priority.
- PROJECTION: Future-looking claim (revenue projections, target metrics). Label clearly.

Output as JSON array:
[
  {{"claim": "exact text of claim", "classification": "VERIFIED|EXTERNAL|SUSPECT|PROJECTION", "reason": "why you classified it this way", "priority": "HIGH|MEDIUM|LOW"}}
]

Be paranoid. If in doubt, flag it. False positives are better than letting a fabricated statistic into a grant application.

DOCUMENT:
"""


def checker_prompt() -> str:
    """The checker's prompt with the brand file's verified numbers (key "verified_claims")."""
    b = config.brand()
    line = b.get("verified_claims_line") or (
        "- VERIFIED: Cites the organization's own published work with specific numbers it lists as verified: "
        + (b.get("verified_claims") or "none are configured, so nothing is VERIFIED on that ground") + ". These are REAL.")
    return _CHECKER_TEMPLATE.format(verified_line=line)



# The most of a document one call reads: the amount the checker always sent (text[:6000]), now a part size rather than
# a cut. A longer document is checked in several parts.
CHUNK_CHARS = 6000
# Where a part may end, best first: a paragraph break, a line break, a sentence end, a space. The break stays with the
# part before it.
_BREAKS = ("\n\n", "\n", ". ", " ")


def split_document(text: str, size: int = CHUNK_CHARS) -> list[tuple[int, int]]:
    """(start, end) spans that cover the text in order, each at most size characters, every character in exactly one.
    Each part ends at the best break in its second half (see _BREAKS), or at size when there is none. A document that
    is empty or only whitespace has no parts."""
    if not text.strip():
        return []
    spans, start = [], 0
    while len(text) - start > size:
        window = text[start:start + size]
        cut = size
        for brk in _BREAKS:
            i = window.rfind(brk, size // 2)
            if i != -1:
                cut = i + len(brk)
                break
        spans.append((start, start + cut))
        start += cut
    spans.append((start, len(text)))
    return spans


def _check_part(part: str, k: int, n: int) -> tuple[list[dict] | None, str, bool]:
    """One call on one part: (claims or None, error, cut). cut is True when the claim list ran into the output budget,
    so it may be missing claims."""
    label = f"[part {k} of {n}]\n" if n > 1 else ""
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": checker_prompt() + label + part}],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 3000},
            },
            timeout=600,
        )
        data = resp.json()
    except Exception as e:
        return None, f"the call failed: {e}", False
    if data.get("error"):
        return None, f"the model answered with an error: {data['error']}", False
    msg = data.get("message", {}) or {}
    content = (msg.get("content") or "").strip()
    for close in ("</think>", "</thinking>"):
        if close in content:
            content = content.rsplit(close, 1)[1]
    if not content:
        return None, "the model returned no content (keys: %s)" % ",".join(sorted(msg.keys())), False
    cut = data.get("done_reason") == "length"
    json_match = re.search(r'\[[\s\S]*\]', content)
    if not json_match:
        return None, f"no JSON array in the answer, which begins {content[:200]!r} [first 200 characters]", cut
    try:
        parsed = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        return None, f"the JSON did not parse ({e}); the answer begins {content[:200]!r} [first 200 characters]", cut
    return parsed, "", cut          # the match starts with "[" and ends with "]", so what parses is a list


def check_document_parts(text: str) -> dict:
    """Check every part of a document (split_document) and say what ran.

    Returns {"chars", "parts", "claims", "checked_parts", "failed_parts", "incomplete_parts", "complete"}: claims from
    every part that ran, each marked with its "part" (when there is more than one); failed_parts as
    {"part", "chars": [first, last] (1-based, inclusive), "error"}; incomplete_parts, the parts whose claim list was cut
    at the output budget. complete is True only when every part ran with its whole claim list, and False for an empty
    document, which has nothing to check."""
    spans = split_document(text)
    out = {"chars": len(text), "parts": len(spans), "claims": [], "checked_parts": [], "failed_parts": [],
           "incomplete_parts": [], "complete": False}
    for k, (a, b) in enumerate(spans, 1):
        claims, error, cut = _check_part(text[a:b], k, len(spans))
        if claims is None:
            out["failed_parts"].append({"part": k, "chars": [a + 1, b], "error": error})
            continue
        out["checked_parts"].append(k)
        if cut:
            out["incomplete_parts"].append(k)
        out["claims"].extend({**c, "part": k} if len(spans) > 1 and isinstance(c, dict) else c for c in claims)
    out["complete"] = bool(spans) and not out["failed_parts"] and not out["incomplete_parts"]
    return out


def check_document(text: str) -> list[dict] | None:
    """Run fact-checker on a whole document (in parts when it is long: check_document_parts).

    Returns a list of claims, or None when any part produced nothing parseable, any part's claim list was cut off at the
    output budget, or the document is empty. None is not an empty list: an empty list means "no claims found", None
    means "the check did not happen, or did not cover all of the document". Callers must not report None as zero;
    check_document_parts says what did run.
    """
    out = check_document_parts(text)
    for f in out["failed_parts"]:
        print(f"Checker error, part {f['part']} of {out['parts']} (characters {f['chars'][0]:,}-{f['chars'][1]:,}): "
              f"{f['error']}")
    for k in out["incomplete_parts"]:
        print(f"Checker warning: part {k} of {out['parts']}: the claim list was cut at num_predict and may be incomplete")
    return out["claims"] if out["complete"] else None


def check_file(filepath: str) -> dict:
    """Check a grant draft file and return report.

    The report says how much of the file was read: checked is True only when all of it was, with every claim list
    whole and every entry of it a claim; partial is True when some parts ran and others didn't (or were cut, or held
    entries that aren't claims), and the claims are then only from what could be read. The printout says the same in
    words.

    Every entry of the claim list is accounted for (2026-11-03 verifier: entries that weren't JSON objects were
    dropped without a word): unreadable_claims lists each one that isn't an object, as text, and unclassified each
    claim whose classification isn't one of the four. Both are printed for a person to read."""
    with open(filepath) as f:
        text = f.read()

    out = check_document_parts(text)
    claims = [c for c in out["claims"] if isinstance(c, dict)]
    unreadable = [repr(c)[:200] for c in out["claims"] if not isinstance(c, dict)]
    coverage = {k: out[k] for k in ("chars", "parts", "checked_parts", "failed_parts", "incomplete_parts")}
    none_read = {"verified": [], "external": [], "suspect": [], "projections": [], "unclassified": [],
                 "unreadable_claims": []}
    print(f"\n{'='*60}")
    print(f"FACT CHECK: {os.path.basename(filepath)}")
    print(f"{'='*60}")
    if not out["parts"]:
        print("  EMPTY DOCUMENT: nothing was checked.")
        return {"file": filepath, "checked": False, "partial": False, "total_claims": None, **coverage, **none_read}
    if not out["checked_parts"]:
        print("  CHECK DID NOT RUN: the checker produced no parseable claim list. Not a clean result.")
        for f in out["failed_parts"]:
            print(f"    part {f['part']}: {f['error']}")
        return {"file": filepath, "checked": False, "partial": False, "total_claims": None, **coverage, **none_read}

    whole = out["complete"] and not unreadable
    known = ("VERIFIED", "EXTERNAL", "SUSPECT", "PROJECTION")
    report = {
        "file": filepath,
        "checked": whole,
        "partial": not whole,
        "total_claims": len(claims),
        **coverage,
        "verified": [c for c in claims if c.get("classification") == "VERIFIED"],
        "external": [c for c in claims if c.get("classification") == "EXTERNAL"],
        "suspect": [c for c in claims if c.get("classification") == "SUSPECT"],
        "projections": [c for c in claims if c.get("classification") == "PROJECTION"],
        "unclassified": [c for c in claims if c.get("classification") not in known],
        "unreadable_claims": unreadable,
    }

    if whole:
        print(f"  Checked all of it: {out['chars']:,} characters in {out['parts']} part"
              f"{'s' if out['parts'] != 1 else ''}.")
    elif out["complete"]:
        print(f"  READ ALL OF IT ({out['chars']:,} characters), BUT THE CLAIM LIST WASN'T WHOLE: the counts below leave "
              f"out the entries that weren't claims.")
    else:
        print(f"  CHECKED ONLY PART OF IT: {len(out['checked_parts'])} of {out['parts']} parts ran whole or in part; "
              f"the claims below come only from the parts that ran.")
        for f in out["failed_parts"]:
            print(f"    NOT CHECKED: part {f['part']}, characters {f['chars'][0]:,}-{f['chars'][1]:,}: {f['error']}")
        for k in out["incomplete_parts"]:
            print(f"    CUT SHORT: part {k}'s claim list ran into the output budget and may be missing claims.")
    if unreadable:
        n = len(unreadable)
        print(f"    {n} {'entry' if n == 1 else 'entries'} in the claim list weren't claims (not JSON objects), so "
              f"{'it was' if n == 1 else 'they were'} not classified; a person reads {'it' if n == 1 else 'them'}:")
        for c in unreadable:
            print(f"      - {c}")
    print(f"  Total claims: {report['total_claims']}")
    print(f"  Verified: {len(report['verified'])}")
    print(f"  External (verify): {len(report['external'])}")
    print(f"  SUSPECT (likely fabricated): {len(report['suspect'])}")
    print(f"  Projections: {len(report['projections'])}")
    if report["unclassified"]:
        print(f"  UNCLASSIFIED (none of the four labels; read them): {len(report['unclassified'])}")
        for c in report["unclassified"]:
            print(f"    - {str(c.get('claim', c))[:100]}... (labelled {c.get('classification')!r})")

    if report["suspect"]:
        print(f"\n  🚨 SUSPECT CLAIMS:")
        for c in report["suspect"]:
            print(f"    - {str(c.get('claim', c))[:100]}...")
            print(f"      Reason: {c.get('reason', '(none given)')}")

    if report["external"]:
        print(f"\n  ⚠️ EXTERNAL (needs human verification):")
        for c in report["external"]:
            print(f"    - {str(c.get('claim', c))[:100]}...")

    return report


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        check_file(sys.argv[1])
    else:
        # Check all grant drafts
        draft_dir = str(config.folder("grant-drafts"))
        for fname in os.listdir(draft_dir):
            if fname.endswith("_draft.md"):
                check_file(os.path.join(draft_dir, fname))
