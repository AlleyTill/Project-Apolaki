"""apolaki.security.normalize: what the pattern checks read. One test per step, so each step has its own guard."""
import pytest

from apolaki.security.normalize import fold_quotes, normalize


def test_plain_ascii_is_unchanged_and_empty_stays_empty():
    s = "Write a post about the clinic's hours, \"10am to 2pm\", for $5,000 or less."
    assert normalize(s) == s and normalize("") == ""


def test_tag_characters_become_the_ascii_they_hide():
    hidden = "".join(chr(0xE0000 + ord(c)) for c in "fake review")
    assert normalize("Nice post" + chr(0xE0001) + hidden + chr(0xE007F)) == "Nice postfake review"


@pytest.mark.parametrize("cp", [0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x00AD, 0x200E, 0x200F, 0x202A, 0x202E,
                                0x2066, 0x2069, 0x180E, 0x2061, 0x115F, 0x1160, 0x3164, 0xFFA0],
                         ids=lambda cp: f"U+{cp:04X}")
def test_invisible_characters_are_removed(cp):
    assert normalize("fa" + chr(cp) + "ke") == "fake"


@pytest.mark.parametrize("ch", list("\u2018\u2019\u201a\u201b\u2032\u2035\u02bc\u02bb\u02bd\u02b9`\u00b4\u055a\u05f3"
                                    "\ua78b\ua78c\u2039\u203a\uff07"), ids=lambda c: f"U+{ord(c):04X}")
def test_every_apostrophe_look_alike_becomes_straight(ch):
    assert normalize(f"don{ch}t") == "don't"


@pytest.mark.parametrize("ch", list("\u201c\u201d\u201e\u201f\u2033\u2036\u00ab\u00bb\u301d\u301e\u301f\uff02\u05f4"
                                    "\u02ba"), ids=lambda c: f"U+{ord(c):04X}")
def test_every_double_quote_look_alike_becomes_straight(ch):
    assert normalize(f"{ch}hi{ch}") == '"hi"'


@pytest.mark.parametrize("text,plain", [
    ("\uff46\uff41\uff4b\uff45 \uff52\uff45\uff56\uff49\uff45\uff57", "fake review"),      # fullwidth
    ("\U0001d41f\U0001d41a\U0001d424\U0001d41e", "fake"),                                     # mathematical bold
    ("\ufb01ve", "five"),                                                                       # ligature
    ("\uff04\uff15\uff10\uff10\uff10", "$5000"),                                               # fullwidth $ and digits
    ("fa\u0301ke re\u0300vie\u0302w", "fake review"),                                          # combining marks
    ("f\u00e0k\u00e9", "fake"),                                                                 # precomposed accents
    ("caf\u00e9", "cafe"),
    ("a\u20ddb", "ab"),                                                                         # enclosing mark
])
def test_compatibility_forms_and_accents_become_plain_letters(text, plain):
    assert normalize(text) == plain


@pytest.mark.parametrize("text,plain", [
    ("f\u0430k\u0435 r\u0435vi\u0435w", "fake review"),          # Cyrillic a and ie (U+0430, U+0435)
    ("\u0455\u0440\u0430m", "spam"),                              # Cyrillic dze, er and a (U+0455, U+0440, U+0430)
    ("\u0421\u041e\u0420\u0423", "COPY"),                         # Cyrillic capitals
    ("\u03bf\u03c1\u03b5n", "open"),                              # Greek omicron, rho, epsilon (U+03BF, U+03C1, U+03B5)
    ("\u0391CT N\u039fW", "ACT NOW"),                             # Greek capitals
    ("l\u0131m\u0131ted", "limited"),                             # dotless i
])
def test_cyrillic_and_greek_look_alikes_become_latin(text, plain):
    assert normalize(text) == plain


@pytest.mark.parametrize("ch", list("\u1fbd\u1fbf\u1fef\u1ffd\u1ffe\u02ca\u02cb"), ids=lambda c: f"U+{ord(c):04X}")
def test_spacing_accents_typed_as_apostrophes_are_folded_before_decomposition(ch):
    """Decomposed first, U+1FFD (Greek oxia) becomes a space and a combining mark, and "don't" reads "don t"."""
    assert normalize(f"don{ch}t") == "don't"


def test_a_quote_produced_by_decomposition_is_folded_too():
    """U+2034 (triple prime) decomposes to three U+2032 primes; the fold after decomposition straightens them."""
    assert normalize("5\u2034") == "5" + "'" * 3


CORPUS = ["Don\u2019t miss out", "fa\u200bke", "\uff46\uff41\uff4b\uff45", "f\u0430ke", "fa\u0301ke",
          "\u00abquote\u00bb", "don\u1ffdt", "5\u2034", "\ufeffhello\u2060world", "Hangul\u3164filler", "\u0391CT",
          "caf\u00e9 \u2018ok\u2019", "".join(chr(0xE0000 + ord(c)) for c in "hidden"), "\u1100\u1161 Hangul jamo",
          "\u00bd and \u2153"]


@pytest.mark.parametrize("s", CORPUS)
def test_normalising_twice_is_normalising_once(s):
    assert normalize(normalize(s)) == normalize(s)


def test_fold_quotes_keeps_every_position():
    s = "\u201cShe said \u2018we\u2019re in\u2019\u201d \u00abnow\u00bb"
    folded = fold_quotes(s)
    assert len(folded) == len(s) and folded == "\"She said 'we're in'\" \"now\""
