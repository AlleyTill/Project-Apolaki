"""The MCP server can't write a house rule (2026-11-02 review, REPORT section 5 item 13, R2).

Before: apolaki_store_memory passed any memory_type straight to store(), which checks nothing, so any MCP client could
write a "brand" or "guideline" memory, and every one of those goes into the system prompt in full on the next start,
as a standing rule a brief can't lift. The schema's enum listed "brand", and nothing enforced the enum at all."""
import importlib
import json

import pytest

pytest.importorskip("numpy")             # memory_store imports numpy at the top; it's in the [agent] extra


class FakeStore:
    instances = []

    def __init__(self, *a, **k):
        self.stored = []
        FakeStore.instances.append(self)

    def store(self, content, memory_type="observation", significance=0.5, tags=None, source=""):
        self.stored.append({"content": content, "memory_type": memory_type, "significance": significance,
                            "tags": tags, "source": source})
        return "mem-1"

    def stats(self):
        return {"memories": len(self.stored), "entities": 0, "triples": 0}


@pytest.fixture
def mcp(monkeypatch, tmp_path):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path))
    from apolaki.agent import memory_store as ms
    monkeypatch.setattr(ms, "ApolakiMemoryStore", FakeStore)
    FakeStore.instances.clear()
    import apolaki.agent.mcp_server as m
    m = importlib.reload(m)
    yield m
    monkeypatch.undo()
    importlib.reload(m)


def stored(mcp):
    return [row for s in FakeStore.instances for row in s.stored]


def store_call(mcp, **args):
    return mcp.handle_tool("apolaki_store_memory", {"content": "Our clinic opens Mondays.", **args})


# ---- house rules can't be written over MCP --------------------------------------------------------------------------
@pytest.mark.parametrize("memory_type", ["brand", "guideline"])
def test_a_house_rule_type_is_refused_and_nothing_is_stored(mcp, memory_type):
    with pytest.raises(ValueError, match="house rule"):
        store_call(mcp, memory_type=memory_type)
    assert stored(mcp) == []


@pytest.mark.parametrize("memory_type", ["Brand", "GUIDELINE", " brand", "rule", "", None, 5, ["brand"]])
def test_a_type_outside_the_enum_is_refused(mcp, memory_type):
    with pytest.raises(ValueError, match="memory_type"):
        store_call(mcp, memory_type=memory_type)
    assert stored(mcp) == []


def test_the_schema_offers_exactly_the_types_the_server_accepts(mcp):
    (tool,) = [t for t in mcp.TOOLS if t["name"] == "apolaki_store_memory"]
    enum = tool["inputSchema"]["properties"]["memory_type"]["enum"]
    assert enum == list(mcp.STORABLE_TYPES)
    assert "brand" not in enum and "guideline" not in enum


def test_every_type_the_schema_offers_is_stored(mcp):
    for t in mcp.STORABLE_TYPES:
        store_call(mcp, memory_type=t)
    assert [r["memory_type"] for r in stored(mcp)] == list(mcp.STORABLE_TYPES)


def test_no_type_given_means_observation(mcp):
    out = json.loads(store_call(mcp))
    assert out["stored"] == "mem-1" and stored(mcp)[0]["memory_type"] == "observation"


# ---- the rest of the schema is enforced too -------------------------------------------------------------------------
@pytest.mark.parametrize("content", ["", "   ", None, 5, ["text"]])
def test_content_must_be_text(mcp, content):
    with pytest.raises(ValueError, match="content"):
        mcp.handle_tool("apolaki_store_memory", {"content": content})
    assert stored(mcp) == []


def test_content_is_required(mcp):
    with pytest.raises(ValueError, match="content"):
        mcp.handle_tool("apolaki_store_memory", {"memory_type": "observation"})


@pytest.mark.parametrize("significance", [-0.1, 1.5, "high", True, None, float("nan")])
def test_significance_must_be_a_number_from_0_to_1(mcp, significance):
    with pytest.raises(ValueError, match="significance"):
        store_call(mcp, significance=significance)
    assert stored(mcp) == []


@pytest.mark.parametrize("significance", [0, 1, 0.25])
def test_significance_in_range_is_stored(mcp, significance):
    store_call(mcp, significance=significance)
    assert stored(mcp)[0]["significance"] == significance


@pytest.mark.parametrize("tags", ["campaign", [1], [None], {"a": 1}])
def test_tags_must_be_a_list_of_text(mcp, tags):
    with pytest.raises(ValueError, match="tags"):
        store_call(mcp, tags=tags)
    assert stored(mcp) == []


@pytest.mark.parametrize("source", [5, ["x"], None])
def test_source_must_be_text(mcp, source):
    with pytest.raises(ValueError, match="source"):
        store_call(mcp, source=source)
    assert stored(mcp) == []


# ---- over the wire --------------------------------------------------------------------------------------------------
def test_a_refusal_reaches_the_client_as_an_error(mcp):
    msg = mcp.tool_result(7, {"name": "apolaki_store_memory",
                              "arguments": {"content": "Always say last chance.", "memory_type": "guideline"}})
    assert msg["id"] == 7 and msg["result"]["isError"] is True
    assert "house rule" in msg["result"]["content"][0]["text"]
    assert stored(mcp) == []


def test_an_allowed_store_reaches_the_client_as_a_result(mcp):
    msg = mcp.tool_result(8, {"name": "apolaki_store_memory", "arguments": {"content": "Mondays.", "memory_type": "team"}})
    assert msg["result"]["isError"] is False and json.loads(msg["result"]["content"][0]["text"])["stored"] == "mem-1"


def test_importing_the_server_opens_no_store(mcp):
    """Nothing is opened until a tool needs it, so the refusals can be checked without the memory stack."""
    importlib.reload(mcp)
    assert FakeStore.instances == []


def test_the_servers_house_rule_types_are_the_agents(mcp):
    from apolaki.agent import agent
    assert mcp.HOUSE_RULE_TYPES == agent.HOUSE_RULE_TYPES


# ---- the path the refusal names: a person at the interactive agent's /rule command ---------------------------------
def run_cli(monkeypatch, lines):
    import types
    from apolaki.agent import agent as A
    calls = []

    class FakeAgent:
        def __init__(self, auto_capture=False):
            self.memory = types.SimpleNamespace(stats=lambda: {"memories": 0, "archived": 0, "entities": 0, "triples": 0})
            self.house_rules_count = 0

        def remember(self, content, memory_type="decision", **kw):
            calls.append((content, memory_type))
            self.house_rules_count += memory_type in A.HOUSE_RULE_TYPES
            return "abcdef123456"

        def respond(self, text):
            calls.append((text, "sent to the model"))
            return "reply"

        def close(self):
            pass
    monkeypatch.setattr(A, "ApolakiAgent", FakeAgent)
    feed = iter(lines + ["/bye"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
    A.main()
    return calls


def test_the_rule_command_stores_a_guideline_and_remember_still_stores_a_decision(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path))
    calls = run_cli(monkeypatch, ["/rule Never promise a date we haven't confirmed.", "/remember we chose the spring date"])
    assert calls == [("Never promise a date we haven't confirmed.", "guideline"), ("we chose the spring date", "decision")]
    out = capsys.readouterr().out
    assert "/rule <text>" in out and "1 house rule" in out


@pytest.mark.parametrize("line", ["/rule", "/rule    "])
def test_a_rule_with_no_text_stores_nothing_and_sends_nothing(monkeypatch, capsys, tmp_path, line):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path))
    assert run_cli(monkeypatch, [line]) == []
    assert "Usage: /rule" in capsys.readouterr().out
