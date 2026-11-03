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
# Between the halves of "limited-time", "last-chance", "crossed-out": spaces, an ASCII hyphen or a Unicode one.
_HY = r"[\s\-\u2010-\u2015]+"
# Sensitive traits (marketingskills prospecting: never target or infer them).
# Health conditions by name, since people say "people with depression", not "people with a health condition".
_CONDITIONS = (r"(?:depression|anxiety|addiction|alcoholism|substance\s+(?:use|abuse)|mental\s+(?:health|illness)"
               r"(?:\s+(?:conditions?|issues|problems))?|cancer|diabetes|hiv|dementia|alzheimer'?s|autism|adhd|"
               r"bipolar(?:\s+disorder)?|schizophrenia|ptsd|eating\s+disorders?|anorexia|bulimia|obesity|"
               r"chronic\s+(?:illness|pain|conditions?)|terminal\s+illness|infertility|miscarriages?|"
               r"suicidal\s+(?:thoughts|ideation)|self[-\s]harm|gender\s+identity|criminal\s+(?:records?|histor(?:y|ies)))")
_TRAITS = (r"(?:health(?:\s+conditions?)?|medical|diagnos\w*|disabilit\w*|pregnan\w*|sexual(?:ity|\s+orientation)|"
           r"religio\w*|faith|political\s+(?:views?|leanings?|affiliations?)|politics|ethnicity|race|"
           r"immigration\s+status|financial\s+hardship|debt|bankrupt\w*|" + _CONDITIONS[3:-1] + r")")
# The same traits as words for people ("depressed teenagers"), for targeting only: as adjectives they turn up in
# ordinary sentences too often to block an inference on ("Guess who is marching in the pride parade").
_TRAIT_ADJECTIVES = (r"(?:depressed|anxious|diabetic|bipolar|autistic|suicidal|pregnant|disabled|addicted|"
                     r"terminally\s+ill|chronically\s+ill|mentally\s+ill|gay|lesbian|bisexual|transgender|queer|"
                     r"muslim|jewish|christian|catholic|hindu|sikh|buddhist|atheist|undocumented|bankrupt)")
_PEOPLE_WORDS = (r"(?:people|persons|users|customers|donors|members|visitors|prospects|audiences?|women|men|teens|"
                 r"teenagers|youth|kids|children|parents|mothers|fathers|moms|dads|patients|folks|individuals|adults|"
                 r"seniors|students|voters|families|households|immigrants|veterans|employees|workers)")

_DARK_PATTERNS = {
    "false_urgency": [
        # "Last chance to keep your monthly gift active", sent because a card really expired, is a lapse notice: it is
        # flagged for a person (urgency_claim), not blocked (2026-11-02 review, R5).
        r"(last" + _HY + r"chance(?!\s+to\s+(?:keep|renew|update|reactivate|restore)\s+your\b)|act\s+now|"
        r"(?:don't|dont|do\s+not)\s+miss\s+out|expires?\s+soon)",
        r"(only\s+\d+\s+left|limited" + _HY + r"time|hurry|before\s+it's\s+too\s+late)",
        # A bare "countdown" blocked "Our countdown to the conference starts today" (R5); a fake or resetting one is
        # still blocked.
        r"(offer\s+ends|ticking\s+clock|midnight\s+tonight)",
        r"((?:fake|false|phony|resetting|evergreen)\s+(?:countdown|timer|deadline)s?|"
        r"(?:countdown|timer)s?\s+that\s+(?:resets?|restarts?|starts\s+over|reloads?|refreshes))",
    ],
    "guilt_manipulation": [
        r"(if\s+you\s+don't\s+(donate|help|act).*\b(suffer|die|starve))",
        r"(how\s+can\s+you\s+(sleep|live).*knowing)",
        r"(their\s+blood\s+is\s+on\s+your\s+hands)",
        r"(you're\s+the\s+only\s+one\s+who\s+can)",
    ],
    # A decline option worded to shame the person who picks it ("No thanks, I don't care about saving lives"), and
    # instructions to write one. Naming it to avoid it ("Avoid confirmshaming") is not one.
    "confirmshaming": [
        r"\bno(?:pe)?[,.!]?\s+(?:thanks|thank\s+you)?[,.!]?\s*i(?:'d|\s+would)\s+rather\b",
        r"\bno(?:pe)?[,.!]?\s+(?:thanks|thank\s+you)?[,.!]?\s*i\s+(?:don't|do\s+not)\s+"
        r"(?:care\s+about|want\s+to|like|support|need)\s+(?:\w+\s+){0,2}?"
        r"(?:sav|help|support|protect|feed|learn|grow|improv|succe|win|children|kids|animals|planet|environment|"
        r"community|cause|money|deals?\b|discounts?\b|famil)\w*",
        r"(?<!\bavoid\s)(?<!\bno\s)(?<!\bnot\s)(?<!\bnever\s)(?<!\bwithout\s)(?<!n't\s)\bconfirm[-\s]?sham\w*",
        r"(?<!\bnot\s)(?<!\bnever\s)(?<!n't\s)\bguilt[-\s]?trip\w*\b[^.]{0,40}"
        r"\b(?:opt[-\s]?outs?|declin\w*|unsubscrib\w*|no\s+button|cancel\w*|leav\w*)",
        r"\bshame\w*\s+(?:people|users|visitors|donors|them|readers|customers|subscribers)\b[^.]{0,30}"
        r"\b(?:for|into|who)\b[^.]{0,30}\b(?:declin\w*|leav\w*|unsubscrib\w*|saying\s+no|opt\w*\s+out|cancel\w*|"
        r"not\s+(?:donat|giv|sign)\w*)",
    ],
    "astroturfing": [
        r"(fake\s+grassroots)",
        # Reviews and testimonials called invented, unless the words around say it is to forbid or catch them
        # ("Our policy forbids fabricated reviews", "how to spot fake reviews").
        r"(?<!\bno\s)(?<!\bnot\s)(?<!n't\s)(?<!\bnever\s)(?<!\bspot\s)(?<!\bdetect\s)(?<!\bflag\s)(?<!\breport\s)"
        r"(?<!\bremove\s)(?<!\bagainst\s)(?<!\babout\s)(?<!\bavoid\s)(?<!\bforbid\s)(?<!\bforbids\s)"
        r"(?<!\bban\s)(?<!\bbans\s)(?<!\bbanning\s)(?<!\bidentify\s)(?<!\bcombat\s)(?<!\bfight\s)"
        r"\b(?:fake|fabricated|made" + _HY + r"up|invented|bogus|phony|phoney|sham|counterfeit|fictitious|fictional|"
        r"imaginary|manufactured)\s+(?:\w+[\s-]+){0,2}?(?:reviews?|testimonials?|endorsements?|ratings?|quotes?)\b",
        # Verbs that only ever mean inventing, as instructions: "Invent three testimonials", "Make up a quote from a
        # customer". Their -ed and -ing forms, and "fake" (an adjective as often as a verb: "Fake three reviews" is
        # caught above), are left to the pattern above, which knows "forbids fabricated reviews".
        r"(?<!\bnever\s)(?<!\bnot\s)(?<!n't\s)"
        r"\b(?:invents?|fabricates?|manufactures?|concocts?|(?:make|makes)\s+up|(?:cook|dream)s?\s+up)\s+"
        r"(?:(?!about\b|for\b|of\b|on\b|to\b|that\b|names?\b|titles?\b|headings?\b|formats?\b|layouts?\b|"
        r"designs?\b|sections?\b|pages?\b)\w+[\s-]+){0,4}?"
        r"(?:reviews?|testimonials?|endorsements?|ratings?|quotes?\s+(?:from|by))\b",
        # Writing reviews in the persona's name: "Write 5 glowing customer reviews". A reply to, a summary of, a
        # request for, a page featuring, or a policy, section or template for reviews is not one.
        r"\b(?:write|writes|writing|wrote|written|draft(?:s|ed|ing)?|generat(?:e|es|ed|ing)|creat(?:e|es|ed|ing)|"
        r"compos(?:e|es|ed|ing)|produc(?:e|es|ed|ing)|churn(?:s|ed|ing)?\s+out|crank(?:s|ed|ing)?\s+out|"
        r"come\s+up\s+with)\s+"
        r"(?:(?!ask|request|invit|collect|gather|solicit|encourag|repl|respon|summar|analy|about\b|to\b|of\b|"
        r"for\b|on\b|that\b|with\b|from\b|using\b|featur|show|highlight|quot|includ|contain)\w+[\s-]+){0,4}?"
        + _PERSONA + r"[\s-]+(?:reviews?|testimonials?|endorsements?|ratings?)\b"
        r"(?![\s-]+(?:polic|guideline|section|page|widget|template|request|email|form|survey|program|process|"
        r"strateg|summar|analys|report|dashboard|feed|carousel|module|block|plugin|integration|api\b|data\b|"
        r"platform|tool|software|system|management|moderation|respon|repl|heading|title|intro|link|button|score|"
        r"average|count|metric))",
        r"\b(?:reviews?|testimonials?|endorsements?|quotes?)\b[^.]{0,40}\b(?:sound|read|look|seem)s?\s+"
        r"(?:like|as\s+if|as\s+though)\s+(?:they|it|each|these)\s+(?:came|come|were|was|are|is)\s+"
        r"(?:written\s+)?(?:from|by)\s+(?:\w+\s+){0,3}?" + _PERSONS + r"\b",
        r"(sock\s+puppet|astroturf|fake\s+account|impersonat)",
        r"(write\b.*\bas\s+if\s+you're\s+a\b.*\b(customer|user|supporter|donor|member))",
        r"(write\b.*\btestimonial\b.*\bas\s+if)",
        r"(pretend\s+to\s+be\s+a\s+(customer|user|supporter|donor))",
        # Posing as one to write a review ("Pose as a happy client and write a review"); posing as a customer to
        # test the checkout is not this.
        r"\b(?:pretend(?:s|ed|ing)?\s+to\s+be|pos(?:e|es|ed|ing)\s+as|masquerad(?:e|es|ed|ing)\s+as)\s+"
        r"(?:a|an|one\s+of\s+(?:our|the|my|their)|our|the)?\s*(?:\w+\s+){0,2}?" + _PERSONS + r"\b[^.]{0,40}"
        r"\b(?:reviews?|testimonials?|endorse\w*|ratings?|rate\b|posts?|comments?)",
        # "as if you were a customer", "as though it came from a donor"; not "as if you were talking to a customer"
        # or "as though you were a customer support agent".
        r"\bas\s+(?:if|though)\s+(?:you(?:'re|\s+(?:are|were|was))|it\s+(?:was|were|is|came)\s+(?:written\s+)?"
        r"(?:from|by)|(?:it\s+was\s+)?written\s+by|from|by)\s+(?:a|an|one\s+of\s+(?:our|the|my|their)|our|the)?"
        r"\s*(?:\w+\s+){0,2}?" + _PERSONS + r"(?![-\w])(?!\s+(?:service|support|success|care|experience|"
        r"journey|agent|rep|representative|team|relations|base|data|list|segment|persona|interview)s?\b)",
        # Plainly asked-for invented reviews (R4): "Write five glowing reviews from happy clients". A reply to, a
        # summary of, or a request for real reviews is not one.
        r"\b(?:write|draft|generate|create|compose|invent|fabricate|make\s+up)\s+"
        r"(?:(?!ask|request|invit|collect|gather|solicit|encourag|repl|respon|summar|about\b|to\b|of\b|for\b|on\b|"
        r"that\b)\w+[\s-]+){0,4}?(?:reviews?|testimonials?|endorsements?)\s+(?:from|by)\s+(?:[\w']+,?\s+){0,3}?"
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
        r"\bopt(?:s|ed|ing)?\s+(?:everyone|everybody|all|them|people|users|donors|customers|members|subscribers|"
        r"contacts|visitors|attendees|supporters|buyers|clients)\s+in\b",
    ],
    # A paid, gifted or affiliate connection is disclosed where the reader sees it.
    "undisclosed_ad": [
        r"\b(?:leave\s+(?:out|off)|take\s+(?:out|off|away)|strip|drop|remove|omit|skip|hide|bury|without|"
        r"(?:don't|do\s+not|never)\s+(?:include|use|add|put|show|mention|disclose|say|tell))\b[^.]{0,40}?"
        r"(?:#(?:ad|ads|sponsored|paid|partner|spon|gifted)\b|"
        r"\b(?:ad|sponsorship|paid[-\s]partnership|affiliate)\s+(?:disclosure|label|tag)s?\b|\bdisclosures?\b|"
        r"\b(?:that\s+)?(?:it|this|the\s+\w+|we|they)(?:'s|\s+(?:is|was|'s|are|were|got))\s+"
        r"(?:sponsored|paid|an\s+ad|gifted|compensated))",
        # "Leave the sponsorship disclosure out"; not "Never leave the disclosure out", not "the price tag off".
        r"(?<!n't\s)(?<!\bnot\s)(?<!\bnever\s)\b(?:leave|keep|take|cut)\s+(?:the\s+|our\s+|that\s+|any\s+|this\s+)?"
        r"(?:#(?:ad|ads|sponsored|paid|partner|spon|gifted)\b|"
        r"(?:(?:ad|sponsorship|sponsor|paid[-\s]partnership|affiliate|partnership)\s+)?(?:disclosures?|disclaimers?)|"
        r"(?:ad|sponsorship|sponsor|paid[-\s]partnership|affiliate|partnership)\s+(?:labels?|tags?))\s+(?:out|off)\b",
    ],
    # Pricing and asks built to mislead (marketing-psychology's techniques, as things to catch): a fictitious original
    # price, a decoy option, door-in-the-face.
    "pricing_manipulation": [
        r"\b(?:fake|false|fictitious|made[-\s]up|inflated|phony|invented)\s+(?:\w+\s+){0,2}?"
        r"(?:original|regular|list|retail|was|compare[-\s]at|reference)\s+prices?",
        r"\b(?:original|regular|was|list|compare[-\s]at|crossed" + _HY + r"out|struck" + _HY + r"through|strikethrough|"
        r"slashed)\s+price\b[^.]{0,60}\b(?:never|nobody|no\s+one)\s+"
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
        r"(mass\s+email|blast\s+to\s+all|email\s+bomb)",
        # Any "spam", except the law that governs it (CAN-SPAM, the CAN SPAM Act), the tools that catch it (spam
        # folder, filter, check, score...), "anti-spam", and a negation ("We never spam you", "No spam, ever"). The
        # 2026-11-03 design read: no output could name the US law while bare "spam" blocked.
        r"(?<!\bcan-)(?<!\bcan\u2010)(?<!\banti-)(?<!\banti\s)(?<!\bnever\s)(?<!\bnot\s)(?<!n't\s)(?<!\bno\s)"
        r"\bspam(?:s|med|ming|mer|mers)?\b(?![-\s]*(?:filters?|folders?|traps?|laws?|act\b|rules?|complaints?|scores?|"
        r"checks?|checkers?|compliance|box(?:es)?|reports?|free\b|regulations?|requirements?|provisions?)\b)",
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
        # Plain phrasings (2026-11-03 design read): "Target people with depression", "Show our ads to people who have
        # diabetes", "Target depressed teenagers".
        r"\b(?:target|segment|profile|single\s+out|aim|go\s+after|market\s+to|advertis\w*\s+to|"
        r"(?:show|serve)\w*\s+(?:the\s+|our\s+|these\s+)?ads?\s+to)\w*\b[^.]{0,60}?"
        r"\b(?:with|who\s+(?:have|has|had|suffers?|struggles?|lives?|battles?|deals?|are\s+(?:suffering|struggling|"
        r"living|battling|dealing|diagnosed)|were\s+diagnosed)(?:\s+(?:from|with))?|suffering\s+from|"
        r"struggling\s+with|living\s+with|battling|diagnosed\s+with|in\s+recovery\s+from)\s+(?:\w+\s+){0,2}?"
        + _TRAITS + r"\b",
        r"\b(?:target|segment|single\s+out|aim|go\s+after|market\s+to|advertis\w*\s+to)\w*\b[^.]{0,40}?\b"
        + _TRAIT_ADJECTIVES + r"\s+(?:\w+\s+)?" + _PEOPLE_WORDS + r"\b",
    ],
    # Tracking people for ads: a custom or lookalike audience made from a list, retargeting, tracking pixels,
    # fingerprinting (2026-11-03 design read: all were approved). Each can be lawful with consent; a person checks.
    "tracking": [
        r"\b(?:custom|lookalike|look-alike|matched|similar)\s+audiences?\b|\bcustomer\s+match\b",
        r"\bre-?(?:target|market)(?:s|ed|ing)?\b",
        r"\b(?:upload|import|sync|send|give|hand|share|match)\w*\b[^.]{0,40}\b(?:donor|supporter|customer|member|"
        r"subscriber|client|volunteer|contact|mailing|email)s?\s+(?:lists?|database|data|emails?|records|files?|crm|"
        r"addresses)\b[^.]{0,40}\b(?:to|with|into|on)\s+(?:\w+\s+){0,2}?(?:facebook|meta|google|tiktok|linkedin|"
        r"instagram|twitter|ad\s+platforms?|ads?\s+(?:manager|account|platform)s?)\b",
        r"\b(?:tracking|meta|facebook|tiktok|linkedin|conversion|retargeting)\s+pixels?\b|\bpixel\s+(?:tracking|"
        r"events?|code)\b",
        r"\b(?:browser|device|canvas)\s+fingerprint\w*|\bthird[-\s]party\s+cookies?\b|"
        r"\bcross[-\s](?:site|device|app)\s+track\w*",
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
            "confirmshaming": "Word the decline option plainly: 'No thanks' or 'Not now'. Saying no should cost the reader nothing, not even a jab.",
        }
        return alternatives.get(category, "Consider the ethical implications and revise with prosocial intent.")
