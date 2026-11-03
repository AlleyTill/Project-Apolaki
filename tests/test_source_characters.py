"""Test sources spell invisible and look-alike characters as escapes (2026-11-03 verifier: tests/test_garuda_intake.py
carried a literal zero-width space, soft hyphen, Cyrillic I and fullwidth letters). A literal one can't be seen in a
review or a diff, an editor or a copy can drop or change it, and the test then checks something other than it says."""
import unicodedata
from pathlib import Path

import pytest

from apolaki.security.normalize import _LOOKALIKES

TESTS = Path(__file__).resolve().parent
_LOOK = set(_LOOKALIKES)


def hidden(c: str) -> bool:
    """Invisible (format and control characters, spaces other than U+0020, combining marks, tag and private-use
    characters, the Hangul fillers) or a look-alike (normalize's Cyrillic and Greek table, the fullwidth forms)."""
    cat, o = unicodedata.category(c), ord(c)
    return (cat in ("Cf", "Zl", "Zp", "Co", "Cs", "Mn", "Me") or (cat == "Zs" and c != " ")
            or (cat == "Cc" and c not in "\t\n\r") or 0xE0000 <= o <= 0xE007F or o in _LOOK
            or 0xFF01 <= o <= 0xFF5E or c in "\u115f\u1160\u3164\uffa0")


@pytest.mark.parametrize("path", sorted(TESTS.rglob("*.py")), ids=lambda p: str(p.relative_to(TESTS)))
def test_a_test_source_spells_hidden_characters_as_escapes(path):
    found = [f"line {i}: U+{ord(c):04X} {unicodedata.name(c, '')}"
             for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1) for c in line if hidden(c)]
    assert found == [], found


def test_the_guard_can_fire():
    assert all(hidden(c) for c in "\u200b\u00ad\u0406\uff29\u00a0\U000e0041\u0301\ue000\u2060\u3164")
    assert not any(hidden(c) for c in "aZ09 '\u00e9\u2014\u2019")
