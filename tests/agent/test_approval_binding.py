"""An approval is of the exact text that was queued and checked (2026-11-02 review, REPORT section 5 items 8 and 9).

Before this, review_item wrote a status with no hash, so an item edited on disk after queueing was approved as edited,
and an item whose own ethics verdict was "blocked" could be approved like any other."""
import hashlib
import json
from datetime import datetime, timezone

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("APOLAKI_BRAND_FILE", raising=False)
    return tmp_path / "home"


CLEAN = "Our tenant clinic opens Monday at the library."
BLOCKED = "Act now, last chance to donate!"


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def path_of(home, item_id):
    found = [p for p in (home / "approval-queue").glob("*.json") if json.loads(p.read_text())["id"] == item_id]
    assert len(found) == 1, found
    return found[0]


def on_disk(home, item_id):
    return json.loads(path_of(home, item_id).read_text())


def edit_on_disk(home, item_id, **fields):
    p = path_of(home, item_id)
    item = json.loads(p.read_text())
    item.update(fields)
    p.write_text(json.dumps(item))


# ---- the hash is recorded at queueing ------------------------------------------------------------------------------
def test_the_queue_records_the_sha256_of_the_exact_content(home):
    from apolaki.agent.agent import queue_for_approval
    item_id = queue_for_approval(CLEAN, "social")
    assert on_disk(home, item_id)["content_sha256"] == sha(CLEAN)


@pytest.mark.parametrize("field", ["content", "content_sha256", "status", "ethics_verdict", "id"])
def test_extra_fields_cannot_overwrite_the_queues_own(home, field):
    """extra was merged last, so extra={"content": ...} would have written text the hash and the check never saw."""
    from apolaki.agent.agent import queue_for_approval
    with pytest.raises(ValueError, match=field):
        queue_for_approval(CLEAN, "social", extra={field: "something else"})
    assert not list((home / "approval-queue").glob("*.json"))


def test_two_items_queued_in_the_same_second_both_survive(home, monkeypatch):
    """The id is the second it was queued in; the second write used to replace the first file."""
    from apolaki.agent import agent as A

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 20, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(A, "datetime", Frozen)
    first = A.queue_for_approval("first draft", "social")
    second = A.queue_for_approval("second draft", "social")
    assert first != second
    assert on_disk(home, first)["content"] == "first draft" and on_disk(home, second)["content"] == "second draft"
    assert A.review_item(first, "approved")["content"] == "first draft"
    assert A.review_item(second, "rejected")["content"] == "second draft"


def frozen_clock(monkeypatch, A):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 2, 20, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(A, "datetime", Frozen)


def test_items_of_different_types_queued_in_the_same_second_get_different_ids(home, monkeypatch):
    """review_item finds an item by its id across content types, so two types can't share one."""
    from apolaki.agent import agent as A
    frozen_clock(monkeypatch, A)
    social = A.queue_for_approval("a post", "social")
    blog = A.queue_for_approval("a blog post", "blog")
    assert social != blog
    assert A.review_item(social, "approved")["content"] == "a post"
    assert A.review_item(blog, "approved")["content"] == "a blog post"


def test_a_file_written_between_the_id_check_and_the_write_is_not_replaced(home, monkeypatch):
    """Another process can queue in that window; the write is exclusive, so it moves on to the next id."""
    from apolaki.agent import agent as A
    frozen_clock(monkeypatch, A)
    first = A.queue_for_approval("first draft", "social")
    monkeypatch.setattr(A, "_queue_paths", lambda item_id: [])       # the check sees nothing, as in the race
    second = A.queue_for_approval("second draft", "social")
    assert first != second
    contents = sorted(json.loads(p.read_text())["content"] for p in (home / "approval-queue").glob("*.json"))
    assert contents == ["first draft", "second draft"]


# ---- the content type goes into a file name, so it is a closed set of characters (2026-11-03 design read) ----------
BAD_TYPES = ["../outside", "..", "a/b", "a\\b", "", ".hidden", "so cial", "social\n", "social\x00", "x" * 41,
             "-social", "social.json"]


@pytest.mark.parametrize("content_type", BAD_TYPES, ids=repr)
def test_a_content_type_that_isnt_a_plain_name_is_refused_and_nothing_is_written(home, content_type):
    from apolaki.agent import agent as A
    with pytest.raises(ValueError, match="content type"):
        A.queue_for_approval("a post", content_type)
    written = [p for p in home.rglob("*") if p.is_file()]
    assert written == [], written


@pytest.mark.parametrize("content_type", ["social", "grant", "blog_post", "web-page", "LinkedIn", "x" * 40, "unknown"])
def test_a_plain_content_type_is_queued(home, content_type):
    from apolaki.agent import agent as A
    item_id = A.queue_for_approval("a post", content_type)
    assert path_of(home, item_id).name == f"{item_id}_{content_type}.json"


def test_a_brief_with_a_bad_content_type_is_refused_before_the_model_is_called(home, monkeypatch):
    from apolaki.agent import agent as A
    monkeypatch.setattr(A, "chat", lambda *a, **k: pytest.fail("the model was called"))
    class Memory:
        def search(self, query, n_results=6):
            return []
    agent = object.__new__(A.ApolakiAgent)
    agent.memory, agent.history, agent.auto_capture, agent.house_rules_count = Memory(), [], False, 0
    with pytest.raises(ValueError, match="content type"):
        agent.draft_content("Announce the clinic.", content_type="../../etc/x")


def test_the_discord_hook_refuses_a_bad_content_type_before_writing(home, monkeypatch):
    """It writes long drafts to approval-queue/<id>_<type>.md, the same path shape."""
    from apolaki.agent import discord_hook as D
    monkeypatch.setattr(D, "DISCORD_TOKEN", "test-token-not-real")
    monkeypatch.setattr(D, "ADMIN_CHANNEL_ID", "123")
    monkeypatch.setattr(D, "APPROVAL_DIR", home / "approval-queue")
    monkeypatch.setattr(D.requests, "post", lambda *a, **k: pytest.fail("posted"))
    with pytest.raises(ValueError, match="content type"):
        D.post_for_review("x" * 3000, content_type="../outside", queue_id="20261103_000000")
    assert not [p for p in home.rglob("*") if p.is_file()]


# ---- review_item checks the hash before it records an approval -----------------------------------------------------
def test_an_unedited_item_is_approved_and_the_approval_names_the_hash(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    item = review_item(item_id, "approved", "good", "the comms lead")
    assert item["status"] == "approved" and item.get("approved_content_sha256") == sha(CLEAN)
    assert on_disk(home, item_id).get("approved_content_sha256") == sha(CLEAN)


def test_an_item_edited_on_disk_after_queueing_is_not_approved(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, content=CLEAN + " Free lunch for everyone who comes.")
    with pytest.raises(ValueError, match="changed since it was queued"):
        review_item(item_id, "approved", "fine", "the comms lead")
    after = on_disk(home, item_id)
    assert after["status"] == "pending" and "approved_content_sha256" not in after and "reviewed_at" not in after


def test_the_refusal_says_how_to_requeue(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, content="edited")
    with pytest.raises(ValueError, match=f"requeue {item_id}"):
        review_item(item_id, "approved")


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_a_rejection_of_an_edited_item_is_still_recorded(home, decision):
    """Only an approval vouches for the text; turning down changed text is harmless and worth recording."""
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, content="edited")
    try:
        item = review_item(item_id, decision, "no")
    except ValueError as e:
        pytest.fail(f"a {decision} of changed text was refused: {e}")
    assert item["status"] == decision


def test_an_item_with_no_recorded_hash_is_not_approved(home):
    """Items queued before this change carry no hash: what they hold now can't be shown to be what was queued."""
    from apolaki.agent.agent import review_item
    d = home / "approval-queue"
    d.mkdir(parents=True)
    (d / "20261016_130000_social.json").write_text(json.dumps(
        {"id": "20261016_130000", "content": CLEAN, "content_type": "social", "status": "pending",
         "ethics_verdict": "approved", "ethics_reason": "No ethics concerns"}))
    with pytest.raises(ValueError, match="no content_sha256"):
        review_item("20261016_130000", "approved")
    try:
        assert review_item("20261016_130000", "rejected")["status"] == "rejected"
    except ValueError as e:
        pytest.fail(f"a rejection of an item with no hash was refused: {e}")


def test_content_that_is_not_text_is_not_approved(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, content=["not", "text"])
    with pytest.raises(ValueError, match="changed since it was queued"):
        review_item(item_id, "approved")


# ---- a blocked item needs an override note, and the override is recorded ------------------------------------------
def test_a_blocked_item_is_not_approved_without_an_override_note(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(BLOCKED, "social")
    assert on_disk(home, item_id)["ethics_verdict"] == "blocked"
    with pytest.raises(ValueError, match="override"):
        review_item(item_id, "approved", "looks fine", "the comms lead")
    assert on_disk(home, item_id)["status"] == "pending"


def test_an_override_is_recorded_with_its_note_who_and_the_block_it_overrode(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(BLOCKED, "social")
    item = review_item(item_id, "approved", "ok", "the comms lead", override="the deadline is real: the venue closes")
    o = item.get("ethics_override")
    assert item["status"] == "approved" and isinstance(o, dict), item
    assert o["note"] == "the deadline is real: the venue closes" and o["by"] == "the comms lead"
    assert o["verdict"] == "blocked" and "false_urgency" in o["reason"] and o["at"]
    assert on_disk(home, item_id).get("ethics_override") == o


def test_an_override_must_name_who_made_it(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(BLOCKED, "social")
    with pytest.raises(ValueError, match="who"):
        review_item(item_id, "approved", override="the deadline is real")
    assert on_disk(home, item_id)["status"] == "pending"


def test_a_blocked_verdict_comes_from_the_content_not_only_the_stored_label(home):
    """The label is a field on disk like the content; the check is run again on the text being approved."""
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(BLOCKED, "social")
    edit_on_disk(home, item_id, ethics_verdict="approved", ethics_reason="No ethics concerns")
    with pytest.raises(ValueError, match="override"):
        review_item(item_id, "approved", "ok", "the comms lead")


def test_a_stored_blocked_label_holds_even_if_todays_check_passes_the_text(home):
    """Stricter wins: a block recorded at queueing isn't lifted by a later, looser check."""
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, ethics_verdict="blocked", ethics_reason="Dark pattern detected: false_urgency")
    with pytest.raises(ValueError, match="override"):
        review_item(item_id, "approved", "ok", "the comms lead")


def test_an_override_note_on_anything_but_an_approval_is_refused(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(BLOCKED, "social")
    with pytest.raises(ValueError, match="only to an approval"):
        review_item(item_id, "rejected", "no", "the comms lead", override="why")


def test_a_clean_item_needs_no_override_and_records_none(home):
    from apolaki.agent.agent import queue_for_approval, review_item
    item_id = queue_for_approval(CLEAN, "social")
    assert "ethics_override" not in review_item(item_id, "approved", "", "the comms lead")


# ---- re-queueing: the edited text becomes a new item with its own check and hash -----------------------------------
def test_requeue_makes_a_new_item_from_the_edited_text_and_supersedes_the_old(home):
    from apolaki.agent.agent import queue_for_approval, requeue_item, review_item
    item_id = queue_for_approval(CLEAN, "social", context="the brief")
    edited = CLEAN + " Bring a photo ID."
    edit_on_disk(home, item_id, content=edited)
    new_id = requeue_item(item_id)
    new, old = on_disk(home, new_id), on_disk(home, item_id)
    assert new_id != item_id and new["content"] == edited and new["content_sha256"] == sha(edited)
    assert new["status"] == "pending" and new.get("requeued_from") == item_id and new["context"] == "the brief"
    assert new["content_type"] == "social" and "pass" in new.get("style", {})
    assert old["status"] == "superseded" and old.get("superseded_by") == new_id and old.get("status_before") == "pending"
    assert review_item(new_id, "approved", "", "the comms lead").get("approved_content_sha256") == sha(edited)


def test_requeue_runs_the_ethics_check_on_the_edited_text(home):
    from apolaki.agent.agent import queue_for_approval, requeue_item
    item_id = queue_for_approval(CLEAN, "social")
    edit_on_disk(home, item_id, content=BLOCKED)
    assert on_disk(home, requeue_item(item_id))["ethics_verdict"] == "blocked"


def test_a_superseded_item_is_not_approved_or_requeued_again(home):
    from apolaki.agent.agent import queue_for_approval, requeue_item, review_item
    item_id = queue_for_approval(CLEAN, "social")
    new_id = requeue_item(item_id)            # unedited: the old item's hash still matches
    with pytest.raises(ValueError, match=f"superseded by {new_id}"):
        review_item(item_id, "approved")
    with pytest.raises(ValueError, match=f"superseded by {new_id}"):
        requeue_item(item_id)


# ---- the CLI -------------------------------------------------------------------------------------------------------
def test_the_review_cli_passes_an_override_and_requeue_is_a_command(home, monkeypatch, capsys):
    import apolaki.engine as E
    from apolaki.agent import agent as A
    seen = {}
    monkeypatch.setattr(A, "review_item", lambda *a, **k: seen.update(review=(a, k)) or {"id": a[0], "status": a[1]})
    monkeypatch.setattr(A, "requeue_item", lambda item_id: seen.update(requeue=item_id) or "NEW")
    assert E.main(["review", "Q1", "approved", "ok", "--by", "Ana", "--override", "the deadline is real"]) == 0
    assert seen["review"] == (("Q1", "approved", "ok", "Ana"), {"override": "the deadline is real"})
    assert E.main(["requeue", "Q1"]) == 0
    assert seen["requeue"] == "Q1" and "NEW" in capsys.readouterr().out


def test_the_review_cli_reports_a_refusal_and_exits_nonzero(home, capsys):
    import apolaki.engine as E
    from apolaki.agent.agent import queue_for_approval
    item_id = queue_for_approval(BLOCKED, "social")
    assert E.main(["review", item_id, "approved", "ok", "--by", "Ana"]) == 2
    assert "override" in capsys.readouterr().err
    assert on_disk(home, item_id)["status"] == "pending"
