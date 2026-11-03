"""The fact checker reads all of a draft, or says plainly how much it read (2026-11-02 review, REPORT section 5 item 19).

Before: check_document sent text[:6000] and said nothing, so a 1,500-word concept paper was checked only up to about
its middle and reported as checked. A claim list cut off at the output budget was printed as a warning and then
returned as if it were the whole list."""
import json

import pytest

from apolaki.agent import fact_checker as fc


class Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def answer(claims, done_reason="stop"):
    return {"message": {"content": json.dumps(claims)}, "done_reason": done_reason}


def fake_model(monkeypatch, bodies=None):
    """Records each request's document text; answers each call with one claim naming its call number, or with the
    scripted bodies in order."""
    sent = []
    scripted = list(bodies) if bodies is not None else None

    def post(url, json=None, timeout=None):
        sent.append(json["messages"][0]["content"])
        if scripted is not None:
            body = scripted.pop(0)
        else:
            body = answer([{"claim": f"claim from call {len(sent)}", "classification": "SUSPECT", "reason": "r",
                            "priority": "HIGH"}])
        return Resp(body)
    monkeypatch.setattr(fc.requests, "post", post)
    return sent


def paragraphs(n, size=2500, marker_at=None):
    paras = []
    for i in range(n):
        body = f"Paragraph {i}. " + ("We served families across the county this year. " * 80)
        if marker_at == i:
            body = body[: size // 2] + f" MARKER-{i} " + body[size // 2:]
        paras.append(body[:size])
    return "\n\n".join(paras)


# ---- splitting: every character is in exactly one part, and no part is over the size ------------------------------
@pytest.mark.parametrize("text", [
    paragraphs(7),                                         # paragraphs
    "One long paragraph with no breaks. " * 900,           # sentences only
    "x" * 20000,                                           # nothing to break on
    "short",
    "line one\nline two\n" * 1200,                          # lines only
], ids=["paragraphs", "sentences", "unbroken", "short", "lines"])
def test_the_parts_cover_every_character_once_and_none_is_over_the_size(text):
    spans = fc.split_document(text)
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert all(a < b for a, b in spans) and all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))
    assert all(b - a <= fc.CHUNK_CHARS for a, b in spans)
    assert "".join(text[a:b] for a, b in spans) == text


def test_parts_break_at_paragraphs_when_they_can():
    text = paragraphs(7)
    for a, b in fc.split_document(text)[:-1]:
        assert text[b - 2:b] == "\n\n", repr(text[b - 20:b + 5])


def test_an_empty_document_has_no_parts():
    assert fc.split_document("") == [] and fc.split_document("  \n ") == []


# ---- checking: all of it, in parts --------------------------------------------------------------------------------
def test_a_long_draft_is_checked_to_its_last_character(monkeypatch):
    text = paragraphs(7, marker_at=6)                      # about 17,500 characters; the marker sits near the end
    assert len(text) > 2 * fc.CHUNK_CHARS and text.index("MARKER-6") > fc.CHUNK_CHARS
    sent = fake_model(monkeypatch)
    claims = fc.check_document(text)
    assert any("MARKER-6" in s for s in sent)
    sent_docs = "".join(s.split("DOCUMENT:\n", 1)[1].split("\n", 1)[1] for s in sent)
    assert sent_docs == text                                # every part, in order, nothing dropped
    assert claims is not None and len(claims) == len(sent) == len(fc.split_document(text))
    assert [c.get("part") for c in claims] == list(range(1, len(sent) + 1))


def test_a_short_draft_is_one_call_exactly_as_before(monkeypatch):
    text = "Our clinic served 450 families in 2025."
    sent = fake_model(monkeypatch)
    claims = fc.check_document(text)
    assert sent == [fc.checker_prompt() + text]
    assert claims == [{"claim": "claim from call 1", "classification": "SUSPECT", "reason": "r", "priority": "HIGH"}]


def test_each_part_tells_the_model_which_part_it_is(monkeypatch):
    sent = fake_model(monkeypatch)
    fc.check_document(paragraphs(7))
    n = len(sent)
    assert n > 1 and all(f"[part {i} of {n}]" in s for i, s in enumerate(sent, 1))


# ---- a part that didn't run, or whose list was cut, is never hidden -----------------------------------------------
def test_a_part_that_fails_makes_the_whole_result_none_and_the_parts_say_which(monkeypatch):
    text = paragraphs(7)
    n = len(fc.split_document(text))
    ok = answer([{"claim": "c", "classification": "EXTERNAL", "reason": "r", "priority": "LOW"}])
    bodies = [ok] * n
    bodies[1] = {"error": "model not loaded"}
    fake_model(monkeypatch, bodies)
    out = fc.check_document_parts(text)
    assert out["complete"] is False and out["parts"] == n
    assert [f["part"] for f in out["failed_parts"]] == [2] and "model not loaded" in out["failed_parts"][0]["error"]
    span = fc.split_document(text)[1]
    assert out["failed_parts"][0]["chars"] == [span[0] + 1, span[1]]
    assert out["checked_parts"] == [i for i in range(1, n + 1) if i != 2] and len(out["claims"]) == n - 1
    fake_model(monkeypatch, bodies)
    assert fc.check_document(text) is None


def test_a_claim_list_cut_at_the_output_budget_is_reported_as_incomplete(monkeypatch):
    fake_model(monkeypatch, [answer([{"claim": "c", "classification": "SUSPECT", "reason": "r", "priority": "HIGH"}],
                                    done_reason="length")])
    out = fc.check_document_parts("Our clinic served 450 families.")
    assert out["complete"] is False and out["incomplete_parts"] == [1] and len(out["claims"]) == 1
    fake_model(monkeypatch, [answer([], done_reason="length")])
    assert fc.check_document("Our clinic served 450 families.") is None


@pytest.mark.parametrize("body", [{"message": {"content": "no json here"}}, {"message": {"content": ""}},
                                  {"message": {"content": "[not json"}}, {"message": {"content": '{"a": 1}'}}])
def test_an_unreadable_answer_is_a_failed_part(monkeypatch, body):
    fake_model(monkeypatch, [body])
    out = fc.check_document_parts("Our clinic served 450 families.")
    assert out["complete"] is False and [f["part"] for f in out["failed_parts"]] == [1]


def test_an_empty_document_is_not_reported_as_checked(monkeypatch):
    sent = fake_model(monkeypatch)
    assert fc.check_document("   ") is None and sent == []
    out = fc.check_document_parts("   ")
    assert out["complete"] is False and out["parts"] == 0


# ---- the report says plainly how much it read ---------------------------------------------------------------------
def test_the_report_says_it_checked_all_of_it(monkeypatch, tmp_path, capsys):
    f = tmp_path / "draft.md"
    f.write_text(paragraphs(7))
    fake_model(monkeypatch)
    report = fc.check_file(str(f))
    out = capsys.readouterr().out
    assert report["checked"] is True and report["partial"] is False and report["chars"] == len(f.read_text())
    assert f"Checked all of it: {len(f.read_text()):,} characters in {report['parts']} parts" in out


def test_the_report_says_plainly_when_it_checked_only_part(monkeypatch, tmp_path, capsys):
    f = tmp_path / "draft.md"
    text = paragraphs(7)
    f.write_text(text)
    n = len(fc.split_document(text))
    ok = answer([{"claim": "c", "classification": "SUSPECT", "reason": "r", "priority": "HIGH"}])
    fake_model(monkeypatch, [ok, {"error": "timed out"}] + [ok] * (n - 2))
    report = fc.check_file(str(f))
    out = capsys.readouterr().out
    span = fc.split_document(text)[1]
    assert report["checked"] is False and report["partial"] is True
    assert "CHECKED ONLY PART OF IT" in out and f"characters {span[0] + 1:,}-{span[1]:,}" in out and "timed out" in out
    assert "only from the parts that ran" in out
    assert len(report["suspect"]) == n - 1


def test_the_report_says_when_nothing_ran(monkeypatch, tmp_path, capsys):
    f = tmp_path / "draft.md"
    f.write_text("Our clinic served 450 families.")
    fake_model(monkeypatch, [{"error": "connection refused"}])
    report = fc.check_file(str(f))
    out = capsys.readouterr().out
    assert report["checked"] is False and report["partial"] is False and report["total_claims"] is None
    assert "CHECK DID NOT RUN" in out


def test_the_report_on_an_empty_file_says_nothing_was_checked(monkeypatch, tmp_path, capsys):
    f = tmp_path / "draft.md"
    f.write_text("\n")
    fake_model(monkeypatch)
    report = fc.check_file(str(f))
    assert report["checked"] is False and "empty" in capsys.readouterr().out.lower()
