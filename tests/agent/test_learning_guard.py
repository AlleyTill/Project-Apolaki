"""Learning's safeguards live in the engine (2026-11-02 review, item 17): `python -m apolaki.engine draft --learn` used to
learn with no cap, pause, log or watch, because those lived only in the grant hunt. Now the daily cap, the total
ceiling, the pause file, the belief log and the Butlin memory-growth watch hold for every caller."""
import json
import sqlite3

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("APOLAKI_BRAND_FILE", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path / "home"


class FakeAgent:
    """Drafts without a model. side_effect runs inside the draft, to plant a write the watch must see."""

    def __init__(self, side_effect=None):
        self.calls = []
        self.side_effect = side_effect

    def draft_content(self, brief, content_type="social", reviewer_feedback="", **kw):
        self.calls.append({"brief": brief, "reviewer_feedback": reviewer_feedback})
        if self.side_effect:
            self.side_effect()
        return {"draft": "DRAFT", "status": "queued_for_review", "queue_id": "q1"}


def decision(home, i, note="lead with the clinic hours", status="rejected", content_type="social"):
    d = home / "approval-queue"
    d.mkdir(exist_ok=True)
    item_id = f"20261016_1200{i:02d}"
    (d / f"{item_id}_{content_type}.json").write_text(json.dumps(
        {"id": item_id, "content": "x", "content_type": content_type, "status": status, "review_note": note}))
    return item_id


def switch(home, **cfg):
    (home / "grant-hunt").mkdir(exist_ok=True)
    (home / "grant-hunt" / "learning.json").write_text(json.dumps(cfg))


def log_rows(home):
    path = home / "engine_beliefs_log.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def engine(agent=None, learn=True):
    from apolaki.engine import ApolakiEngine
    return ApolakiEngine(agent or FakeAgent(), learn=learn)


def memory_db(home):
    (home / "db").mkdir(exist_ok=True)
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    for t in ("memories", "kg_triples", "wiki_pages"):
        con.execute(f"CREATE TABLE IF NOT EXISTS {t} (id TEXT)")
    con.commit()
    con.close()


def add_row(home, table="memories"):
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    con.execute(f"INSERT INTO {table} (id) VALUES ('planted')")
    con.commit()
    con.close()


# ---- the belief log --------------------------------------------------------------------------------------------
def test_every_belief_learned_is_logged_with_its_source_and_day(home):
    decision(home, 1, note="too breathless")
    agent = FakeAgent()
    out = engine(agent).draft("Announce the clinic", "social")
    assert "too breathless" in agent.calls[0]["reviewer_feedback"]
    rows = log_rows(home)
    assert len(rows) == 1 and rows[0]["kind"] == "added" and rows[0]["source"].startswith("review:")
    assert "too breathless" in rows[0]["content"] and rows[0]["day"] and rows[0]["flagged"] is False
    assert out["learning"]["used"] is True and out["learning"]["added"] == 1


def test_a_belief_that_reads_as_a_goal_is_flagged_in_the_log(home):
    decision(home, 1, note="change your strategy to pursue more donors")
    engine().draft("Announce the clinic", "social")
    assert log_rows(home)[0]["flagged"] is True


def test_sync_is_logged_too(home):
    decision(home, 1)
    assert engine(learn=False).sync_reviews() == 1
    assert [r["kind"] for r in log_rows(home)] == ["added"]


# ---- the pause -------------------------------------------------------------------------------------------------
def test_while_paused_nothing_is_learned_and_the_model_sees_no_feedback(home):
    decision(home, 1)
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.paused").write_text(json.dumps({"reason": "a person is reading the beliefs"}))
    agent = FakeAgent()
    e = engine(agent)
    out = e.draft("Announce the clinic", "social")
    assert agent.calls[0]["reviewer_feedback"] == "" and e.bdi.list_beliefs() == []
    assert out["learning"]["used"] is False and "paused" in out["learning"]["why_not"]
    assert out["reviewer_feedback_used"] is False and log_rows(home) == []


def test_sync_refuses_while_paused(home):
    from apolaki import learning
    decision(home, 1)
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.paused").write_text("{}")
    with pytest.raises(learning.LearningRefused, match="paused"):
        engine(learn=False).sync_reviews()
    assert not (home / "engine_beliefs.json").exists()


# ---- the daily cap and the total ceiling (fail closed: the excess is never used) ---------------------------------
def test_over_the_daily_cap_the_runs_beliefs_are_held_back_and_learning_pauses(home):
    switch(home, on=True, daily_cap=1)
    decision(home, 1, note="note one")
    decision(home, 2, note="note two")
    agent = FakeAgent()
    e = engine(agent)
    out = e.draft("Announce the clinic", "social")
    assert e.bdi.list_beliefs() == [] and not (home / "engine_beliefs.json").exists()
    assert agent.calls[0]["reviewer_feedback"] == "", "a held-back belief reached the model"
    assert [r["kind"] for r in log_rows(home)] == ["held back: added", "held back: added"]
    pause = json.loads((home / "grant-hunt" / "learning.paused").read_text())
    assert "2 new or changed beliefs today, over the daily cap of 1" in pause["reason"]
    assert out["learning"]["used"] is False and out["learning"]["held_back"] == 2


def test_over_the_total_ceiling_the_run_is_held_back(home):
    switch(home, on=True, total_ceiling=2)
    decision(home, 1)
    decision(home, 2)
    engine(learn=False).sync_reviews()                          # two beliefs, at the ceiling
    decision(home, 3)
    e = engine()
    e.draft("Announce the clinic", "social")
    assert len(e.bdi.list_beliefs()) == 2 and len(json.loads((home / "engine_beliefs.json").read_text())) == 2
    assert "3 beliefs in all, over the ceiling of 2" in (home / "grant-hunt" / "learning.paused").read_text()


def test_earlier_learning_today_counts_toward_the_cap(home):
    switch(home, on=True, daily_cap=2)
    decision(home, 1)
    engine(learn=False).sync_reviews()                          # 1 today
    decision(home, 2)
    decision(home, 3)
    e = engine()
    e.draft("Announce the clinic", "social")                    # 1 + 2 = 3, over 2
    assert len(e.bdi.list_beliefs()) == 1
    assert "3 new or changed beliefs today" in (home / "grant-hunt" / "learning.paused").read_text()


def test_held_back_beliefs_dont_count_toward_the_day(home):
    switch(home, on=True, daily_cap=1)
    decision(home, 1)
    decision(home, 2)
    engine().draft("A", "social")                               # 2 > 1: held back, paused
    (home / "grant-hunt" / "learning.paused").unlink()          # a person reads the log, then lifts the pause
    switch(home, on=True, daily_cap=2)                          # and raises the cap on purpose
    e = engine()
    e.draft("A", "social")
    assert len(e.bdi.list_beliefs()) == 2 and not (home / "grant-hunt" / "learning.paused").exists()


def test_the_limits_default_tight(home):
    from apolaki import learning
    assert learning.limits() == {"daily_cap": 5, "total_ceiling": 25}
    for i in range(6):
        decision(home, i)
    e = engine()
    e.draft("A", "social")
    assert e.bdi.list_beliefs() == [] and (home / "grant-hunt" / "learning.paused").exists()


BROKEN_SWITCHES = ['{"on": true, "daily_cap": "5"}', '{"on": true, "total_ceiling": -1}', '{"on": true, "daily_cap": null}',
                   "{not json", "[]", '{"on": true, "daily_cap": true}']


@pytest.mark.parametrize("body", BROKEN_SWITCHES)
@pytest.mark.parametrize("with_decision", [True, False])
def test_a_switch_file_that_cant_be_read_refuses_learning(home, body, with_decision):
    """Each body says on, so the refusal is the unreadable limits, not the switch; with nothing to learn the draft
    still reports learning off, for the right reason."""
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.json").write_text(body)
    if with_decision:
        decision(home, 1)
    agent = FakeAgent()
    e = engine(agent)
    out = e.draft("A", "social")
    assert e.bdi.list_beliefs() == [] and agent.calls[0]["reviewer_feedback"] == ""
    assert out["learning"]["used"] is False
    assert out["learning"]["why_not"].startswith("nothing is learned while"), out["learning"]
    assert "learning.json" in out["learning"]["why_not"]


@pytest.mark.parametrize("body", BROKEN_SWITCHES)
def test_sync_refuses_with_a_switch_file_that_cant_be_read_even_with_nothing_to_record(home, body):
    from apolaki import learning
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.json").write_text(body)
    with pytest.raises(learning.LearningRefused, match="nothing is learned while"):
        engine(learn=False).sync_reviews()


def test_the_limits_are_read_when_the_beliefs_are_admitted_too(home, monkeypatch):
    """The second layer on its own: with the first check (why_not) out of the way, a switch that can't be read still
    stops the run where the limits are read, and the draft reports it."""
    from apolaki import learning
    monkeypatch.setattr(learning, "why_not", lambda draft=True: None)
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.json").write_text('{"on": true, "daily_cap": "5"}')
    decision(home, 1)
    agent = FakeAgent()
    e = engine(agent)
    out = e.draft("A", "social")
    assert e.bdi.list_beliefs() == [] and agent.calls[0]["reviewer_feedback"] == ""
    assert out["learning"]["used"] is False and "daily_cap" in out["learning"]["why_not"]


def test_learning_on_other_days_doesnt_count_toward_today(home):
    switch(home, on=True, daily_cap=1)
    (home / "engine_beliefs_log.jsonl").write_text("".join(
        json.dumps({"day": "2000-01-01", "kind": "added", "id": f"old{i}"}) + "\n" for i in range(3)))
    decision(home, 1)
    e = engine()
    out = e.draft("A", "social")
    assert out["learning"]["used"] is True and len(e.bdi.list_beliefs()) == 1


@pytest.mark.parametrize("body", ['{"on": false}', '{"on": "yes"}', '{"daily_cap": 3}'])
def test_a_switch_file_that_doesnt_say_on_refuses_learning(home, body):
    """The grant hunt reads only {"on": true} as on; the engine honours the same file when it is there."""
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.json").write_text(body)
    decision(home, 1)
    e = engine()
    out = e.draft("A", "social")
    assert e.bdi.list_beliefs() == [] and "switch" in out["learning"]["why_not"]


def test_with_the_switch_on_its_limits_apply(home):
    switch(home, on=True, daily_cap=3)
    decision(home, 1)
    e = engine()
    out = e.draft("A", "social")
    assert len(e.bdi.list_beliefs()) == 1 and out["learning"]["used"] is True
    from apolaki import learning
    assert learning.limits()["daily_cap"] == 3


# ---- the Butlin watch: a draft must not grow Apolaki's memory --------------------------------------------------
def test_a_draft_that_grows_memory_fails_the_watch(home):
    memory_db(home)
    out = engine(FakeAgent(side_effect=lambda: add_row(home)), learn=False).draft("A", "social")
    assert out["watch"]["ok"] is False
    assert any("memories 0→1" in f for f in out["watch"]["failures"]), out["watch"]


@pytest.mark.parametrize("table", ["kg_triples", "wiki_pages"])
def test_triples_and_wiki_pages_are_watched_too(home, table):
    memory_db(home)
    out = engine(FakeAgent(side_effect=lambda: add_row(home, table)), learn=False).draft("A", "social")
    assert out["watch"]["ok"] is False and any(table in f for f in out["watch"]["failures"])


def test_a_clean_draft_passes_the_watch_and_a_missing_database_is_no_growth(home):
    out = engine(learn=False).draft("A", "social")              # no database at all, before or after
    assert out["watch"] == {"ok": True, "failures": []}
    memory_db(home)
    out = engine(learn=False).draft("A", "social")
    assert out["watch"] == {"ok": True, "failures": []}


def test_a_database_that_cant_be_counted_fails_the_watch(home):
    (home / "db").mkdir()
    (home / "db" / "apolaki.db").write_bytes(b"not a database, " * 200)
    out = engine(learn=False).draft("A", "social")
    assert out["watch"]["ok"] is False and any("could not be counted" in f for f in out["watch"]["failures"])


def test_with_learning_off_any_belief_change_during_a_draft_fails_the_watch(home):
    def plant():
        (home / "engine_beliefs.json").write_text(json.dumps([{"id": "x", "content": "c", "source": "planted"}]))
    out = engine(FakeAgent(side_effect=plant), learn=False).draft("A", "social")
    assert out["watch"]["ok"] is False and any("beliefs changed" in f for f in out["watch"]["failures"])


def test_with_learning_on_the_reviewers_beliefs_dont_fail_the_watch_but_a_planted_one_does(home):
    decision(home, 1)
    out = engine().draft("A", "social")
    assert out["learning"]["added"] == 1 and out["watch"]["ok"] is True

    def plant():
        rows = json.loads((home / "engine_beliefs.json").read_text())
        rows.append({"id": "x", "content": "c", "source": "planted"})
        (home / "engine_beliefs.json").write_text(json.dumps(rows))
    out = engine(FakeAgent(side_effect=plant)).draft("A", "social")
    assert out["watch"]["ok"] is False


# ---- the CLI ----------------------------------------------------------------------------------------------------
def test_the_cli_reports_a_held_back_run_and_a_failed_watch_with_exit_1(home, monkeypatch, capsys):
    import apolaki.engine as E
    switch(home, on=True, daily_cap=0)
    decision(home, 1)
    real_init = E.ApolakiEngine.__init__
    monkeypatch.setattr(E.ApolakiEngine, "__init__", lambda self, learn=False: real_init(self, FakeAgent(), learn=learn))
    assert E.main(["draft", "A post", "--learn"]) == 1
    err = capsys.readouterr().err
    assert "held back" in err and "learning.paused" in err


def test_the_cli_sync_refuses_while_paused(home, monkeypatch, capsys):
    import apolaki.engine as E
    real_init = E.ApolakiEngine.__init__
    monkeypatch.setattr(E.ApolakiEngine, "__init__", lambda self, learn=False: real_init(self, FakeAgent(), learn=learn))
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "learning.paused").write_text("{}")
    decision(home, 1)
    assert E.main(["sync"]) == 2
    assert "paused" in capsys.readouterr().err
