"""THIRD_PARTY_NOTICES.md holds the Unicode License v3 exactly as fetched, and what it covers points to it."""
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
# sha256 of https://www.unicode.org/license.txt as fetched on 2026-11-11 (1,995 bytes, ending with a newline). The
# test's own copy: an edit to the text in the notice, or to the hash written beside it, fails here.
UNICODE_LICENSE_SHA256 = "e7a93b009565cfce55919a381437ac4db883e9da2126fa28b91d12732bc53d96"


def _license_block() -> bytes:
    text = NOTICES.read_text(encoding="utf-8")
    after = text.split("\n## Unicode License v3\n", 1)[1]
    m = re.search(r"\n```text\n(.*?\n)```\n", after, re.S)
    assert m, "the licence's fenced block is missing"
    return m.group(1).encode("utf-8")


def test_the_unicode_license_is_the_fetched_text_byte_for_byte():
    block = _license_block()
    assert len(block) == 1995
    assert hashlib.sha256(block).hexdigest() == UNICODE_LICENSE_SHA256


def test_the_hash_written_in_the_notice_is_the_texts():
    text = NOTICES.read_text(encoding="utf-8")
    written = re.findall(r"`([0-9a-f]{64})`", text.split("\n## Unicode License v3\n", 1)[1])
    assert written == [UNICODE_LICENSE_SHA256]


def test_what_is_derived_from_unicode_data_points_to_the_notice():
    assert "THIRD_PARTY_NOTICES.md" in (ROOT / "README.md").read_text(encoding="utf-8")
    erase = (ROOT / "apolaki" / "agent" / "erase.py").read_text(encoding="utf-8")
    comment = erase[erase.index("The Cherokee pairs are from confusables.txt"):erase.index("_SKELETON = ")]
    assert "THIRD_PARTY_NOTICES.md" in comment
    tests = (ROOT / "tests" / "agent" / "test_erase_person.py").read_text(encoding="utf-8")
    assert "THIRD_PARTY_NOTICES.md" in tests[:tests.index("CHEROKEE_CONFUSABLES = ")].rsplit("\n\n", 1)[1]


def test_the_notice_names_each_derived_table():
    text = NOTICES.read_text(encoding="utf-8").split("\n## Unicode License v3\n", 1)[0]
    for name in ("`apolaki/agent/erase.py`, `_SKELETON`: the 29 Cherokee entries", "`CHEROKEE_CONFUSABLES`",
                 "the 24 small capitals", "`_LOOKALIKE_PAIRS`", "can't be shown"):
        assert name in text, name
