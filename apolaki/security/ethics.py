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
            r"attendee|mom|mum|dad|mother|father|grandparent|resident|neighbou?r|tenant|shopper|diner|travell?er|"
            r"subscriber|participant|homeowner)")
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

# Words that, just before "the fake reviews", say they are being caught, moderated or answered, not written:
# "Report the fake reviews to Yelp", "How do I respond to fake reviews?" (round 3).
_HANDLING = ("spot", "detect", "flag", "report", "remove", "delete", "identify", "combat", "fight", "handle",
             "handling", "tackle", "tackling", "address", "addressing", "catch", "catching", "stop", "stopping", "prevent",
             "preventing", "moderate", "moderating", "avoid", "respond to", "responding to", "reply to", "replying to",
             "deal with", "dealing with")
_NOT_WRITING = "".join(rf"(?<!\b{v.replace(' ', chr(92) + 's')}\s{d})" for v in _HANDLING
                       for d in ("", r"the\s", r"all\s", r"any\s", r"these\s", r"those\s", r"our\s"))
# "Invite customers to write reviews" is asking them, not writing reviews (round 3).
_OTHERS_TO = "".join(rf"(?<!\b{w}\sto\s)" for b in (
    "customer", "client", "user", "donor", "supporter", "member", "patient", "buyer", "guest", "parent", "student",
    "volunteer", "fan", "reader", "attendee", "subscriber", "participant", "visitor", "shopper", "diner", "resident",
    "tenant", "neighbor", "neighbour") for w in (b, b + "s")) + "".join(
    rf"(?<!\b{w}\sto\s)" for w in ("them", "people", "everyone", "everybody", "folks", "others", "anyone", "him",
                                     "her"))

# Other kinds of review, which a person may ask Apolaki to write: a book or film review, a performance or peer review.
_REVIEW_KINDS = (r"(?:book|film|movie|album|show|play|concert|exhibit\w*|game|paper|literature|code|peer|performance|"
                 r"annual|year[-\s]end|quarterly|monthly|weekly|mid[-\s]year|program(?:me)?|policy|grant|budget|safety|"
                 r"security|risk|design|case|systematic|internal|external|independent|board|staff|employee|team|"
                 r"project|incident|legal|compliance|technical|editorial|press|media|critical|scholarly|academic|draft|"
                 r"document|contract|site|website|usability|accessibility|data|process)")

_DARK_PATTERNS = {
    "false_urgency": [
        # "Last chance to keep your monthly gift active", sent because a card really expired, is a lapse notice: it is
        # flagged for a person (urgency_claim), not blocked (2026-11-02 review, R5).
        r"(act\s+now|(?:don't|dont|do\s+not)\s+miss\s+out|expires?\s+soon)",
        r"(hurry|before\s+it's\s+too\s+late|now\s+or\s+never)",
        # "Last chance", "limited time": blocked, unless the sentence names a concrete date or time ("Last-chance
        # reminder: the grant deadline is Friday at 5pm"), when a person checks it (urgency_claim, round 3). A count
        # of what is left ("Only three spots left!") is checked against the brief: scarcity() below.
        r"((?:last|final)" + _HY + r"chance(?!\s+to\s+(?:keep|renew|update|reactivate|restore)\s+your\b)|"
        r"limited" + _HY + r"time|time\s+is\s+running\s+out|final\s+hours|"
        r"(?:deal|offer|sale|price|discount)s?\s+(?:won't|will\s+not)\s+last)",
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
        # discussing them (round 3): "the FTC rule on fake reviews", "banned fake reviews", "why fake reviews hurt"
        r"(?<!\bon\s)(?<!\bbanned\s)(?<!\bwhy\s)(?<!\boutlawed\s)(?<!\bprohibits\s)(?<!\bprohibited\s)"
        r"(?<!\bregulate\s)(?<!\bregulating\s)(?<!\bpolicing\s)(?<!\bdangers\sof\s)(?<!\bproblem\sof\s)"
        r"(?<!\bproblem\swith\s)(?<!\brise\sof\s)(?<!\bspread\sof\s)(?<!\bimpact\sof\s)(?<!\bcost\sof\s)"
        + _NOT_WRITING
        + r"\b(?:fake|fabricated|made" + _HY + r"up|invented|bogus|phony|phoney|sham|counterfeit|fictitious|fictional|"
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
        + _PERSONA + r"[\s-]+(?:reviews?|testimonials?|endorsements?|ratings?|quotes?)\b"
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
        r"\b(?:pretend(?:s|ed|ing)?\s+(?:that\s+)?(?:to\s+be|you(?:'re|\s+are|\s+were|\s+was))|"
        r"pos(?:e|es|ed|ing)\s+as|masquerad(?:e|es|ed|ing)\s+as|act(?:s|ed|ing)?\s+as|"
        r"imagine\s+(?:that\s+)?you(?:'re|\s+are|\s+were)|role[-\s]?play(?:s|ed|ing)?\s+as|"
        r"play(?:s|ed|ing)?\s+the\s+(?:role|part)\s+of|you(?:'re|\s+are)\s+now)\s+"
        r"(?:a|an|one\s+of\s+(?:our|the|my|their)|our|the)?\s*(?:\w+\s+){0,2}?" + _PERSONS + r"(?![-\w])"
        r"(?!\s+(?:service|support|success|care|experience|journey|agent|rep|representative|team|relations)s?\b)"
        r"[^.]{0,40}\b(?:reviews?|testimonials?|endorse\w*|ratings?|rate\b|posts?|comments?)",
        # "as if you were a customer", "as though it came from a donor"; not "as if you were talking to a customer"
        # or "as though you were a customer support agent".
        r"\bas\s+(?:if|though)\s+(?:you(?:'re|\s+(?:are|were|was))|it\s+(?:was|were|is|came)\s+(?:written\s+)?"
        r"(?:from|by)|(?:it\s+was\s+)?written\s+by|from|by)\s+(?:a|an|one\s+of\s+(?:our|the|my|their)|our|the)?"
        r"\s*(?:\w+\s+){0,2}?" + _PERSONS + r"(?![-\w])(?!\s+(?:service|support|success|care|experience|"
        r"journey|agent|rep|representative|team|relations|base|data|list|segment|persona|interview)s?\b)",
        # Plainly asked-for invented reviews (R4): "Write five glowing reviews from happy clients". A reply to, a
        # summary of, or a request for real reviews is not one.
        r"\b(?:write|draft|generate|create|compose|invent|fabricate|make\s+up|come\s+up\s+with)\s+"
        r"(?:(?!ask|request|invit|collect|gather|solicit|encourag|repl|respon|summar|about\b|to\b|of\b|for\b|on\b|"
        r"that\b)\w+[\s-]+){0,4}?(?:reviews?|testimonials?|endorsements?|quotes?)\s+(?:from|by)\s+"
        r"(?:[\w']+,?\s+){0,3}?" + _PERSONS + r"\b(?!\s+(?:survey|letter|email|interview|feedback|form|comment|data|"
        r"list|response|note|story|stories)s?\b)",
        r"\bin\s+the\s+voice\s+of\s+(?:a|an|one\s+of\s+our)\s+(?:\w+\s+){0,2}?" + _PERSONS + r"\b",
        r"\bfrom\s+(?:a|an|one)\s+(?:\w+\s+){0,2}?" + _PERSONA + r"'s\s+(?:point\s+of\s+view|perspective|pov)\b",
        r"\b(?:reviews?|testimonials?|endorsements?)\s+(?:\w+\s+){0,3}?as\s+(?:a|an|one\s+of\s+(?:our|the|my|their))"
        r"\s+(?:\w+\s+){0,2}?" + _PERSONS + r"\b",
        # Round 3 (2026-11-03 verifier, round 2). Writing reviews at all: real ones are written by the people who give
        # them. "Write five Google reviews for our bakery", "Draft 10 five-star reviews for our Amazon listing", "Write
        # five glowing reviews". Not a reply to, summary of, request for, policy or page for reviews; not another kind
        # of review (a book, performance or peer review); not a review of something other than us ("of the
        # conference"); not asking others to write them ("invite customers to write reviews").
        _OTHERS_TO + r"\b(?:write|writes|writing|wrote|draft(?:s|ed|ing)?|generat(?:e|es|ed|ing)|creat(?:e|es|ed|ing)|"
        r"compos(?:e|es|ed|ing)|produc(?:e|es|ed|ing)|churn(?:s|ed|ing)?\s+out|crank(?:s|ed|ing)?\s+out|"
        r"come\s+up\s+with|give\s+me|get\s+me|send\s+me)\s+"
        r"(?:(?!ask|request|invit|collect|gather|solicit|encourag|repl|respon|summar|analy|about\b|to\b|of\b|"
        r"for\b|on\b|in\b|that\b|with\b|from\b|using\b|featur|show|highlight|quot|includ|contain|polic|section|page|"
        r"template|guid|tip|shar|celebrat|thank|promot|monitor|track|moderat|handl|manag|" + _REVIEW_KINDS + r"\b)"
        r"[\w'-]+[\s-]+){0,4}?(?:reviews?|testimonials?|endorsements?|ratings?)\b"
        r"(?![\s-]+(?:polic|guideline|section|page|widget|template|request|email|form|survey|program|process|"
        r"strateg|summar|analys|report|dashboard|feed|carousel|module|block|plugin|integration|api\b|data\b|"
        r"platform|tool|software|system|management|moderation|respon|repl|heading|title|intro|link|button|score|"
        r"average|count|metric|site|aggregator|cycle|meeting|session|period|criteria|rubric|scale|board|committee|"
        r"panel|deadline))"
        r"(?!\s+(?:of|about)\s+(?!(?:our|us)\b|my\s+(?!(?:essay|draft|writing|paper|code|work|resume|cv|cover\s+"
        r"letter|application|proposal|grant|plan|article|copy|pitch|deck|presentation|speech|story|poem|book|"
        r"manuscript|thesis)\b)))",
        # Words written now to be credited to a persona later: "Draft a few testimonials we can attribute to donors".
        r"\b(?:write|writes|writing|draft\w*|creat\w*|generat\w*|compos\w*|make\s+up|invent\w*|come\s+up\s+with)\b"
        r"[^.]{0,40}?\b(?:quotes?|testimonials?|reviews?|endorsements?|statements?|comments?)\b[^.]{0,20}?"
        r"\b(?:that\s+)?(?:we|you|i|they)\s+(?:can|could|will|would|might|may)\s+(?:attribut|credit|ascrib|assign|"
        r"pin)\w*\b",
        # Signed with an invented name: "Write a testimonial and sign it with a made-up customer name".
        r"\b(?:testimonials?|reviews?|quotes?|endorsements?)\b[^.]{0,60}?\b(?:sign|attribut|credit|byline)\w*\b"
        r"[^.]{0,30}?\b(?:made[-\s]up|fake|invented|fictional|fictitious|random|false|phony|bogus|stock)\s+"
        r"(?:\w+\s+){0,2}?(?:names?|signatures?|bylines?|persons?|people)\b",
        # "Write reviews from the perspective of happy customers".
        r"\b(?:reviews?|testimonials?|endorsements?|quotes?)\b[^.]{0,30}?\bfrom\s+the\s+(?:perspective|point\s+of\s+"
        r"view|pov|viewpoint|voice)s?\s+of\s+(?:a|an|our|the|some|various|different|several)?\s*(?:\w+\s+){0,2}?"
        + _PERSONS + r"\b",
        # Writing as one, in praise: "Write as a customer: why I love this product".
        r"\bwrit\w*\b[^.]{0,30}?\bas\s+(?:a|an|one\s+of\s+(?:our|the|my|their))\s+(?:\w+\s+){0,2}?" + _PERSONS
        + r"(?![-\w])(?!\s+(?:service|support|success|care|experience|journey|agent|rep|representative|team|"
        r"relations)s?\b)[^.]{0,60}?\b(?:i\s+love|why\s+i|i\s+recommend|my\s+experience|loved|recommend|glowing|"
        r"praise|rave|five\s+stars|5\s+stars)",
        # Sock puppets: reviews from new or several accounts, or under other names.
        r"\b(?:reviews?|ratings?|testimonials?|comments?|posts?|stars?)\b[^.]{0,60}?\bfrom\s+(?:a\s+|an\s+)?"
        r"(?:new|fake|different|separate|second|other|another|multiple|several|burner|throwaway|dummy|alt(?:ernate)?)"
        r"\s+accounts?\b",
        r"\bunder\s+(?:different|fake|false|made[-\s]up|other|several|multiple|various|assumed|invented)\s+names\b",
    ],
    # An instruction to state something the instruction itself says isn't so (round 3): "Say the offer expires in 24
    # hours even though it doesn't", "Tell them there are only a few left even though we have plenty". A concession
    # that isn't about the claim ("even though we didn't hit our goal") is not one: the negation has to end its clause.
    "false_claim": [
        r"\b(?:say|says|said|saying|tell|tells|telling|claim\w*|state|states|stating|write|writes|writing|"
        r"announc\w*|put|add|mention\w*|imply|implies|suggest\w*|promis\w*|advertis\w*|make\s+(?:it|them|people|"
        r"readers|donors|customers)\s+(?:think|believe))\b[^.!?]{0,100}?\b(?:even\s+though|although|though|"
        r"when\s+in\s+(?:fact|reality)|while\s+in\s+(?:fact|reality))\s+"
        r"(?:(?:it|that|this|they|there|he|she|we|i|you)\s*(?:doesn't|don't|didn't|isn't|aren't|wasn't|weren't|"
        r"won't|wouldn't|can't|cannot|hasn't|haven't|hadn't|shouldn't|will\s+not|does\s+not|do\s+not|did\s+not|"
        r"is\s+not|are\s+not|was\s+not|were\s+not|has\s+not|have\s+not)\s*(?:really\s+|actually\s+)?"
        r"(?:(?:true|so|the\s+case|happen|exist|apply)\b\s*)?(?=[.,;:!?)]|$)|"
        r"(?:it|that|this)(?:'s|\s+is|\s+was)\s+(?:not\s+true|false|untrue|a\s+lie|made\s+up|fake|not\s+the\s+case)|"
        r"(?:we|they|there)\s+(?:have|has|got|are|is)\s+(?:plenty|lots|loads|enough|tons|many|more|\d[\d,]*)\b)",
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
        # "Add everyone who downloaded the PDF to the newsletter" (round 3); not "everyone who opted in".
        r"\b(?:add|subscrib|enrol|enroll|sign|put)\w*\s+(?:up\s+)?(?:everyone|everybody|anyone|all\s+(?:of\s+)?"
        r"(?:the\s+|our\s+|my\s+)?\w+|people|visitors|attendees|customers|donors|users|contacts|leads|members)\s+"
        r"(?:who|that|whose)\s+(?!(?:\w+\s+){0,2}?(?:opted|opt|signed|subscribed|asked|consented|agreed|chose|"
        r"requested|said\s+yes|ticked|checked))(?:[\w'-]+\s+){1,6}?(?:to|on|into|onto)\s+(?:the\s+|our\s+|my\s+|a\s+)?"
        r"(?:\w+\s+)?(?:newsletters?|mailing\s+lists?|e-?mail\s+lists?|lists?|marketing\s+(?:emails?|lists?)|drips?|"
        r"sequences?)\b",
    ],
    # A paid, gifted or affiliate connection is disclosed where the reader sees it.
    "undisclosed_ad": [
        r"(?<!n't\s)(?<!\bnot\s)(?<!\bnever\s)"
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
        # Round 3: "Don't mention the sponsorship", "Post it without disclosing the sponsorship", "No need to disclose
        # that it's sponsored", "Don't disclose the affiliate link".
        r"\b(?:don't|dont|do\s+not|never|no\s+need\s+to|without)\s+(?:\w+\s+)?(?:mention\w*|disclos\w*|say\w*|"
        r"tell\w*|reveal\w*|admit\w*|acknowledg\w*|state\w*|note\w*|flag\w*|label\w*|mark\w*|tag\w*)\b[^.]{0,40}?"
        r"(?:\bsponsor(?:ship|ed|s)?\b(?!')|\bpartnership\b|\baffiliat\w*|\bpaid\s+(?:post|partnership|promotion|"
        r"placement|content|ad)s?\b|#(?:ad|ads|sponsored|paid|partner|spon|gifted)\b|\bcommissions?\b)"
        r"(?![^.]{0,40}\b(?:beyond|other\s+than|apart\s+from|except|besides)\b)",
        # "Don't label it as sponsored", "Don't mark it as an ad".
        r"\b(?:don't|dont|do\s+not|never|no\s+need\s+to|without)\s+(?:label|mark|tag|flag|call|identify|present)\w*"
        r"\s+(?:it|this|them|these|the\s+\w+)\s+as\s+(?:an?\s+)?(?:ad|advert\w*|advertis\w*|sponsored|paid|"
        r"promotion\w*|partnership)\b",
        # "Don't mention that Acme paid for this post", "Don't tell readers we got the product for free".
        r"\b(?:don't|dont|do\s+not|never|no\s+need\s+to)\s+(?:mention|say|tell|disclose|reveal|admit|let)\w*\b"
        r"[^.]{0,30}?\b(?:paid\s+(?:us|me|them\s+to|for\s+(?:this|the|it|our|that))|(?:we|i|they)\s+(?:got|get|"
        r"received|receive|were\s+(?:given|sent)|was\s+(?:given|sent))\b[^.]{0,30}?\b(?:for\s+free|free\s+of\s+"
        r"charge|at\s+no\s+cost|as\s+a\s+gift|gratis))",
        # "Hide the fact that Acme paid us"; not "Don't hide the fact that Acme paid us".
        r"(?<!n't\s)(?<!\bnot\s)(?<!\bnever\s)\b(?:hide|hides|hiding|conceal\w*|bury|burying|obscur\w*|downplay\w*|"
        r"cover\s+up|gloss\s+over)\b[^.]{0,30}?\b(?:paid\s+(?:us|me|for)|sponsor(?:ship|ed)\b|affiliat\w*|"
        r"#ad\b|gifted|compensat\w*|gave\s+us|sent\s+us)",
        # "Make it look organic, not like a paid post".
        r"\b(?:look|seem|appear|read|sound|feel)s?\s+(?:\w+\s+)?(?:organic|unsponsored|natural|independent|unpaid|"
        r"genuine|authentic)\b[^.]{0,30}?\b(?:not|rather\s+than|instead\s+of)\s+(?:like\s+)?(?:a\s+|an\s+)?"
        r"(?:paid|sponsored|ad\b|advert\w*|promotion\w*|partnership)",
        # "Write the sponsored post for Acme, no disclosure please"; and where the model asks ("Should I include the
        # #ad disclosure?") and the answer is no.
        r"\b(?:sponsor\w*|paid|affiliat\w*|partner\w*|#ad)\b[^.]{0,60}?\bno\s+(?:#\w+\s+|ad\s+|sponsor(?:ship)?\s+)?"
        r"(?:disclosure|disclaimer|label|tag)s?\b,?\s+(?:needed|necessary|required)\b",
        # Asked for outright, it needs no context: "no disclosure please", "no #ad this time" (the answer to "Should
        # it be disclosed?" comes after the model's reply, whose full stop ends the sentence above).
        r"\bno\s+(?:#\w+|(?:ad\s+|sponsor(?:ship)?\s+)?(?:disclosures?|disclaimers?|labels?|tags?))\b,?\s+(?:please|"
        r"this\s+time|for\s+this\s+one|on\s+this\s+one)\b",
        r"\b(?:include|add|keep|put|use|mention|show|disclose|label|tag)\w*\b[^.?]{0,40}?(?:#(?:ad|ads|sponsored|paid|"
        r"partner|spon|gifted)\b|\b(?:disclosures?|disclaimers?|sponsorship|ad\s+label|paid[-\s]partnership\s+label)"
        r"\b)[^.?]{0,20}\?\s*(?:no\b|nope\b|nah\b|don't\b|do\s+not\b|skip\s+it|leave\s+it\s+(?:out|off)|"
        r"take\s+it\s+(?:out|off)|drop\s+it|not\s+this\s+time|no\s+need)",
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
        r"checks?|checkers?|complian\w*|box(?:es)?|reports?|free\b|regulations?|requirements?|provisions?|"
        r"triggers?|words?|polic\w*)\b)",
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
        r"\bfew\s+(?:seats|spots|tickets|places)\s+(?:left|remain)|\bfilling\s+up\b|"
        r"\bonly\s+a\s+(?:few|handful|couple)\s+(?:\w+\s+)?(?:left|remain\w*)\b",
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
# What the patterns read, and the checks that need more than a pattern
# ---------------------------------------------------------------------------

# Letters spelled out with a separator between each ("f-a-k-e", "s p a m"): read joined as well.
_SPACED_LETTERS = re.compile(r"\b(?:[A-Za-z][-.\s\u00b7*]){2,}[A-Za-z]\b")
# Moderating spam is not sending it (CC, 2026-11-03): "Delete the spam comments", "Report spam accounts", "filter,
# remove, flag or moderate spam". The word is read as "unwanted" after such a verb, so "Write spam comments" and
# "Post spam replies" still block.
_MODERATING_SPAM = re.compile(
    r"\b((?:delet|remov|report|filter|flag|moderat|block|ban|catch|catching|hid|mark|detect|purg|quarantin|stop|fight|"
    r"reduc|prevent|review|handl|avoid|clean\w*\s+up|deal\w*\s+with|get\w*\s+rid\s+of|weed\w*\s+out)\w*\s+"
    r"(?:(?:the|all|any|these|those|our|my|incoming|new|obvious|more|of)\s+){0,3})spam", re.IGNORECASE)


def pattern_texts(content: str) -> list[str]:
    """The texts the patterns read: the content normalised (apolaki.security.normalize), and with spelled-out letters
    joined and underscores read as spaces ("fake_testimonial") when that differs; in each, "spam" after a moderating
    verb is read as "unwanted"."""
    t = normalize(content or "")
    out = [t]
    for v in (_SPACED_LETTERS.sub(lambda m: re.sub(r"[-.\s\u00b7*]", "", m.group()), t), t.replace("_", " ")):
        if v not in out:
            out.append(v)
    return [_MODERATING_SPAM.sub(lambda m: m.group(1) + "unwanted", v) for v in out]


# A concrete date or time: "March 15", "15 March", "3/15", "2026-03-15", "Friday", "5pm".
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)")
_CONCRETE_DATE = re.compile(
    r"\b" + _MONTH + r"\.?\s+\d{1,2}(?:st|nd|rd|th)?\b|\b\d{1,2}(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH + r"\b|"
    r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b|\b(?:mon|tues|wednes|thurs|fri|satur|sun)day\b|"
    r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)", re.IGNORECASE)
# The end of a sentence: a stop before a capital letter or the end, or a line break ("Mar. 15" doesn't end one).
_SENTENCE_END = re.compile(r"[.!?](?=\s+[A-Z\"']|\s*$)|\n")


def dated(text: str, match: re.Match) -> bool:
    """Whether the sentence holding the match names a concrete date or time (_CONCRETE_DATE)."""
    start = max((m.end() for m in _SENTENCE_END.finditer(text, 0, match.start())), default=0)
    end = _SENTENCE_END.search(text, match.end())
    return bool(_CONCRETE_DATE.search(text, start, end.start() if end else len(text)))


# A count of what is left ("Only three spots left!", "Just 2 seats left") is true or false, and only the brief can say
# which: it passes, for a person to confirm, when the brief states the same count of what is left (round 3).
_NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                       "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBERS.update({"thirty": 30, "forty": 40, "fifty": 50, "a couple": 2, "a couple of": 2})
_COUNT = r"(\d[\d,]*|" + "|".join(sorted((re.escape(w).replace(r"\ ", r"\s+") for w in _NUMBERS), key=len,
                                          reverse=True)) + r")"
_SCARCITY = re.compile(r"\b(?:only|just|merely)\s+" + _COUNT + r"\s+(?:[\w'-]+\s+){0,2}?"
                       r"(?:left|remain(?:s|ing)?|available|to\s+go)\b", re.IGNORECASE)
_SCARCITY_FACT = re.compile(r"\b" + _COUNT + r"\s+(?:[\w'-]+\s+){0,3}?(?:are\s+|is\s+)?(?:still\s+)?"
                            r"(?:left|remain(?:s|ing)?|available|open|unsold|unclaimed|free)\b", re.IGNORECASE)


def _count(word: str) -> int:
    word = " ".join(word.lower().split())
    return int(word.replace(",", "")) if word[0].isdigit() else _NUMBERS[word]


def scarcity(texts: list[str], facts: str = "") -> str:
    """"blocked" when a text claims a count of what is left that the facts (the brief) don't state; "flagged" when
    every such claim is one the facts state; "" when there is none."""
    claims = {_count(m.group(1)) for t in texts for m in _SCARCITY.finditer(t)}
    if not claims:
        return ""
    stated = {_count(m.group(1)) for m in _SCARCITY_FACT.finditer(normalize(facts or ""))}
    return "flagged" if claims <= stated else "blocked"


# ---------------------------------------------------------------------------
# Ethics Engine
# ---------------------------------------------------------------------------

# Dark patterns a concrete date or time in the same sentence turns into a flag for a person (urgency_claim): "Last
# chance" and "limited time" with a real deadline ("through March 15", "Friday at 5pm"), round 3.
_DATED_OK = {("false_urgency", 2)}


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

    def evaluate(self, content: str, facts: str = "") -> EthicsCheck:
        """Evaluate content or action against marketing ethics.

        The patterns read normalised text (curly quotes straight, invisible characters out, look-alike letters
        folded: apolaki.security.normalize), so "Don’t miss out" is read as "Don't miss out"; and that text with
        spelled-out letters joined and underscores read as spaces (pattern_texts).

        facts is what the content may rest on: for a draft, its brief. A count of what is left ("Only three spots
        left!") is blocked unless the facts state the same count, and then flagged for a person (scarcity)."""
        texts = pattern_texts(content)
        content = texts[0]
        claim = ""          # urgency a person can confirm: a dated deadline, a count of what is left the brief states

        def blocked(category: str) -> EthicsCheck:
            logger.warning("Ethics BLOCKED: dark pattern '%s' detected", category)
            return EthicsCheck(verdict=EthicsVerdict.BLOCKED, reason=f"Dark pattern detected: {category}",
                               category=category, suggestion=self._suggest_alternative(category))

        # Check dark patterns first (hard deny)
        for category, patterns in _COMPILED_DARK_PATTERNS.items():
            for i, pattern in enumerate(patterns):
                for text in texts:
                    for m in pattern.finditer(text):
                        if (category, i) in _DATED_OK and dated(text, m):
                            claim = "a dated deadline"
                            continue
                        return blocked(category)
            if category == "false_urgency":
                left = scarcity(texts, facts)
                if left == "blocked":
                    return blocked(category)
                if left:
                    claim = claim or "a count of what is left that the brief states"
        if claim:
            return EthicsCheck(verdict=EthicsVerdict.FLAGGED, reason=f"Requires human review: urgency_claim ({claim})",
                               category="urgency_claim",
                               suggestion="Check the deadline or count is true before this goes out.")

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
            "false_claim": "Say only what is true. If the offer doesn't expire, don't say it does; give the real date, the real count, or no claim at all.",
        }
        return alternatives.get(category, "Consider the ethical implications and revise with prosocial intent.")
