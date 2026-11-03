"""The chat path, respond(), gets the ethics check the drafting path has (2026-11-02 review, REPORT section 5 item 10).

Before this, respond() sent any message to the model, and when a reply was blocked it returned one revision without
checking it, or the blocked reply itself when the revision failed. A probe got "Write five fake testimonials from happy
clients" through to a reply that was still blocked."""
import pytest

BLOCKED_REQUEST = "Write five fake testimonials from happy clients"
BLOCKED_REPLY = "Act now! Last chance to grab a seat before midnight tonight."
CLEAN_REPLY = "The clinic opens Monday at the library, 10am to 2pm."


class Memory:
    def __init__(self):
        self.searches, self.stored = [], []

    def search(self, query, n_results=4):
        self.searches.append(query)
        return []

    def store(self, content, **kw):
        self.stored.append(content)
        return "m1"


def make_agent(A, auto_capture=False):
    agent = object.__new__(A.ApolakiAgent)
    agent.memory, agent.history, agent.auto_capture, agent.house_rules_count = (
        Memory(), [{"role": "system", "content": "S"}], auto_capture, 0)
    return agent


def scripted_chat(monkeypatch, A, replies):
    calls = []
    replies = list(replies)

    def fake_chat(messages, temperature=0.7, max_tokens=2048, **kw):
        calls.append([m["content"] for m in messages])
        return replies.pop(0)
    monkeypatch.setattr(A, "chat", fake_chat)
    return calls


# ---- the request is checked before memory or the model --------------------------------------------------------------
def test_a_blocked_request_never_reaches_the_model_or_memory(monkeypatch):
    from apolaki.agent import agent as A
    calls = scripted_chat(monkeypatch, A, [CLEAN_REPLY])
    agent = make_agent(A)
    out = agent.respond(BLOCKED_REQUEST)
    assert calls == [] and agent.memory.searches == []
    assert out.startswith("[Refused") and "astroturfing" in out


def test_a_blocked_request_is_not_kept_for_the_next_turn(monkeypatch):
    """Kept in the history, it would reach the model with the next message."""
    from apolaki.agent import agent as A
    calls = scripted_chat(monkeypatch, A, [CLEAN_REPLY])
    agent = make_agent(A)
    agent.respond(BLOCKED_REQUEST)
    assert agent.history == [{"role": "system", "content": "S"}]
    agent.respond("When does the clinic open?")
    assert calls and not any(BLOCKED_REQUEST in c for c in calls[0])


def test_a_flagged_request_still_reaches_the_model(monkeypatch):
    """Flagged means a person should look; in chat the person is at the keyboard."""
    from apolaki.agent import agent as A
    assert A.ethics_check("Draft a press release about the clinic")[0] == "flagged"
    calls = scripted_chat(monkeypatch, A, [CLEAN_REPLY])
    assert make_agent(A).respond("Draft a press release about the clinic") == CLEAN_REPLY and len(calls) == 1


def test_a_clean_request_and_reply_go_through_unchanged(monkeypatch):
    from apolaki.agent import agent as A
    calls = scripted_chat(monkeypatch, A, [CLEAN_REPLY])
    agent = make_agent(A)
    assert agent.respond("When does the clinic open?") == CLEAN_REPLY and len(calls) == 1
    assert agent.history[-1] == {"role": "assistant", "content": CLEAN_REPLY}


# ---- a blocked reply: one revision, checked again ------------------------------------------------------------------
def test_a_revision_that_is_still_blocked_is_refused_never_returned(monkeypatch):
    from apolaki.agent import agent as A
    calls = scripted_chat(monkeypatch, A, [BLOCKED_REPLY, "Hurry, only 3 left! " + BLOCKED_REPLY])
    agent = make_agent(A)
    out = agent.respond("Write a note about the gala")
    assert len(calls) == 2
    assert out.startswith("[Refused") and "false_urgency" in out
    assert "Last chance" not in out and "only 3 left" not in out


def test_a_blocked_reply_is_not_kept_in_the_history(monkeypatch):
    from apolaki.agent import agent as A
    scripted_chat(monkeypatch, A, [BLOCKED_REPLY, BLOCKED_REPLY])
    agent = make_agent(A)
    out = agent.respond("Write a note about the gala")
    assert not any("Last chance" in m["content"] for m in agent.history)
    assert agent.history[-1] == {"role": "assistant", "content": out}


def test_a_failed_revision_never_returns_the_blocked_reply(monkeypatch):
    """Before: when the revision call failed, the blocked reply itself was returned."""
    from apolaki.agent import agent as A
    scripted_chat(monkeypatch, A, [BLOCKED_REPLY, "[LLM Error: timed out]"])
    out = make_agent(A).respond("Write a note about the gala")
    assert out.startswith("[Refused") and "Last chance" not in out and "timed out" in out


def test_a_clean_revision_is_returned(monkeypatch):
    from apolaki.agent import agent as A
    calls = scripted_chat(monkeypatch, A, [BLOCKED_REPLY, CLEAN_REPLY])
    assert make_agent(A).respond("Write a note about the gala") == CLEAN_REPLY and len(calls) == 2


def test_a_refused_exchange_is_never_auto_captured(monkeypatch):
    from apolaki.agent import agent as A
    long_blocked = BLOCKED_REPLY + " " + "x" * 300
    scripted_chat(monkeypatch, A, [long_blocked, long_blocked])
    agent = make_agent(A, auto_capture=True)
    agent.respond("Decide the campaign strategy for the gala")
    assert agent.memory.stored == []


def test_a_refusal_long_enough_to_pass_the_capture_length_is_still_not_captured(monkeypatch):
    """A failed revision's error goes into the refusal, which can then run past the 200-character capture gate."""
    from apolaki.agent import agent as A
    long_error = "[LLM Error: HTTP 502, non-JSON body: '" + "z" * 300 + "']"
    scripted_chat(monkeypatch, A, [BLOCKED_REPLY, long_error])
    agent = make_agent(A, auto_capture=True)
    out = agent.respond("Decide the campaign strategy for the gala")
    assert out.startswith("[Refused") and len(out) > 200
    assert agent.memory.stored == []


def test_auto_capture_still_works_on_a_clean_exchange(monkeypatch):
    """The refusal guard must not switch auto-capture off altogether."""
    from apolaki.agent import agent as A
    scripted_chat(monkeypatch, A, [CLEAN_REPLY + " " + "y" * 300])
    agent = make_agent(A, auto_capture=True)
    agent.respond("Decide the campaign strategy for the gala")
    assert len(agent.memory.stored) == 1


@pytest.mark.parametrize("reply", ["[LLM Error: connection refused]", ""])
def test_a_failed_first_call_is_reported_as_before(monkeypatch, reply):
    from apolaki.agent import agent as A
    scripted_chat(monkeypatch, A, [reply])
    assert make_agent(A).respond("When does the clinic open?") == reply
