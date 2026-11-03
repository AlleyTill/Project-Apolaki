"""Prosocial marketing ethics guardrails.

Marketing is power. This module ensures the power serves the Cause.

The line between "effective marketing" and "manipulation" is where
the ethics engine lives. Effective marketing connects people with
things that genuinely serve them. Manipulation exploits psychology
to extract behavior that serves the marketer at the audience's expense.

Apolaki only does the first kind.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .normalize import normalize

logger = logging.getLogger(__name__)


class EthicsVerdict(str, Enum):
    APPROVED = "approved"
    FLAGGED = "flagged"       # Needs human review
    BLOCKED = "blocked"       # Hard deny


@dataclass(frozen=True)
class EthicsCheck:
    """Result of an ethics evaluation."""
    verdict: EthicsVerdict
    reason: str
    category: str = ""        # Which ethics rule triggered
    suggestion: str = ""      # How to fix if flagged


# ---------------------------------------------------------------------------
# Dark pattern detection
# ---------------------------------------------------------------------------

# People the patterns below mean when they ask who a review, a voice or an inference is about.
_PERSONA = (r"(?:customer|client|user|donor|supporter|member|patient|buyer|guest|parent|student|volunteer|fan|reader|"
            r"attendee)")
_PERSONS = _PERSONA[:-1] + r")s?"
# Sensitive traits (marketingskills prospecting: never target or infer them).
_TRAITS = (r"(?:health(?:\s+conditions?)?|medical|diagnos\w*|disabilit\w*|pregnan\w*|sexual(?:ity|\s+orientation)|"
           r"religio\w*|faith|political\s+(?:views?|leanings?|affiliations?)|politics|ethnicity|race|"
           r"immigration\s+status|financial\s+hardship|debt|bankrupt\w*)")

_DARK_PATTERNS = {
    "false_urgency": [
        # "Last chance to keep your monthly gift active", sent because a card really expired, is a lapse notice: it is
        # flagged for a person (urgency_claim), not blocked (2026-11-02 review, R5).
        r"(last\s+chance(?!\s+to\s+(?:keep|renew|update|reactivate|restore)\s+your\b)|act\s+now|"
        r"don't\s+miss\s+out|expires?\s+soon)",
        r"(only\s+\d+\s+left|limited\s+time|hurry|before\s+it's\s+too\s+late)",
        # A bare "countdown" blocked "Our countdown to the conference starts today" (R5); a fake or resetting one is
        # still blocked.
        r"(offer\s+ends|ticking\s+clock|midnight\s+tonight)",
        r"((?:fake|false|phony|resetting|evergreen)\s+(?:countdown|timer|deadline)s?|"
        r"(?:countdown|timer)s?\s+that\s+resets?)",
    ],
    "guilt_manipulation": [
        r"(if\s+you\s+don't\s+(donate|help|act).*\b(suffer|die|starve))",
        r"(how\s+can\s+you\s+(sleep|live).*knowing)",
        r"(their\s+blood\s+is\s+on\s+your\s+hands)",
        r"(you're\s+the\s+only\s+one\s+who\s+can)",
    ],
    "astroturfing": [
        r"(fake\s+(review|testimonial|endorsement|grassroots))",
        r"(sock\s+puppet|astroturf|fake\s+account|impersonat)",
        r"(write\b.*\bas\s+if\s+you're\s+a\b.*\b(customer|user|supporter|donor|member))",
        r"(write\b.*\btestimonial\b.*\bas\s+if)",
        r"(pretend\s+to\s+be\s+a\s+(customer|user|supporter|donor))",
        # Plainly asked-for invented reviews (R4): "Write five glowing reviews from happy clients". A reply to, a
        # summary of, or a request for real reviews is not one.
        r"\b(?:write|draft|generate|create|compose|invent|fabricate|make\s+up)\s+"
        r"(?:(?!ask|request|invit|collect|gather|solicit|encourag|repl|respon|summar|about\b|to\b|of\b|for\b|on\b|"
        r"that\b)\w+[\s-]+){0,4}?(?:reviews?|testimonials?|endorsements?)\s+(?:from|by)\s+(?:\w+\s+){0,3}?"
        + _PERSONS + r"\b",
        r"\bin\s+the\s+voice\s+of\s+(?:a|an|one\s+of\s+our)\s+(?:\w+\s+){0,2}?" + _PERSONS + r"\b",
        r"\bfrom\s+(?:a|an|one)\s+(?:\w+\s+){0,2}?" + _PERSONA + r"'s\s+(?:point\s+of\s+view|perspective|pov)\b",
        r"\b(?:reviews?|testimonials?|endorsements?)\s+(?:\w+\s+){0,3}?as\s+(?:a|an)\s+(?:\w+\s+){0,2}?"
        + _PERSONA + r"\b",
    ],
    # Review programs (marketingskills referrals): no five-star requests, no reward for a good review, no asking only
    # the happy ones, no prewritten reviews. A plain reward for any review is flagged instead (review_incentive).
    "review_manipulation": [
        r"\b(?:ask|request|tell|get|urge|encourage|invite)\w*\b[^.]{0,60}\b(?:5|five)[\s-]*stars?\s+reviews?",
        r"\b(?:gift\s*cards?|discounts?|coupons?|rewards?|prizes?|free\s+\w+|\$\d+|payments?|pay)\b[^.]{0,60}"
        r"\b(?:for|in\s+exchange\s+for|in\s+return\s+for)\b[^.]{0,30}"
        r"\b(?:positive|good|great|glowing|favou?rable|(?:5|five)[\s-]*stars?)\s+reviews?",
        r"\bonly\s+(?:ask|invite|email|send|request)\w*\b[^.]{0,60}\b(?:happy|satisfied|positive|promoters?)\b"
        r"[^.]{0,40}\breviews?",
        r"\b(?:ask|invite)\w*\s+only\s+(?:the\s+)?(?:happy|satisfied)\b[^.]{0,40}\breviews?",
        r"\breviews?\b[^.]{0,60}\bonly\s+(?:to\s+)?(?:\w+\s+){0,3}?"
        r"(?:happy|satisfied|promoters?|who\s+(?:rated|scored)\s+us\s+(?:a\s+)?(?:9|10|five|5))",
        r"\b(?:pre[-\s]?written|ready[-\s]made|scripted)\s+reviews?",
    ],
    # Consent asked for, not assumed: no pre-checked boxes or automatic sign-ups, no sending to or adding people
    # without asking. "Make sure the box is not pre-checked" is the honest instruction and is not matched.
    "consent_bypass": [
        r"(?<!\bnot\s)(?<!\bnever\s)(?<!n't\s)(?<!\bno\s)"
        r"\b(?:pre[-\s]?(?:check|tick|select|fill)(?:ed|ing|s)?|auto[-\s]?(?:enrol|enroll|subscrib|opt[-\s]?in)\w*)\b"
        r"[^.]{0,60}\b(?:opt[-\s]?ins?|consent|subscri\w*|newsletters?|marketing|check[-\s]?box(?:es)?|box(?:es)?|"
        r"mailing\s+lists?|emails?)\b",
        r"\b(?:opt[-\s]?ins?|consent|marketing|newsletter|subscription|mailing\s+list)\b"
        r"(?:(?!\bnot\b|\bnever\b|n't\b|\bun)[^.]){0,40}"
        r"\b(?:pre[-\s]?(?:checked|ticked|selected)|(?:checked|ticked|on)\s+by\s+default|"
        r"defaults?(?:ed)?\s+to\s+(?:yes|on|checked|ticked|opted[-\s]?in))",
        r"\b(?:send|email|e-mail|message|text|sms|add|subscribe|enrol|enroll|sign)\w*\b[^.]{0,80}"
        r"\b(?:lists?|everyone|all\s+(?:of\s+)?(?:our|the|my)\s+\w+|contacts?|subscribers?|database|newsletter|"
        r"mailing)\b[^.]{0,60}\b(?:without|no)\s+(?:\w+\s+){0,2}?(?:asking|consent|permission|opt[-\s]?in|agreement)",
    ],
    # A paid, gifted or affiliate connection is disclosed where the reader sees it.
    "undisclosed_ad": [
        r"\b(?:leave\s+(?:out|off)|take\s+(?:out|off|away)|strip|drop|remove|omit|skip|hide|bury|without|"
        r"(?:don't|do\s+not|never)\s+(?:include|use|add|put|show|mention|disclose|say|tell))\b[^.]{0,40}?"
        r"(?:#(?:ad|ads|sponsored|paid|partner|spon|gifted)\b|"
        r"\b(?:ad|sponsorship|paid[-\s]partnership|affiliate)\s+(?:disclosure|label|tag)s?\b|\bdisclosures?\b|"
        r"\bthat\s+(?:it|this|the\s+\w+|we)\s+(?:is|was|'s|are|were|got)\s+"
        r"(?:sponsored|paid|an\s+ad|gifted|compensated))",
        r"\bleave\s+(?:the\s+)?(?:#(?:ad|sponsored|paid)\b|disclosure|(?:ad|sponsorship)\s+(?:label|tag))\s+(?:out|off)\b",
    ],
    # Pricing and asks built to mislead (marketing-psychology's techniques, as things to catch): a fictitious original
    # price, a decoy option, door-in-the-face.
    "pricing_manipulation": [
        r"\b(?:fake|false|fictitious|made[-\s]up|inflated|phony|invented)\s+(?:\w+\s+){0,2}?"
        r"(?:original|regular|list|retail|was|compare[-\s]at|reference)\s+prices?",
        r"\b(?:original|regular|was|list|compare[-\s]at)\s+price\b[^.]{0,60}\b(?:never|nobody|no\s+one)\s+"
        r"(?:\w+\s+){0,2}?(?:charged|paid|sold|offered|used)",
        r"\bdecoy\s+(?:tier|option|plan|price|pricing|package|level|choice)s?\b",
        r"\b(?:deliberately|intentionally|purposely)\s+(?:worse|bad|overpriced|unattractive)\s+(?:\w+\s+){0,2}?"
        r"(?:tier|option|plan|package|level)",
        r"\bdoor[-\s]in[-\s]the[-\s]face\b",
        r"\bso\s+(?:that\s+)?(?:the\s+)?(?:real|actual|second|smaller|\$?\d[\d,]*)\s*(?:\w+\s+){0,2}?"
        r"(?:ask|amount|request|gift)?\s*(?:feels?|seems?|looks?)\s+(?:small|smaller|reasonable|modest|cheap|tiny)\b",
    ],
    # Never infer a sensitive trait about people (marketingskills prospecting). Targeting by one is flagged.
    "sensitive_inference": [
        r"\b(?:infer|guess|predict|deduce|work\s+out|figure\s+out)\w*\b[^.]{0,30}"
        r"\b(?:donors?|supporters?|members?|people|customers?|clients?|users?|prospects?|contacts?|subscribers?|"
        r"visitors?|their|whose|each|who)\b[^.]{0,40}\b" + _TRAITS + r"\b",
    ],
    "spam": [
        r"(mass\s+email|blast\s+to\s+all|email\s+bomb|spam)",
        r"(scrape\s+(email|contact|profile)s?)",
        r"(buy\s+(email\s+)?list|purchased\s+contacts?)",
        r"(unsolicited\s+(mass|bulk))",
    ],
    "deceptive_metrics": [
        r"(inflat|fake|fabricat)\w*\b.*\b(metric|number|stat|figure|impact)",
        r"(overstat|exaggerat)\w*\b.*\b(impact|result|outcome|reach)",
        r"(misleading\s+(graph|chart|statistic))",
    ],
}

_COMPILED_DARK_PATTERNS = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in _DARK_PATTERNS.items()
}


# ---------------------------------------------------------------------------
# Escalation triggers (human review required)
# ---------------------------------------------------------------------------

_ESCALATION_TRIGGERS = {
    "financial_ask": [
        r"(ask\w*\s+(for\s+)?(a\s+)?(\w+\s+)?(donation|contribution|gift|pledge))",
        # Amounts of $1,000 or more are found by large_amount() below, in any common form.
        r"(major\s+gift|planned\s+giving|legacy\s+gift)",
        r"(fundraising\s+appeal|solicit\w*\s+(fund|donat|gift|support))",
    ],
    "public_communication": [
        # Whole words: an instruction to publish is flagged; "we just published our paper" in the copy is not. The
        # deployment's 2026-09-23 audit found the bare stem flagging nearly every research announcement, which
        # trains reviewers to ignore flags.
        r"\b(publish|post\s+as|send\s+on\s+behalf|release\s+to\s+media)\b",
        r"(official\s+statement|press\s+release|media\s+advisory)",
        r"(go\s+live|launch\s+campaign|push\s+to\s+production)",
    ],
    "sensitive_topic": [
        r"(political\s+action|endorse\s+candidate|campaign\s+contribution)",
        r"(protest|boycott|strike|demonstration)",
        r"(legal\s+action|lawsuit|litigation|cease\s+and\s+desist)",
    ],
    "data_sharing": [
        r"(share\b.*\b(data|list|contacts?)\b.*\bwith)",
        r"(export\b.*\b(donor|supporter|member)\b.*\b(data|list|info))",
        r"(third.?party\s+(access|sharing|integration))",
    ],
    # Claimed scarcity or a lapse deadline: fine when true, and only a person can say it is (R5).
    "urgency_claim": [
        r"\b(?:going|selling)\s+(?:out\s+)?fast\b|\balmost\s+(?:gone|sold\s+out|full)\b|"
        r"\bfew\s+(?:seats|spots|tickets|places)\s+(?:left|remain)|\bfilling\s+up\b",
        r"\blast\s+chance\s+to\s+(?:keep|renew|update|reactivate|restore)\s+your\b",
    ],
    # A reward for any review: platforms such as Google and Trustpilot forbid it, and the reward must be disclosed.
    "review_incentive": [
        r"\b(?:gift\s*cards?|discounts?|coupons?|rewards?|prizes?|raffle|giveaway|\$\d+)\b[^.]{0,60}\breviews?\b",
        r"\breviews?\b[^.]{0,40}\b(?:gift\s*cards?|discounts?|coupons?|rewards?|prizes?|raffle|entry)\b",
    ],
    "sensitive_traits": [
        r"\b(?:target|segment|filter|sort|rank|profile|exclude|select)\w*\b[^.]{0,60}"
        r"\b(?:by|based\s+on|according\s+to|using)\s+(?:their\s+)?(?:\w+\s+){0,2}?" + _TRAITS + r"\b",
    ],
}

_COMPILED_ESCALATION = {
    cat: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cat, patterns in _ESCALATION_TRIGGERS.items()
}


# ---------------------------------------------------------------------------
# Money amounts: an ask of $1,000 or more goes to a person
# ---------------------------------------------------------------------------

LARGE_AMOUNT = 1000
_NUMBER = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(k|mm|mn|m|bn|b|thousand|million|billion)?"
_MONEY = re.compile(
    r"(?:(?:us\$|\$|usd|\u00a3|gbp|\u20ac|eur)\s?" + _NUMBER + r"\b"
    r"|" + _NUMBER + r"\s?(?:usd|dollars|bucks|eur|euros|gbp)\b)", re.IGNORECASE)
_MULTIPLIER = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9,
               "billion": 1e9}


def large_amount(text: str) -> str:
    """The first money amount of LARGE_AMOUNT or more in the text, as written ("$1.2M"), or "" if there is none.

    Reads "$5,000", "$5000", "$1.2M", "$50k", "US$7,500", "USD 50,000", "50,000 USD", "1,500 dollars", and pound and
    euro amounts the same way. Before 2026-11-02 only "$" followed by four digits was seen, so "$5,000" and "$1.2M"
    were approved (R3). It does not read amounts in words ("five thousand dollars") or with a dot for thousands
    ("5.000 \u20ac"), and "pounds" alone is taken as weight."""
    for m in _MONEY.finditer(text):
        whole, frac, mult = (m.group(1), m.group(2), m.group(3)) if m.group(1) else (m.group(4), m.group(5), m.group(6))
        value = float(whole.replace(",", "") + ("." + frac if frac else ""))
        value *= _MULTIPLIER.get((mult or "").lower(), 1)
        if value >= LARGE_AMOUNT:
            return m.group(0).strip()
    return ""


# ---------------------------------------------------------------------------
# Ethics Engine
# ---------------------------------------------------------------------------


class MarketingEthicsEngine:
    """Evaluates marketing content and actions against prosocial ethics.

    Three verdicts:
      APPROVED — action is ethical and can proceed
      FLAGGED  — action needs human review before execution
      BLOCKED  — action violates ethics and is denied

    Usage::

        engine = MarketingEthicsEngine()
        check = engine.evaluate("Send urgent donation appeal to all contacts")
        if check.verdict == EthicsVerdict.BLOCKED:
            print(f"Blocked: {check.reason}")
    """

    def evaluate(self, content: str) -> EthicsCheck:
        """Evaluate content or action against marketing ethics.

        The patterns read normalised text (curly quotes straight, invisible characters out, look-alike letters
        folded: apolaki.security.normalize), so "Don’t miss out" is read as "Don't miss out"."""
        content = normalize(content)

        # Check dark patterns first (hard deny)
        for category, patterns in _COMPILED_DARK_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(content):
                    logger.warning(
                        "Ethics BLOCKED: dark pattern '%s' detected", category
                    )
                    return EthicsCheck(
                        verdict=EthicsVerdict.BLOCKED,
                        reason=f"Dark pattern detected: {category}",
                        category=category,
                        suggestion=self._suggest_alternative(category),
                    )

        # Check escalation triggers (human review)
        for category, patterns in _COMPILED_ESCALATION.items():
            amount = large_amount(content) if category == "financial_ask" else ""
            if amount or any(pattern.search(content) for pattern in patterns):
                logger.info(
                    "Ethics FLAGGED: escalation trigger '%s'", category
                )
                return EthicsCheck(
                    verdict=EthicsVerdict.FLAGGED,
                    reason=f"Requires human review: {category}" + (f" ({amount})" if amount else ""),
                    category=category,
                    suggestion=f"Draft the {category} content and present for human approval before sending.",
                )

        return EthicsCheck(
            verdict=EthicsVerdict.APPROVED,
            reason="No ethics concerns detected",
        )

    def evaluate_batch(self, items: list[str]) -> list[EthicsCheck]:
        """Evaluate multiple items, return worst verdict first."""
        checks = [self.evaluate(item) for item in items]
        # Sort: blocked first, flagged second, approved last
        priority = {EthicsVerdict.BLOCKED: 0, EthicsVerdict.FLAGGED: 1, EthicsVerdict.APPROVED: 2}
        return sorted(checks, key=lambda c: priority[c.verdict])

    @staticmethod
    def _suggest_alternative(category: str) -> str:
        """Suggest ethical alternatives for blocked patterns."""
        alternatives = {
            "false_urgency": "Use genuine deadlines (grant closing dates, event dates) instead of manufactured urgency. State facts: 'Applications close March 15' not 'ACT NOW OR MISS OUT.'",
            "guilt_manipulation": "Lead with impact and hope, not guilt. Show what donations ENABLE, not what happens without them. 'Your $50 provides meals for a family for a week' not 'Children will starve without your help.'",
            "astroturfing": "Use genuine testimonials from real supporters. Ask permission to share their stories. Authentic voices are more powerful than fabricated ones.",
            "spam": "Build opt-in lists through genuine value (newsletters, resources, events). Quality > quantity. One engaged supporter is worth 100 spam recipients.",
            "deceptive_metrics": "Report accurate metrics with context. If reach was 10,000, say 10,000 — not 'tens of thousands.' Honest metrics build trust that compounds.",
            "review_manipulation": "Ask every customer for an honest review, with no reward tied to a rating and no sorting out the unhappy ones first. Let them write it in their own words.",
            "consent_bypass": "Ask first: an unchecked opt-in box, a clear sentence about what they'll receive, and email only to people who said yes.",
            "undisclosed_ad": "Disclose every paid, gifted or affiliate connection where the reader sees it: #ad at the start, or 'Sponsored by ...' in the first line.",
            "pricing_manipulation": "Show real prices and real options: a former price only if it was charged, every tier because someone should choose it, and the ask you actually mean.",
            "sensitive_inference": "Don't guess anyone's health, faith, politics, sexuality, ethnicity or finances. Work from what people chose to tell you, for the purpose they told you.",
        }
        return alternatives.get(category, "Consider the ethical implications and revise with prosocial intent.")
