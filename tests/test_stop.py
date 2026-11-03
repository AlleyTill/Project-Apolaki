"""The STOP file: a person stops Apolaki's scheduled work between steps (2026-11-02 review, item 16: the grant hunt
posts every night unwatched and had no documented way to stop it)."""
import json

import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("APOLAKI_BRAND_FILE", raising=False)
    return tmp_path / "home"


def plant_stop(home, text="stopping for the night: a person is reading the drafts"):
    home.mkdir(parents=True, exist_ok=True)
    (home / "STOP").write_text(text)


def test_without_a_stop_file_every_step_may_run(home):
    from apolaki import stop
    assert stop.stop_reason() is None
    stop.check("hunt")                                         # no exception


def test_with_a_stop_file_a_step_is_refused_with_its_reason(home):
    from apolaki import stop
    plant_stop(home)
    with pytest.raises(stop.StopRequested) as e:
        stop.check("triage")
    assert e.value.step == "triage"
    assert "stopping for the night" in str(e.value) and str(home / "STOP") in str(e.value)


def test_a_job_that_checks_before_each_step_stops_at_the_next_one(home):
    """The shape the grant hunt takes: check(step) before every step. A STOP planted during step 2 stops step 3."""
    from apolaki import stop
    ran = []

    def job():
        for step in ("hunt", "watch", "triage", "draft", "deliver"):
            stop.check(step)
            ran.append(step)
            if step == "watch":
                plant_stop(home)                               # a person touches STOP while the watch runs
    with pytest.raises(stop.StopRequested) as e:
        job()
    assert ran == ["hunt", "watch"] and e.value.step == "triage"
    (home / "STOP").unlink()                                   # the person lifts it
    ran.clear()
    with pytest.raises(stop.StopRequested):                    # planted again during watch, as before
        job()
    assert ran == ["hunt", "watch"]


@pytest.mark.parametrize("kind", ["empty", "directory", "unreadable"])
def test_any_stop_file_stops_even_one_that_cant_be_read(home, kind):
    """Fail closed: a STOP a person made in a hurry (empty, a folder, no read permission) still stops."""
    from apolaki import stop
    home.mkdir(parents=True)
    path = home / "STOP"
    if kind == "directory":
        path.mkdir()
    else:
        path.write_text("" if kind == "empty" else "secret reason")
        if kind == "unreadable":
            path.chmod(0)
    try:
        assert stop.stop_reason()
        with pytest.raises(stop.StopRequested):
            stop.check("draft")
    finally:
        if kind == "unreadable":
            path.chmod(0o600)


class FakeAgent:
    def __init__(self):
        self.calls = []

    def draft_content(self, brief, content_type="social", reviewer_feedback="", **kw):
        self.calls.append(brief)
        return {"draft": "DRAFT", "status": "queued_for_review", "queue_id": "q1"}


def test_the_engine_refuses_to_draft_while_stop_exists_before_any_model_call(home):
    from apolaki import stop
    from apolaki.engine import ApolakiEngine
    q = home / "approval-queue"
    q.mkdir(parents=True)
    (q / "20261016_120000_social.json").write_text(json.dumps(
        {"id": "20261016_120000", "content": "x", "content_type": "social", "status": "rejected", "review_note": "n"}))
    plant_stop(home)
    agent = FakeAgent()
    e = ApolakiEngine(agent, learn=True)
    with pytest.raises(stop.StopRequested) as err:
        e.draft("Announce the clinic", "grant")
    assert err.value.step == "draft"
    assert agent.calls == [] and e.bdi.list_intentions() == []
    assert e.bdi.list_beliefs() == [], "a stopped engine still learned"
    (home / "STOP").unlink()
    e.draft("Announce the clinic", "grant")
    assert agent.calls == ["Announce the clinic"]


def test_the_engine_cli_says_it_stopped_and_how_to_resume(home, monkeypatch, capsys):
    """Through the real ApolakiEngine.draft, with only the agent faked: exit 3, the file named, the way back given."""
    import apolaki.engine as E
    agent = FakeAgent()
    real_init = E.ApolakiEngine.__init__
    monkeypatch.setattr(E.ApolakiEngine, "__init__", lambda self, learn=False: real_init(self, agent, learn=learn))
    plant_stop(home)
    assert E.main(["draft", "A post"]) == 3
    err = capsys.readouterr().err
    assert "stopped" in err and str(home / "STOP") in err and "python -m apolaki.stop clear" in err
    assert agent.calls == []
    (home / "STOP").unlink()
    assert E.main(["draft", "A post"]) == 0 and agent.calls == ["A post"]


def test_the_stop_cli_sets_shows_and_clears_the_file(home, capsys):
    from apolaki import stop
    assert stop.main(["status"]) == 0 and "not stopped" in capsys.readouterr().out
    assert stop.main(["now", "the drafts need a read first", "--by", "the comms lead"]) == 0
    text = (home / "STOP").read_text()
    assert "the drafts need a read first" in text and "the comms lead" in text
    assert stop.main(["status"]) == 1
    out = capsys.readouterr().out
    assert "STOPPED" in out and "the drafts need a read first" in out
    assert stop.main(["clear"]) == 0 and not (home / "STOP").exists()
    assert stop.main(["status"]) == 0


def test_stopping_needs_a_reason_and_a_name(home):
    from apolaki import stop
    with pytest.raises(SystemExit):
        stop.main(["now", "--by", "x"])
    with pytest.raises(ValueError):
        stop.request("", "the comms lead")
    with pytest.raises(ValueError):
        stop.request("a reason", " ")
    assert not (home / "STOP").exists()
