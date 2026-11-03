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
    "m2": "Met Marisol Quintero and Dev Okafor about the spring appeal at Harbor Hall.",
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
        "Dev Okafor": "rebuild", "Harbor Hall": "rebuild"}             # both pages cite m2, which names her
    assert {f["file"]: f["action"] for f in p.wiki_files} == {
        "marisol_quintero.md": "remove", "riverside_commons.md": "remove", "lucia_quintero.md": "remove",
        "dev_okafor.md": "rebuild", "harbor_hall.md": "rebuild"}
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


def test_a_new_memory_alone_changes_the_code(home):
    """A memory that names her only in its tags adds no graph row: the code must still change."""
    from apolaki.agent import erase as X
    plant(home)
    code = X.plan(PERSON).code
    s = open_store(home)
    s.store("Seating plan for the gala.", tags=["guest: Marisol Quintero"])
    s.close()
    assert X.plan(PERSON).code != code


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
    try:
        done = X.erase(PERSON, confirm=p.code, by="the data lead", reason="asked to be removed")
    except Exception as e:                  # a refusal, a leftover the erase's own check found, a broken constraint
        pytest.fail(f"the erase didn't complete: {e!r}")
    assert done["counts"]["memories"] == 5 and {path for path, _ in done["elsewhere"]} == NOT_MEMORY
    # the graph: no row left pointing at an erased memory or entity (m2 also tied Dev Okafor to Harbor Hall)
    kept_mem = {ids["m3"], ids["m6"], ids["m8"]}
    assert {r[0] for r in db_rows(home, "SELECT source_memory_id FROM kg_triples")} <= kept_mem
    assert {r[0] for r in db_rows(home, "SELECT memory_id FROM kg_entity_mentions")} <= kept_mem
    kept_ent = {r[0] for r in db_rows(home, "SELECT id FROM kg_entities")}
    assert {r[0] for r in db_rows(home, "SELECT entity_id FROM kg_entity_mentions")} <= kept_ent
    assert {x for r in db_rows(home, "SELECT subject_entity_id, object_entity_id FROM kg_triples") for x in r} <= kept_ent

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
    assert "Dev Okafor" in (home / "wiki" / "harbor_hall.md").read_text()
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


def test_the_check_finds_an_erased_embedding_left_in_the_database(home):
    from apolaki.agent import erase as X
    plant(home)
    vector = fake_embed(TEXTS["m1"]).tobytes()
    assert any("an erased embedding" in f for f in X.leftovers([PERSON], home, [vector]))
    assert not any("an erased embedding" in f for f in X.leftovers([PERSON], home, [b"\x01\x02" * 1536]))


@pytest.mark.parametrize("probe", ["MAR\u00cdA L\u00d3PEZ", "Mari\u200bsol Quintero", "\uff2d\uff41risol Quintero",
                                   "\u041carisol Quintero", "O\u2019Brien", "O`Brien", "\U000e0041\U000e0042 tag"])
def test_the_byte_fold_reads_like_the_full_fold(probe):
    """The check of the database bytes uses a fast fold; on the disguises it covers it must read what plan() reads."""
    from apolaki.agent import erase as X
    assert X._fold_bytes(probe.encode()).split() == X._fold(probe).split()


def test_ascii_text_folds_exactly_as_normalize_does(home):
    """The ASCII shortcut in _fold must give normalize()'s answer: a backtick for an apostrophe still matches."""
    from apolaki.agent import erase as X
    from apolaki.security.normalize import normalize
    for text in ("Siobhan O`Brien called.", "plain text, no quotes", "it's `quoted` here"):
        assert X._fold(text) == " ".join(normalize(text).casefold().split())
    s = open_store(home)
    mid = s.store("Siobhan O`Brien called about the appeal.")
    s.close()
    assert [m["id"] for m in X.plan("Siobhan O'Brien").memories] == [mid]


def test_a_longer_name_that_only_starts_with_theirs_is_not_them(home):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quinterova runs the choir.")
    s.store("AMarisol Quintero is a typo here.")
    s.close()
    assert X.plan(PERSON).memories == []


def test_the_full_fold_catches_what_the_byte_fold_cant(home):
    """A format character the fast byte fold doesn't know (U+110BD, Kaithi number sign) hides the name from the byte
    check; the checks with the full fold (every column of every table, and the second dry run) still find it."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Mari\U000110bdsol Quintero signed up to volunteer.")
    s.close()
    found = X.leftovers([PERSON], home)
    assert not [f for f in found if f.endswith("apolaki.db: the name")], found      # the byte check misses it
    assert any("table memories, column content" in f for f in found), found
    assert any("second dry run" in f for f in found), found


def test_an_idle_connection_left_open_doesnt_leave_old_log_frames(home):
    """With another connection open the write-ahead log isn't removed when the erase closes, and it still holds the
    frames written when the memories were stored; the erase has to empty it."""
    from apolaki.agent import erase as X
    open_store(home).close()                                     # the database, in WAL mode
    idle = sqlite3.connect(str(home / "db" / "apolaki.db"))
    idle.execute("SELECT count(*) FROM memories").fetchall()     # attached to the log, holding no transaction
    try:
        plant(home)
        assert b"Marisol" in (home / "db" / "apolaki.db-wal").read_bytes(), "the setup lost its point"
        try:
            X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
        except X.EraseError as e:
            pytest.fail(f"the erase left the name behind: {e}")
        assert b"marisol" not in (home / "db" / "apolaki.db-wal").read_bytes().lower()
    finally:
        idle.close()


def test_wiki_files_named_for_the_person_or_an_erased_entity_go_even_when_their_text_doesnt_name_her(home):
    from apolaki.agent import erase as X
    plant(home)
    (home / "wiki" / "marisol_quintero_notes.md").write_text("Notes from the March meeting.\n")
    (home / "wiki" / "lincoln_elementary.md").write_text("# Lincoln Elementary\n")           # an orphan's page
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    con.execute("DELETE FROM wiki_pages WHERE title = 'Lincoln Elementary'")                # its row long gone
    con.commit()
    con.close()
    files = {f["file"]: f["action"] for f in X.plan(PERSON).wiki_files}
    assert files.get("marisol_quintero_notes.md") == "remove" and files.get("lincoln_elementary.md") == "remove"


def test_a_page_file_whose_row_is_gone_is_rebuilt_under_its_own_title(home):
    """A page file for a kept entity that names her, with no wiki_pages row: rebuilt as "Dev Okafor", not as a
    lower-case copy with a second row."""
    from apolaki.agent import erase as X
    plant(home)
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    con.execute("DELETE FROM wiki_pages WHERE title = 'Dev Okafor'")
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert {f["file"]: (f["action"], f["title"]) for f in p.wiki_files}["dev_okafor.md"] == ("rebuild", "Dev Okafor")
    X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert (home / "wiki" / "dev_okafor.md").read_text().startswith("# Dev Okafor\n")
    assert [r[0] for r in db_rows(home, "SELECT title FROM wiki_pages WHERE lower(title) = 'dev okafor'")] == \
        ["Dev Okafor"]


def test_a_belief_file_that_cant_be_read_stops_the_erase_before_anything_changes(home):
    from apolaki.agent import erase as X
    plant(home)
    (home / "engine_beliefs.json").write_text("{not json")
    before = len(db_rows(home, "SELECT id FROM memories"))
    try:
        X.plan(PERSON)
    except X.EraseError as e:
        assert "can't be read" in str(e)
    except Exception as e:                                       # noqa: BLE001
        pytest.fail(f"an unreadable belief file broke the dry run instead of stopping it: {e!r}")
    else:
        pytest.fail("the dry run went ahead with an unreadable belief file")
    assert len(db_rows(home, "SELECT id FROM memories")) == before


def test_no_deleted_bytes_stay_where_sqlite_doesnt_zero_them_by_default(home, monkeypatch):
    """Ubuntu's SQLite is built with secure_delete on, macOS builds may not be: with every connection's default
    turned off, the erase's own secure_delete and VACUUM still leave none of the deleted text in the file."""
    from apolaki.agent import erase as X
    plant(home)
    real = sqlite3.connect

    def connect(*a, **k):
        con = real(*a, **k)
        con.execute("PRAGMA secure_delete = 0")
        return con
    monkeypatch.setattr(sqlite3, "connect", connect)
    code = X.plan(PERSON).code
    try:
        X.erase(PERSON, confirm=code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"deleted bytes stayed in the database: {e}")
    assert all_bytes_naming(home, "marisol", skip=NOT_MEMORY) == []


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
    s = open_store(home)
    old = s.store("The old office hours were Tuesday mornings.")
    s.archive_memory(old, reason="out of date")              # kept, archived: it stays out of the index
    s.close()
    assert db_rows_vec(home, "SELECT count(*) FROM memory_vec")[0][0] == 7          # 9 stored, 2 archived
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    assert old in {r[0] for r in db_rows(home, "SELECT id FROM memories WHERE archived = 1")}
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


# ---- round 2 (2026-11-03 verifier report): every encoding the store uses, every column of every table ---------------
MARIA = "Mar\u00eda L\u00f3pez"
MARIA_BYTES = ("L\u00f3pez".encode(), b"L\\u00f3pez", b"l\\u00f3pez", b"lopez", b"Lopez")


def no_vec(monkeypatch):
    """A store without the vector indexes, so nothing the erase rebuilds (3 MB vec0 chunks) overwrites the file's free
    pages or its write-ahead log by chance: what each step leaves is what it alone left."""
    monkeypatch.setattr(ms.ApolakiMemoryStore, "_init_vec", lambda self: setattr(self, "_vec_enabled", False))


def raw_db(home, secure_delete=None):
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    if secure_delete is not None:
        con.execute(f"PRAGMA secure_delete = {int(secure_delete)}")
    return con


def bytes_naming_maria(home):
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    return [b for b in MARIA_BYTES if b in raw]


def test_a_name_in_non_ascii_tags_is_found_and_erased(home):
    """store() writes tags with json.dumps, which escapes every non-ASCII letter: L\\u00f3pez on disk."""
    from apolaki.agent import erase as X
    s = open_store(home)
    tagged = s.store("Volunteer list reviewed.", tags=["contact: " + MARIA])
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    assert db_rows(home, f"SELECT tags FROM memories WHERE id = '{tagged}'")[0][0] == '["contact: Mar\\u00eda L\\u00f3pez"]'
    p = X.plan(MARIA)
    assert [m["id"] for m in p.memories] == [tagged]
    try:
        X.erase(MARIA, confirm=p.code, by="the data lead", reason="asked to be removed")
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete: {e}")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]
    assert bytes_naming_maria(home) == []


def test_a_name_in_an_archive_reason_is_found_and_erased(home):
    from apolaki.agent import erase as X
    s = open_store(home)
    old = s.store("Old volunteer roster entry.")
    s.archive_memory(old, reason=MARIA + " asked us to stop using it")
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    p = X.plan(MARIA)
    assert [(m["id"], m["archived"]) for m in p.memories] == [(old, True)]
    try:
        X.erase(MARIA, confirm=p.code, by="the data lead", reason="asked to be removed")
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete: {e}")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]
    assert bytes_naming_maria(home) == []


def test_a_table_the_erase_doesnt_know_stops_it_before_anything_changes(home):
    """Every column of every table is read: a name somewhere the erase can't remove it from is listed in the dry run,
    and the erase refuses rather than finish and leave it."""
    from apolaki.agent import erase as X
    plant(home)
    con = raw_db(home)
    con.execute("CREATE TABLE campaign_notes (id TEXT PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO campaign_notes VALUES ('n1', 'Call Marisol Quintero about the spring appeal.')")
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert p.db_other == [{"table": "campaign_notes", "column": "body", "rows": 1}]
    assert "campaign_notes" in X.describe(p)
    before = snapshot(home)
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert snapshot(home) == before


@pytest.mark.parametrize("column,value", [
    ("body", "Call Marisol Quintero about the appeal."),
    ("body", '["contact: Mar\\u00eda L\\u00f3pez"]'),                  # JSON-escaped, as store() writes tags
    ("body", "Marisol\u00a0Quintero"),                                   # a no-break space
])
def test_the_check_reads_every_column_of_every_table(home, column, value):
    from apolaki.agent import erase as X
    open_store(home).close()
    con = raw_db(home)
    con.execute("CREATE TABLE campaign_notes (id TEXT PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO campaign_notes VALUES ('n1', ?)", (value,))
    con.commit()
    con.close()
    found = X.leftovers([PERSON, MARIA], home)
    assert any("campaign_notes" in f and column in f for f in found), found


@pytest.mark.parametrize("sql,params", [
    # the name at the very start of a column value, after a column ending in a digit (archived_at)
    ("INSERT INTO memories (id, content, created_at, archived, archived_at, archive_reason) VALUES (?,?,?,?,?,?)",
     ("m-old", "Old roster entry.", "2026-01-01", 1, "2026-02-01T10:00:00+00:00", MARIA + " asked us to stop")),
    # the name JSON-escaped, as store() writes tags
    ("INSERT INTO memories (id, content, tags, created_at) VALUES (?,?,?,?)",
     ("m-old", "Seating plan.", json.dumps(["guest: " + MARIA]), "2026-01-01")),
])
def test_the_byte_check_finds_a_deleted_name_wherever_it_starts_and_however_it_is_escaped(home, monkeypatch, sql,
                                                                                          params):
    """Deleted with secure_delete off, the row's bytes stay in the file's free space where no row reads them; the byte
    check must still find the name, which starts a column value right after other bytes, or is JSON-escaped."""
    from apolaki.agent import erase as X
    no_vec(monkeypatch)
    open_store(home).close()
    con = raw_db(home, secure_delete=False)
    con.execute(sql, params)
    con.commit()
    con.execute("DELETE FROM memories WHERE id = 'm-old'")
    con.commit()
    con.close()
    assert bytes_naming_maria(home), "the setup lost its point: the deleted bytes aren't in the file"
    assert db_rows(home, "SELECT count(*) FROM memories")[0][0] == 0
    found = X.leftovers([MARIA], home)
    assert any(f.endswith("apolaki.db: the name") for f in found), found


def test_a_kept_longer_word_that_contains_the_name_is_not_taken_for_it(home):
    """The byte check has no word edges (bytes around a column value are anything), so a kept "Quinterova" would read
    as the name; it is told apart by the kept rows."""
    from apolaki.agent import erase as X
    plant(home)
    s = open_store(home)
    other = s.store("Marisol Quinterova runs the choir.")
    s.close()
    try:
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"a kept longer name was taken for hers: {e}")
    assert other in {r[0] for r in db_rows(home, "SELECT id FROM memories")}


def test_a_chance_match_inside_a_kept_vector_is_not_taken_for_the_name(home):
    """Float vectors hold a short name's bytes now and then (three letters turn up in megabytes of floats); a kept
    embedding whose bytes spell the name is kept data, not a trace."""
    from apolaki.agent import erase as X
    plant(home)
    vector = bytearray(fake_embed("Brand voice: plain and warm.").tobytes())
    vector[100:100 + 18] = b"\x81Marisol Quintero\x82"         # the name's bytes inside a vector, in no text cell
    con = raw_db(home)
    con.execute("UPDATE memories SET embedding = ? WHERE content = 'Brand voice: plain and warm.'", (bytes(vector),))
    con.commit()
    con.close()
    try:
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"a kept vector's bytes were taken for her name: {e}")


@pytest.mark.parametrize("written", ["Jean Luc Moreau", "Jean-Luc Moreau", "Jean\u2013Luc Moreau", "JeanLuc Moreau",
                                     "jean_luc_moreau", "JEAN-LUC MOREAU", "Jean\u2011Luc Moreau"])
@pytest.mark.parametrize("asked", ["Jean-Luc Moreau", "Jean Luc Moreau"])
def test_hyphen_space_and_joined_forms_of_a_name_are_the_same_name(home, written, asked):
    from apolaki.agent import erase as X
    s = open_store(home)
    mid = s.store(f"{written} joined the board.")
    s.store("Jean-Lucien Moreau and Jean-Luc Moreaux are other people.")
    s.close()
    assert [m["id"] for m in X.plan(asked).memories] == [mid]


@pytest.mark.parametrize("written", ["Siobhan OBrien", "Siobhan O Brien", "Siobhan O\u2019Brien", "siobhan.obrien"])
def test_apostrophe_forms_of_a_name_are_the_same_name(home, written):
    from apolaki.agent import erase as X
    s = open_store(home)
    mid = s.store(f"Ask {written} about the venue.")
    s.close()
    assert [m["id"] for m in X.plan("Siobhan O'Brien").memories] == [mid]


def test_a_belief_log_line_naming_the_person_in_a_list_is_redacted_whole(home):
    from apolaki.agent import erase as X
    plant(home)
    with (home / "engine_beliefs_log.jsonl").open("a") as f:
        f.write(json.dumps({"day": "2026-11-02", "kind": "added", "id": "b3", "tags": ["guest: Marisol Quintero"]})
                + "\n")
    try:
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"the erase left the name in the belief log: {e}")
    assert "arisol" not in (home / "engine_beliefs_log.jsonl").read_text().lower()


# Each of the three steps that clear deleted bytes, alone: removing any one of them must fail a test.
class _VacuumFails(sqlite3.Connection):
    def execute(self, sql, *args):
        if sql.strip().upper() == "VACUUM":
            raise sqlite3.OperationalError("database or disk is full")
        return super().execute(sql, *args)


def test_secure_delete_zeroes_the_deleted_rows_when_vacuum_cant_run(home, monkeypatch):
    """VACUUM needs free space the size of the database. When it fails, the erase's own secure_delete is what keeps the
    deleted text out of the file; the erase says it didn't finish, and records it unverified."""
    from apolaki.agent import erase as X
    real = sqlite3.connect

    def plant_connect(*a, **k):
        con = real(*a, **k)
        con.execute("PRAGMA secure_delete = 1")               # the store's own deletes zeroed, on any build
        return con
    monkeypatch.setattr(sqlite3, "connect", plant_connect)
    plant(home)
    code = X.plan(PERSON).code

    def erase_connect(*a, **k):
        con = real(*a, factory=_VacuumFails, **k)
        con.execute("PRAGMA secure_delete = 0")               # a build whose default is off (macOS may be)
        return con
    monkeypatch.setattr(sqlite3, "connect", erase_connect)
    with pytest.raises(X.EraseError, match="VACUUM"):
        X.erase(PERSON, confirm=code, by="x", reason="asked")
    assert all_bytes_naming(home, "marisol", skip=NOT_MEMORY) == []
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is False and any("VACUUM" in p for p in rec["problems"])


def test_vacuum_clears_text_an_earlier_delete_left_in_free_pages(home, monkeypatch):
    """Rows deleted before the erase, where secure_delete was off, leave their text in free pages that no row reads
    and the erase's own deletes never touch; only rebuilding the file clears them."""
    from apolaki.agent import erase as X
    no_vec(monkeypatch)
    plant(home)
    con = raw_db(home, secure_delete=False)
    con.execute("INSERT INTO memories (id, content, created_at) VALUES ('gone', ?, '2026-01-01')",
                ("Marisol Quintero's old note. " * 300,))
    con.commit()
    con.execute("DELETE FROM memories WHERE id = 'gone'")
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert "gone" not in {m["id"] for m in p.memories}
    try:
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"text an earlier delete left behind is still in the file: {e}")
    assert all_bytes_naming(home, "marisol", skip=NOT_MEMORY) == []


def test_the_write_ahead_log_is_emptied_when_another_connection_keeps_it(home, monkeypatch):
    """An idle connection keeps the log file when the erase closes; it still holds the frames written when the memories
    were stored, and nothing but the truncating checkpoint empties it."""
    from apolaki.agent import erase as X
    no_vec(monkeypatch)
    open_store(home).close()
    idle = sqlite3.connect(str(home / "db" / "apolaki.db"))
    idle.execute("SELECT count(*) FROM memories").fetchall()
    try:
        plant(home)
        assert b"Marisol" in (home / "db" / "apolaki.db-wal").read_bytes(), "the setup lost its point"
        try:
            X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
        except X.EraseError as e:
            pytest.fail(f"the erase left the name behind: {e}")
        assert b"marisol" not in (home / "db" / "apolaki.db-wal").read_bytes().lower()
    finally:
        idle.close()


def test_a_reader_holding_the_log_makes_the_erase_incomplete_and_says_why(home, monkeypatch):
    from apolaki.agent import erase as X
    monkeypatch.setattr(X, "BUSY_TIMEOUT_S", 0.5)                       # the lock wait, not the point here
    plant(home)
    code = X.plan(PERSON).code
    reader = sqlite3.connect(str(home / "db" / "apolaki.db"))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM memories").fetchall()           # a read transaction left open
    try:
        with pytest.raises(X.EraseError, match="another connection is reading"):
            X.erase(PERSON, confirm=code, by="x", reason="asked")
    finally:
        reader.close()
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is False


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
