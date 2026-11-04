"""Text as the pattern checks read it: one normalisation in front of every pattern-based check.

The ethics patterns were written with straight apostrophes and plain letters. Text from phones and editors carries
curly ones ("you’re", "don’t"), and look-alike or invisible characters get past a regular expression too: "fake" with
a Cyrillic а, in fullwidth or mathematical letters, with a zero-width space or a soft hyphen inside it, or with
combining accents. normalize() folds all of that to plain text before a pattern runs (2026-11-02 review). It changes
only what the patterns read: the text that is stored, drafted, queued or shown is never touched.

The steps, in order:
  1. Unicode tag characters (U+E0020..U+E007E, invisible text sometimes used to smuggle words past a reader) become
     the ASCII they encode, so a hidden word is checked like a visible one; the other tag characters are removed.
  2. Invisible characters are removed: every format character (Unicode category Cf: zero-width space, joiner and
     non-joiner, word joiner, byte-order mark, soft hyphen, bidirectional controls) and the Hangul fillers that
     render as blanks.
  3. Curly and look-alike quote marks become straight ones: ‘ ’ ‚ ‛ ′ ʼ ` ´ and their kin (Greek spacing accents
     included) become ', and “ ” „ ‟ ″ « » and their kin become ".
  4. Compatibility decomposition (NFKD), then combining marks are dropped: fullwidth and mathematical letters,
     ligatures, and accented letters become plain ones ("ｆａｋｅ", "𝐟𝐚𝐤𝐞", "ﬁ", "fàke").
  5. Cyrillic, Greek and Armenian letters that look like Latin ones become the Latin letter.
  6. Composition (NFC), and step 3 again, since step 4 can produce quote look-alikes (‴ decomposes to three ′).

normalize(normalize(t)) == normalize(t).

Who reads through it: both ethics checks (the library engine and the agent's own patterns, money amounts included), the
output-contract check, the unsourced-quotation check, the auto-capture trigger, the fast classifier and the router. The
style linter does not, on purpose: curly quotes are among the things it counts.

What it can't do: it doesn't undo bidirectional reordering (text stored backwards and displayed forwards), spacing ("f a
k e"), misspellings or paraphrase, and the look-alike table in step 5 covers the common Cyrillic and Greek letters (and
a few Armenian ones), not Unicode's whole confusables list. Folding accents and look-alikes also means a pattern can
match non-English text that only resembles an English trigger. Every pattern is English, so that is rare, and its cost
is a flag a person reads or a refused brief a person can rephrase. (The ethics checks read spelled-out letters joined
as well, and underscores as spaces: apolaki.security.ethics.pattern_texts.)
"""
from __future__ import annotations

import unicodedata

_TAG_ASCII = {cp: cp - 0xE0000 for cp in range(0xE0020, 0xE007F)}
_TAG_OTHER = {0xE0001: None, 0xE007F: None}
_INVISIBLE_LETTERS = {0x115F: None, 0x1160: None, 0x3164: None, 0xFFA0: None}

# Greek spacing accents (U+1FBD..U+1FFE) and the modifier acute and grave go here too: typed as apostrophes, they
# would otherwise decompose in step 4 to a space and a combining mark: don, U+1FFD, t would read "don t".
_APOSTROPHES = "\u2018\u2019\u201a\u201b\u2032\u2035\u02bc\u02bb\u02bd\u02b9`\u00b4\u055a\u05f3\ua78b\ua78c" \
               "\u2039\u203a\uff07\u1fbd\u1fbf\u1fef\u1ffd\u1ffe\u02ca\u02cb"
_DOUBLE_QUOTES = "\u201c\u201d\u201e\u201f\u2033\u2036\u00ab\u00bb\u301d\u301e\u301f\uff02\u05f4\u02ba"
_QUOTES = str.maketrans({**{c: "'" for c in _APOSTROPHES}, **{c: '"' for c in _DOUBLE_QUOTES}})

# Look-alike letters, written as escapes because they can't be told from Latin ones on screen. Each source string
# lines up with the Latin letters under it, one for one.
_LOOKALIKE_PAIRS = [
    # Cyrillic lower case
    ("\u0430\u0432\u0441\u0501\u0435\u04bb\u0456\u0458\u043a\u04cf\u043c\u043d\u043e\u0440\u051b\u0455\u0442\u0443"
     "\u051d\u0445\u04af\u0475",
     "abcdehijklmhopqstywxyv"),
    # Cyrillic upper case
    ("\u0410\u0412\u0421\u0500\u0415\u041d\u0406\u0408\u041a\u041c\u041e\u0420\u051a\u0405\u0422\u0423\u04ae\u051c"
     "\u0425\u0474",
     "ABCDEHIJKMOPQSTYYWXV"),
    # Greek lower case, then upper case
    ("\u03b1\u03b2\u03b5\u03b9\u03ba\u03bd\u03bf\u03c1\u03c4\u03c5\u03c7\u03b3\u03c9", "abeikvoptuxyw"),
    ("\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7", "ABEZHIKMNOPTYX"),
    # Latin letters that stand in for others: dotless i, dotless j, script g, alpha, small capital L
    ("\u0131\u0237\u0261\u0251\u029f", "ijgaL"),
    # Armenian: oh, seh, vo, ho, za, co; capital oh and seh (round 3: "b\u0585gus" got past)
    ("\u0585\u057d\u0578\u0570\u0566\u0581\u0555\u054d", "ounhqgOU"),
]
_LOOKALIKES = str.maketrans("".join(a for a, _ in _LOOKALIKE_PAIRS), "".join(b for _, b in _LOOKALIKE_PAIRS))


def normalize(text: str) -> str:
    """Plain text for pattern matching (see the module docstring). Never store or show the result."""
    if not text:
        return text
    t = text.translate(_TAG_ASCII).translate(_TAG_OTHER).translate(_INVISIBLE_LETTERS)
    t = "".join(c for c in t if unicodedata.category(c) != "Cf")
    t = t.translate(_QUOTES)
    t = "".join(c for c in unicodedata.normalize("NFKD", t) if unicodedata.category(c) not in ("Mn", "Me"))
    t = t.translate(_LOOKALIKES)
    return unicodedata.normalize("NFC", t).translate(_QUOTES)


def fold_quotes(text: str) -> str:
    """Step 3 alone: one character in, one character out, so positions in the result are positions in the text."""
    return text.translate(_QUOTES)
