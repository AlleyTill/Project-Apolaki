"""erase_person: one path that removes a named person from Apolaki's memory everywhere it lives (2026-11-02 review,
item 14 / adoption 9). The person is planted in every store through the real store() path, then the erase must
leave nothing: not a row, not an embedding, not a wiki page, not a byte of the database files. The people and places
here are invented."""
import hashlib
import json
import re
import sqlite3

import pytest

np = pytest.importorskip("numpy")
from apolaki.agent import memory_store as ms  # noqa: E402

PERSON = "Marisol Quintero"
KNOWN = [("Marisol Quintero", "PERSON"), ("Dev Okafor", "PERSON"), ("Riverside Commons", "ORG"),
         ("Harbor Hall", "FAC"), ("Lucia Quintero", "PERSON"), ("Lincoln Elementary", "ORG"), ("M. Quintero", "PERSON")]


class _Span:
    def __init__(self, text, label, start, sent):
        self.text, self.label_, self.start_char, self.end_char = text, label, start, start + len(text)
        self.sent = sent


class _Sent:
    def __init__(self, text):
        self.text = text


def fake_nlp(text):
    """Finds the known names, case-sensitive like a real NER model (a lower-case mention is missed)."""
    sent = _Sent(text)
    ents = []
    for name, label in KNOWN:
        for m in re.finditer(re.escape(name), text):
            if not any(e.start_char <= m.start() < e.end_char for e in ents):
                ents.append(_Span(name, label, m.start(), sent))
    doc = type("Doc", (), {})()
    doc.ents = sorted(ents, key=lambda e: e.start_char)
    return doc


def fake_embed(text):
    rng = np.random.default_rng(int(hashlib.sha256(text.encode()).hexdigest()[:12], 16))
    v = rng.standard_normal(768).astype(np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("APOLAKI_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(ms, "_nlp_missing", lambda: None)
    monkeypatch.setattr(ms, "_embed", fake_embed)
    monkeypatch.setattr(ms, "_get_nlp", lambda: fake_nlp)
    return tmp_path / "home"


def open_store(home):
    return ms.ApolakiMemoryStore(db_path=home / "db" / "apolaki.db", wiki_path=home / "wiki")


TEXTS = {
    "m1": "Marisol Quintero leads the tenant union at Riverside Commons.",
    "m2": "Met Marisol Quintero and Dev Okafor about the spring appeal.",
    "m3": "Dev Okafor runs the food bank at Harbor Hall.",
    "m4": "marisol quintero asked not to be photographed at events.",
    "m5": "Volunteer list reviewed for the spring appeal.",
    "m6": "Brand voice: plain and warm.",
    "m7": "Marisol Quintero's daughter Lucia Quintero attends Lincoln Elementary.",
    "m8": "M. Quintero called about the newsletter.",
}


def plant(home):
    """The person in every store: memories (one archived, one only in its tags), entities, mentions, triples, wiki
    pages, the engine's beliefs and belief log; and in files that aren't memory."""
    s = open_store(home)
    ids = {k: s.store(v, memory_type="observation") for k, v in TEXTS.items() if k != "m5"}
    ids["m5"] = s.store(TEXTS["m5"], tags=["contact: Marisol Quintero"])
    s.archive_memory(ids["m4"], reason="asked")
    for name in ("Marisol Quintero", "Dev Okafor", "Riverside Commons", "Harbor Hall", "Lucia Quintero"):
        assert s.generate_wiki_page(name)
    s.close()
    (home / "engine_beliefs.json").write_text(json.dumps([
        {"id": "b1", "content": "Reviewers approved a social draft: quote Marisol Quintero exactly.",
         "source": "review:the comms lead", "tags": ["review", "social"], "evidence": ["q1"]},
        {"id": "b2", "content": "Reviewers rejected a blog draft: too long.", "source": "review:the comms lead",
         "tags": ["review", "blog"], "evidence": ["q2"]}]))
    (home / "engine_beliefs_log.jsonl").write_text(
        json.dumps({"day": "2026-11-01", "kind": "added", "id": "b1", "source": "review:the comms lead",
                    "content": "Reviewers approved a social draft: quote Marisol Quintero exactly."}) + "\n"
        + json.dumps({"day": "2026-11-01", "kind": "added", "id": "b2", "source": "review:the comms lead",
                      "content": "Reviewers rejected a blog draft: too long."}) + "\n")
    (home / "approval-queue").mkdir()
    (home / "approval-queue" / "20261101_000000_social.json").write_text(json.dumps(
        {"id": "20261101_000000", "content": "Thanks to Marisol Quintero for hosting.", "status": "pending"}))
    (home / "quarantine").mkdir()
    (home / "quarantine" / "q_0123456789abcdef.json").write_text(json.dumps({"text": "marisol quintero said hi"}))
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "seen.json").write_text(json.dumps({"OPP-1": {"title": "A fund"}}))
    return ids


def db_rows(home, sql):
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def snapshot(home):
    """Every row of every ordinary table, every wiki file and the belief files: what a dry run must not change."""
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql NOT LIKE "
                                            "'%VIRTUAL%' AND name NOT LIKE '%vec%'")]
        rows = {t: sorted(map(repr, con.execute(f"SELECT * FROM {t}").fetchall())) for t in tables}
    finally:
        con.close()
    files = {str(f.relative_to(home)): f.read_bytes() for f in sorted((home / "wiki").rglob("*")) if f.is_file()}
    for name in ("engine_beliefs.json", "engine_beliefs_log.jsonl"):
        files[name] = (home / name).read_bytes()
    return rows, files


def all_bytes_naming(home, word, skip=()):
    """Files under home whose bytes (or name) contain word, case-insensitively, apart from the ones in skip."""
    out = []
    for f in sorted(home.rglob("*")):
        if f.is_file() and str(f.relative_to(home)) not in skip:
            if word.lower().encode() in f.read_bytes().lower() or word.lower() in f.name.lower():
                out.append(str(f.relative_to(home)))
    return out


NOT_MEMORY = {"approval-queue/20261101_000000_social.json", "quarantine/q_0123456789abcdef.json"}


# ---- the dry run ---------------------------------------------------------------------------------------------------
def test_the_dry_run_lists_every_store_and_changes_nothing(home):
    from apolaki.agent import erase as X
    ids = plant(home)
    before = snapshot(home)
    p = X.plan(PERSON)
    assert snapshot(home) == before, "the dry run changed something"
    assert {m["id"] for m in p.memories} == {ids[k] for k in ("m1", "m2", "m4", "m5", "m7")}
    assert {m["id"]: m["archived"] for m in p.memories}[ids["m4"]] is True
    assert {e["name"]: e["why"] for e in p.entities} == {
        "Marisol Quintero": "names the person", "Riverside Commons": "only in erased memories",
        "Lucia Quintero": "only in erased memories", "Lincoln Elementary": "only in erased memories"}
    assert {w["title"]: w["action"] for w in p.wiki_pages} == {
        "Marisol Quintero": "remove", "Riverside Commons": "remove", "Lucia Quintero": "remove",
        "Dev Okafor": "rebuild"}
    assert {f["file"]: f["action"] for f in p.wiki_files} == {
        "marisol_quintero.md": "remove", "riverside_commons.md": "remove", "lucia_quintero.md": "remove",
        "dev_okafor.md": "rebuild"}
    assert p.beliefs == ["b1"] and p.belief_log_lines == 1 and p.mentions and p.triples
    assert {path for path, _ in p.elsewhere} == NOT_MEMORY
    text = X.describe(p)
    assert p.code in text and "NOT erased" in text and "--confirm " + p.code in text


def test_the_code_binds_the_erase_to_what_the_dry_run_listed(home):
    from apolaki.agent import erase as X
    plant(home)
    code = X.plan(PERSON).code
    before = snapshot(home)
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(PERSON, confirm="000000000000", by="the data lead", reason="asked to be removed")
    s = open_store(home)
    s.store("Marisol Quintero joined the board.")           # memory changed after the dry run
    s.close()
    with pytest.raises(X.EraseError, match="changed since the dry run"):
        X.erase(PERSON, confirm=code, by="the data lead", reason="asked to be removed")
    assert snapshot(home)[1] == before[1] and len(db_rows(home, "SELECT id FROM memories")) == 9


@pytest.mark.parametrize("kw,match", [({"by": " "}, "who"), ({"reason": ""}, "why")])
def test_an_erase_needs_who_and_why(home, kw, match):
    from apolaki.agent import erase as X
    plant(home)
    args = dict({"confirm": X.plan(PERSON).code, "by": "the data lead", "reason": "asked to be removed"}, **kw)
    with pytest.raises(X.EraseError, match=match):
        X.erase(PERSON, **args)
    assert len(db_rows(home, "SELECT id FROM memories")) == 8


@pytest.mark.parametrize("name", ["", "  ", "Al", "M."])
def test_a_name_too_short_to_erase_by_is_refused(home, name):
    from apolaki.agent import erase as X
    plant(home)
    with pytest.raises(X.EraseError, match="too short"):
        X.plan(name)


# ---- the erase ------------------------------------------------------------------------------------------------------
def test_after_the_erase_nothing_of_the_person_remains_in_any_store(home):
    from apolaki.agent import erase as X
    ids = plant(home)
    erased_vectors = [fake_embed(TEXTS[k]).tobytes() for k in ("m1", "m2", "m4", "m5", "m7")] + \
                     [fake_embed(n).tobytes() for n in ("Marisol Quintero", "Riverside Commons", "Lucia Quintero",
                                                        "Lincoln Elementary")]
    kept_vector = fake_embed(TEXTS["m3"]).tobytes()
    p = X.plan(PERSON)
    done = X.erase(PERSON, confirm=p.code, by="the data lead", reason="asked to be removed")
    assert done["counts"]["memories"] == 5 and {path for path, _ in done["elsewhere"]} == NOT_MEMORY

    # rows
    assert {r[0] for r in db_rows(home, "SELECT id FROM memories")} == {ids["m3"], ids["m6"], ids["m8"]}
    assert {r[0] for r in db_rows(home, "SELECT name FROM kg_entities")} == {"Dev Okafor", "Harbor Hall",
                                                                              "M. Quintero"}
    for table, col in (("kg_entity_mentions", "mention_context"), ("wiki_pages", "content"),
                       ("wiki_pages", "title"), ("memories", "content"), ("memories", "tags")):
        assert not [r for r in db_rows(home, f"SELECT {col} FROM {table}") if "marisol" in str(r[0]).lower()]
    # bytes: the database, its write-ahead log and shared memory, the wiki, the belief files, the ledger
    assert all_bytes_naming(home, "marisol", skip=NOT_MEMORY) == []
    assert all_bytes_naming(home, "lucia quintero", skip=NOT_MEMORY) == []
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    assert not [i for i, v in enumerate(erased_vectors) if v in raw], "an erased embedding is still on disk"
    assert kept_vector in raw, "the check for vectors couldn't have fired: a kept one isn't found either"
    # the wiki: her page gone, the page that named her rebuilt without her, the rest untouched
    files = {f.name for f in (home / "wiki").iterdir()}
    assert files == {"dev_okafor.md", "harbor_hall.md"}
    assert "Harbor Hall" in (home / "wiki" / "dev_okafor.md").read_text()
    # beliefs: hers removed and logged without her name; the other kept
    assert [b["id"] for b in json.loads((home / "engine_beliefs.json").read_text())] == ["b2"]
    log = [json.loads(line) for line in (home / "engine_beliefs_log.jsonl").read_text().splitlines()]
    assert log[0]["content"] == "[erased]" and log[1]["content"] == "Reviewers rejected a blog draft: too long."
    assert log[-1]["kind"] == "removed" and log[-1]["id"] == "b1"
    # files that aren't memory are listed, never touched
    for rel in NOT_MEMORY:
        assert "arisol" in (home / rel).read_text()
    # the record: who, why, how much, never the name
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["by"] == "the data lead" and rec["reason"] == "asked to be removed" and rec["verified"] is True
    assert rec["counts"]["memories"] == 5 and "arisol" not in json.dumps(rec).lower()


def test_the_store_still_works_after_an_erase(home):
    from apolaki.agent import erase as X
    ids = plant(home)
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    s = open_store(home)
    try:
        found = {r.memory.id for r in s.search("Dev Okafor food bank", n_results=10)}
        assert ids["m3"] in found and not found & {ids[k] for k in ("m1", "m2", "m4", "m5", "m7")}
        assert s.stats()["memories"] == 3 and s.stats()["archived"] == 0
        assert s.generate_wiki_page(PERSON) is None
        s.store("A new note about the spring appeal.")
    finally:
        s.close()


def test_an_alias_reaches_what_the_name_alone_doesnt(home):
    from apolaki.agent import erase as X
    ids = plant(home)
    assert ids["m8"] not in {m["id"] for m in X.plan(PERSON).memories}
    p = X.plan(PERSON, aliases=("M. Quintero",))
    assert ids["m8"] in {m["id"] for m in p.memories}
    X.erase(PERSON, aliases=("M. Quintero",), confirm=p.code, by="x", reason="asked")
    assert all_bytes_naming(home, "quintero", skip=NOT_MEMORY) == []


def test_accents_and_case_are_folded(home):
    from apolaki.agent import erase as X
    s = open_store(home)
    mid = s.store("maria lopez volunteered at the clinic.")
    s.close()
    assert [m["id"] for m in X.plan("María López").memories] == [mid]


def test_a_second_erase_finds_nothing_and_says_so(home):
    from apolaki.agent import erase as X
    plant(home)
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    p = X.plan(PERSON)
    assert p.empty() and "holds nothing" in X.describe(p) and "--confirm" not in X.describe(p)


def test_the_check_after_the_erase_can_fire(home):
    """leftovers() finds the name when it is there: in a wiki file, a belief file, or the database."""
    from apolaki.agent import erase as X
    plant(home)
    assert any("apolaki.db" in f for f in X.leftovers([PERSON], home))
    assert any("marisol_quintero.md" in f for f in X.leftovers([PERSON], home))
    assert any("engine_beliefs.json" in f for f in X.leftovers([PERSON], home))


def test_an_erase_whose_check_finds_the_name_is_an_error_not_a_success(home, monkeypatch):
    from apolaki.agent import erase as X
    plant(home)
    monkeypatch.setattr(X, "leftovers", lambda names, home, blobs=(): ["somewhere: the name"])
    with pytest.raises(X.EraseError, match="check still reads"):
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is False


def test_a_reason_that_names_the_person_is_recorded_without_the_name(home):
    from apolaki.agent import erase as X
    plant(home)
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="Marisol Quintero asked by email")
    assert "arisol" not in (home / "erasures.jsonl").read_text().lower()


def test_without_sqlite_vec_a_database_with_vector_indexes_is_refused(home, monkeypatch):
    from apolaki.agent import erase as X
    plant(home)
    monkeypatch.setattr(X, "_vec_tables", lambda con: ["memory_vec"])
    monkeypatch.setattr(X, "_load_vec", lambda con: False)
    with pytest.raises(X.EraseError, match="sqlite-vec"):
        X.plan(PERSON)


def test_the_vector_indexes_hold_only_what_remains(home):
    """Where sqlite-vec is installed (as it is where Apolaki runs), the indexes are rebuilt from the kept rows."""
    pytest.importorskip("sqlite_vec")
    from apolaki.agent import erase as X
    ids = plant(home)
    assert db_rows_vec(home, "SELECT count(*) FROM memory_vec")[0][0] == 7          # 8 stored, 1 archived
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    assert {r[0] for r in db_rows_vec(home, "SELECT id FROM memory_vec")} == {ids["m3"], ids["m6"], ids["m8"]}
    kept = {r[0] for r in db_rows(home, "SELECT id FROM kg_entities")}
    assert {r[0] for r in db_rows_vec(home, "SELECT id FROM entity_vec")} == kept


def db_rows_vec(home, sql):
    import sqlite_vec
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    con.enable_load_extension(True)
    sqlite_vec.load(con)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ---- the CLI, and no MCP tool ----------------------------------------------------------------------------------------
def test_the_cli_dry_runs_then_erases_with_the_code(home, capsys):
    import apolaki.engine as E
    plant(home)
    assert E.main(["erase-person", PERSON]) == 0
    out = capsys.readouterr().out
    code = re.search(r"--confirm (\w{12})", out).group(1)
    assert "dry run" in out and "Riverside Commons" in out
    assert E.main(["erase-person", PERSON, "--confirm", "000000000000", "--by", "x", "--reason", "asked"]) == 2
    assert "not erased" in capsys.readouterr().err
    assert E.main(["erase-person", PERSON, "--confirm", code, "--by", "x", "--reason", "asked"]) == 0
    out = capsys.readouterr().out
    assert "erased: 5 memories" in out and "approval-queue" in out
    assert all_bytes_naming(home, "marisol", skip=NOT_MEMORY) == []


def test_the_mcp_server_has_no_erase_tool():
    from apolaki.agent import mcp_server as M
    assert not [t["name"] for t in M.TOOLS if "erase" in t["name"] or "delete" in t["name"]]
    assert "Unknown tool" in M.handle_tool("apolaki_erase_person", {"name": PERSON})
