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
                                   "\u041carisol Quintero", "O\u2019Brien", "O`Brien", "\U000e0041\U000e0042 tag",
                                   # round 3: Thai marks, Hangul (NFKD splits it), astral format and mark characters
                                   "\u0e2a\u0e21\u0e28\u0e31\u0e01\u0e14\u0e34\u0e4c", "\uae40\ubbfc\uc218 \uc528",
                                   "Mari\U000110bdsol Quintero", "Mari\U0001d167sol Quintero"])
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
    """The byte check reads the bytes with a fast fold and escapes decoded, not with markup taken out: a Markdown link
    between the parts of the name hides it from the byte check; the checks of the rows (every column of every table,
    and the second dry run) still find it."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Thanks to [Marisol](https://x.example) Quintero for hosting.")
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
    monkeypatch.setattr(X, "leftovers", lambda names, home, blobs=(), others=(): ["somewhere: the name"])
    with pytest.raises(X.EraseIncomplete, match="check still reads"):
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is False


def test_the_cli_says_an_erase_is_incomplete_and_exits_1_and_a_refusal_exits_2(home, monkeypatch, capsys):
    import apolaki.engine as E
    from apolaki.agent import erase as X
    plant(home)
    assert E.main(["erase-person", PERSON, "--confirm", "000000000000", "--by", "x", "--reason", "asked"]) == 2
    assert "not erased" in capsys.readouterr().err
    monkeypatch.setattr(X, "leftovers", lambda names, home, blobs=(), others=(): ["somewhere: the name"])
    assert E.main(["erase-person", PERSON, "--confirm", X.plan(PERSON).code, "--by", "x", "--reason", "asked"]) == 1
    assert "ERASE INCOMPLETE" in capsys.readouterr().err


def test_a_reason_that_names_the_person_is_recorded_without_the_name(home):
    from apolaki.agent import erase as X
    plant(home)
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="Marisol Quintero asked by email")
    assert "arisol" not in (home / "erasures.jsonl").read_text().lower()


def test_a_by_that_names_the_person_is_recorded_without_the_name_too(home):
    """Both fields are checked: a reason and a by that both name her are both redacted."""
    from apolaki.agent import erase as X
    plant(home)
    X.erase(PERSON, confirm=X.plan(PERSON).code, by="Marisol Quintero's assistant", reason="Marisol Quintero asked")
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["by"] == "[erased]" and rec["reason"] == "[erased]"


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


@pytest.mark.parametrize("tag,name", [
    ("contact: " + MARIA, MARIA),
    (json.dumps(["contact: " + MARIA]), MARIA),                  # escaped twice: two backslashes on disk
    ("contact: \U0001d40carisol Quintero", PERSON),              # a mathematical bold M: a surrogate pair, escaped
    ("contact: Marisol\nQuintero", PERSON),                      # a line break, escaped as backslash-n
], ids=["accents", "escaped twice", "astral letter", "escaped line break"])
def test_a_name_in_escaped_tags_is_found(home, tag, name):
    from apolaki.agent import erase as X
    s = open_store(home)
    tagged = s.store("Volunteer list reviewed.", tags=[tag])
    s.store("Brand voice: plain and warm.")
    s.close()
    assert [m["id"] for m in X.plan(name).memories] == [tagged]


def test_a_name_in_non_ascii_tags_is_found_and_erased(home):
    """store() writes tags with json.dumps, which escapes every non-ASCII letter: L\\u00f3pez on disk."""
    from apolaki.agent import erase as X
    s = open_store(home)
    tagged = s.store("Volunteer list reviewed.", tags=["contact: " + MARIA])
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    stored = db_rows(home, f"SELECT tags FROM memories WHERE id = '{tagged}'")[0][0]
    assert stored == '["contact: Mar\\u00eda L\\u00f3pez"]'
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
    ("body", "Call Marisol Quintero about the appeal.".encode()),        # text kept as a blob
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


def test_a_kept_longer_word_ruled_someone_else_is_not_taken_for_the_name(home):
    """The byte check has no word edges (bytes around a column value are anything), so a kept "Quinterova" reads as the
    name there; once a person has ruled it someone else, the kept row explains those bytes."""
    from apolaki.agent import erase as X
    plant(home)
    s = open_store(home)
    other = s.store("Marisol Quinterova runs the choir.")
    s.close()
    try:
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked", not_them=("Marisol Quinterova",))
    except X.EraseError as e:
        pytest.fail(f"a kept longer name, ruled someone else, was taken for hers: {e}")
    assert other in {r[0] for r in db_rows(home, "SELECT id FROM memories")}


def test_a_file_outside_memory_with_the_name_escaped_is_listed(home):
    """The grant hunt's files are written with json.dumps defaults, which escape non-ASCII letters."""
    from apolaki.agent import erase as X
    open_store(home).close()
    (home / "grant-hunt").mkdir()
    (home / "grant-hunt" / "seen.json").write_text(json.dumps({"OPP-1": {"contact": MARIA}}))
    assert "\\u00f3" in (home / "grant-hunt" / "seen.json").read_text(), "the setup lost its point"
    assert [path for path, _ in X.plan(MARIA).elsewhere] == ["grant-hunt/seen.json"]


def test_the_check_reads_the_belief_log_with_escapes_decoded(home):
    from apolaki.agent import erase as X
    open_store(home).close()
    (home / "engine_beliefs_log.jsonl").write_text(json.dumps({"kind": "added", "content": "Quote " + MARIA}) + "\n")
    found = X.leftovers([MARIA], home)
    assert any(f.endswith("engine_beliefs_log.jsonl: the name") for f in found), found


def test_a_rollback_journal_left_beside_the_database_is_read(home):
    """A database used in rollback-journal mode (or left by a crash) can have a -journal file holding old pages."""
    from apolaki.agent import erase as X
    open_store(home).close()
    (home / "db" / "apolaki.db-journal").write_bytes(b"\x00" * 512 + b"old page: Marisol Quintero leads the union.")
    assert any(f.endswith("apolaki.db-journal: the name") for f in X.leftovers([PERSON], home))


def test_a_graph_row_that_names_her_only_in_its_own_text_goes_and_its_rows_stay(home):
    """A mention whose context, or a triple whose predicate, names her between rows that don't: that row goes, the
    kept memory and entities stay."""
    from apolaki.agent import erase as X
    s = open_store(home)
    kept = s.store("Dev Okafor runs the food bank at Harbor Hall.")
    s.close()
    con = raw_db(home)
    dev, hall = (con.execute("SELECT id FROM kg_entities WHERE name = ?", (n,)).fetchone()[0]
                 for n in ("Dev Okafor", "Harbor Hall"))
    con.execute("DELETE FROM kg_entity_mentions WHERE entity_id = ?", (dev,))
    con.execute("INSERT INTO kg_entity_mentions (id, entity_id, memory_id, mention_context) VALUES (?,?,?,?)",
                ("men-1", dev, kept, "Dev Okafor, whom Marisol Quintero trained"))
    con.execute("INSERT INTO kg_triples (id, subject_entity_id, predicate, object_entity_id, source_memory_id, "
                "created_at) VALUES (?,?,?,?,?,?)", ("tri-1", dev, "trained_by_marisol_quintero", hall, kept, "2026"))
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert "men-1" in p.mentions and "tri-1" in p.triples and p.memories == [] and p.db_other == []
    try:
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete: {e}")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]
    assert {r[0] for r in db_rows(home, "SELECT name FROM kg_entities")} == {"Dev Okafor", "Harbor Hall"}
    assert not db_rows(home, "SELECT id FROM kg_entity_mentions WHERE id = 'men-1'")
    assert not db_rows(home, "SELECT id FROM kg_triples WHERE id = 'tri-1'")


def test_a_table_without_rowids_is_read_too(home):
    from apolaki.agent import erase as X
    open_store(home).close()
    con = raw_db(home)
    con.execute("CREATE TABLE notes_by_name (name TEXT PRIMARY KEY, note TEXT) WITHOUT ROWID")
    con.execute("INSERT INTO notes_by_name VALUES ('Marisol Quintero', 'call back')")
    con.commit()
    con.close()
    try:
        p = X.plan(PERSON)
    except Exception as e:                       # noqa: BLE001 - a crash is a failure of the read, said as one
        pytest.fail(f"a table without rowids broke the dry run: {e!r}")
    assert p.db_other == [{"table": "notes_by_name", "column": "name", "rows": 1}]


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


# ---- round 3 (2026-11-03 verifier, round 2): a name touching a letter, a digit or markup; near-matches ruled on
# Each text names the person through the real store() path; before round 3 each erased "successfully" and left it.
TOUCHING = [
    ("\u4eca\u5929\u738b\u5c0f\u660e\u6765\u4e86\u56fe\u4e66\u9986\u3002", "\u738b\u5c0f\u660e", "\u738b\u5c0f\u660e"),
    ("\u0e27\u0e31\u0e19\u0e19\u0e35\u0e49\u0e2a\u0e21\u0e0a\u0e32\u0e22\u0e21\u0e32\u0e17\u0e35\u0e48\u0e2b\u0e49"
     "\u0e2d\u0e07\u0e2a\u0e21\u0e38\u0e14", "\u0e2a\u0e21\u0e0a\u0e32\u0e22", "\u0e2a\u0e21\u0e0a\u0e32\u0e22"),
    # "We met with Karim Mansour today" (an invented name): the preposition bi is written joined to the name
    ("\u0627\u0644\u062a\u0642\u064a\u0646\u0627 \u0628\u0643\u0631\u064a\u0645 \u0645\u0646\u0635\u0648\u0631 "
     "\u0627\u0644\u064a\u0648\u0645",
     "\u0643\u0631\u064a\u0645 \u0645\u0646\u0635\u0648\u0631",
     "\u0643\u0631\u064a\u0645 \u0645\u0646\u0635\u0648\u0631"),
    ("Marisol Quintero\u3055\u3093\u304c\u6765\u307e\u3057\u305f\u3002", PERSON, "Quintero"),
    ("Write to marisol.quintero85@example.org about the lease.", PERSON, "quintero85"),
    ("Follow @MarisolQuintero1990 for updates.", PERSON, "Quintero1990"),
    ("File marisolquintero2.pdf is attached.", PERSON, "quintero2"),
    ("Thanks to **Marisol** Quintero for hosting.", PERSON, "Quintero"),
    ("Thanks to [Marisol](https://x.example) Quintero.", PERSON, "Quintero"),
    ("Contact: Marisol/Quintero", PERSON, "Quintero"),
    ("Mar&iacute;a L&oacute;pez called.", MARIA, "pez"),
    # a name in a script written without spaces keeps no edge even where Latin letters touch it ("member VIP" + name)
    ("\u4f1a\u5458VIP\u738b\u5c0f\u660e\u6765\u4e86\u3002", "\u738b\u5c0f\u660e", "\u738b\u5c0f\u660e"),
]


@pytest.mark.parametrize("text,name,probe", TOUCHING, ids=["chinese", "thai", "arabic prefix", "japanese honorific",
                                                            "email with digits", "handle with year", "file with digit",
                                                            "markdown emphasis", "markdown link", "slash",
                                                            "html entities", "chinese beside latin letters"])
def test_a_name_touching_a_letter_a_digit_or_markup_is_found_and_erased(home, text, name, probe):
    from apolaki.agent import erase as X
    s = open_store(home)
    mid = s.store(text)
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    p = X.plan(name)
    assert [m["id"] for m in p.memories] == [mid], X.describe(p)
    try:
        X.erase(name, confirm=p.code, by="the data lead", reason="asked to be removed")
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete: {e}")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]
    assert not [r for r in db_rows(home, "SELECT content FROM memories") if probe.lower() in r[0].lower()]


QUINTEROVA = "Marisol Quinterova runs the choir."


def test_a_near_match_is_listed_and_the_erase_refuses_until_a_person_rules_on_it(home):
    """The name inside a longer word in a kept row: the dry run lists it, and the erase removes nothing until a person
    names it as someone else."""
    from apolaki.agent import erase as X
    plant(home)
    s = open_store(home)
    other = s.store(QUINTEROVA)
    s.close()
    p = X.plan(PERSON)
    assert [n["word"] for n in p.near] == ["marisol quinterova"]
    assert p.near[0]["place"] == {"table": "memories", "column": "content", "row": other}
    text = X.describe(p)
    assert "marisol quinterova" in text and "--not-them" in text and other[:8] in text
    before = snapshot(home)
    with pytest.raises(X.EraseError, match="near-match") as e:
        X.erase(PERSON, confirm=p.code, by="the data lead", reason="asked to be removed")
    assert "Nothing was removed" in str(e.value) and snapshot(home) == before
    assert not (home / "erasures.jsonl").exists()
    try:
        X.erase(PERSON, confirm=p.code, by="the data lead", reason="asked to be removed",
                not_them=("Marisol Quinterova",))
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete with the near-match ruled on: {e}")
    assert other in {r[0] for r in db_rows(home, "SELECT id FROM memories")}
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True
    assert rec["near_matches"] == [{"place": {"table": "memories", "column": "content", "row": other},
                                    "ruling": "someone else"}]
    assert "arisol" not in json.dumps(rec).lower() and "quinter" not in json.dumps(rec).lower()


@pytest.mark.parametrize("not_them,match", [
    ((), "near-match"),
    (("Marisol Quinterova", "Marisol Quinteros"), "didn't list"),
    (("Quinterova",), "near-match"),
], ids=["none", "one too many", "a different word"])
def test_a_ruling_must_name_exactly_the_near_matches(home, not_them, match):
    from apolaki.agent import erase as X
    plant(home)
    s = open_store(home)
    s.store(QUINTEROVA)
    s.close()
    before = snapshot(home)
    with pytest.raises(X.EraseError, match=match):
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked", not_them=not_them)
    assert snapshot(home) == before


def test_the_byte_check_accepts_a_no_edge_match_only_where_a_ruled_near_match_stands(home):
    """Before round 3 the byte check took any longer word a kept row holds for someone else, and so accepted
    "Quintero\u3055\u3093" and "MarisolQuintero1990" because a kept row held them."""
    from apolaki.agent import erase as X
    open_store(home).close()
    con = raw_db(home)                  # as SQL: the test's fake entity finder would take "Marisol Quintero" from it
    con.execute("INSERT INTO memories (id, content, created_at) VALUES ('other', ?, '2026-01-01')", (QUINTEROVA,))
    con.commit()
    con.close()
    found = X.leftovers([PERSON], home)
    assert any(f.endswith("apolaki.db: the name") for f in found), found
    assert any("near-match nobody ruled on" in f for f in found), found
    assert X.leftovers([PERSON], home, others=("Marisol Quinterova",)) == []


def test_a_deleted_near_match_left_in_free_pages_is_a_trace(home, monkeypatch):
    """A longer word that no kept row holds explains nothing: deleted bytes left by an earlier delete are a trace."""
    from apolaki.agent import erase as X
    no_vec(monkeypatch)
    open_store(home).close()
    con = raw_db(home, secure_delete=False)
    con.execute("INSERT INTO memories (id, content, created_at) VALUES ('gone', ?, '2026-01-01')", (QUINTEROVA,))
    con.commit()
    con.execute("DELETE FROM memories WHERE id = 'gone'")
    con.commit()
    con.close()
    assert b"Quinterova" in (home / "db" / "apolaki.db").read_bytes(), "the setup lost its point"
    found = X.leftovers([PERSON], home, others=("Marisol Quinterova",))
    assert any(f.endswith("apolaki.db: the name") for f in found), found


@pytest.mark.parametrize("where,setup", [
    ("belief", lambda home: (home / "engine_beliefs.json").write_text(json.dumps(
        [{"id": "b9", "content": "Reviewers liked the note on " + QUINTEROVA}]))),
    ("belief log", lambda home: (home / "engine_beliefs_log.jsonl").write_text(json.dumps(
        {"kind": "added", "id": "b9", "content": QUINTEROVA}) + "\n")),
    ("wiki file", lambda home: (home / "wiki" / "choir.md").write_text("# Choir\n" + QUINTEROVA + "\n")),
])
def test_a_near_match_in_a_kept_file_needs_a_ruling_too(home, where, setup):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quintero leads the tenant union.")
    s.close()
    (home / "wiki").mkdir(exist_ok=True)
    setup(home)
    p = X.plan(PERSON)
    assert [n["word"] for n in p.near] == ["marisol quinterova"], X.describe(p)
    with pytest.raises(X.EraseError, match="near-match.*Nothing was removed"):     # refused, not run and incomplete
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    try:
        X.erase(PERSON, confirm=p.code, by="x", reason="asked", not_them=("marisol quinterova",))
    except X.EraseError as e:
        pytest.fail(f"the erase didn't complete with the near-match ruled on: {e}")
    assert X.leftovers([PERSON], home) and X.leftovers([PERSON], home, others=("marisol quinterova",)) == []


def test_a_ledger_place_that_names_the_person_is_recorded_without_it(home):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quintero leads the tenant union.")
    s.close()
    con = raw_db(home)
    con.execute("CREATE TABLE handles (id TEXT PRIMARY KEY, note TEXT)")
    con.execute("INSERT INTO handles VALUES ('marisolquinterova', 'the choir lead')")
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert [n["place"] for n in p.near] == [{"table": "handles", "column": "id", "row": "marisolquinterova"}]
    X.erase(PERSON, confirm=p.code, by="x", reason="asked", not_them=("marisolquinterova",), checked=("table:handles",))
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["near_matches"] == [{"place": {"table": "handles", "column": "id", "row": "[erased]"},
                                    "ruling": "someone else"}]


@pytest.mark.parametrize("ddl,kind", [
    ("CREATE TABLE notes_marisol_quintero (x TEXT)", "table"),
    ("CREATE VIEW v AS SELECT 'Marisol Quintero' AS who", "view"),
    ("CREATE TRIGGER t AFTER INSERT ON memories WHEN new.content LIKE '%Marisol Quintero%' BEGIN SELECT 1; END",
     "trigger"),
    ("CREATE TABLE extra (who TEXT DEFAULT 'Marisol Quintero')", "table"),
    ("CREATE INDEX idx_marisol_quintero ON memories(content)", "index"),
], ids=["table name", "view", "trigger", "column default", "index name"])
def test_a_schema_object_naming_the_person_stops_the_erase_before_anything_changes(home, ddl, kind):
    from apolaki.agent import erase as X
    plant(home)
    con = raw_db(home)
    con.execute(ddl)
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert [s["type"] for s in p.schema] == [kind]
    assert "schema" in X.describe(p) and "WILL REFUSE" in X.describe(p)
    before = snapshot(home)
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert snapshot(home) == before


def test_a_kept_blob_of_text_that_isnt_utf8_is_read_as_text(home):
    """Only a blob that reads as an embedding's float numbers is skipped as numbers; text in another encoding isn't
    one, so the name in it is found (before round 3 the byte check took it for a chance match in a vector)."""
    from apolaki.agent import erase as X
    plant(home)
    con = raw_db(home)
    con.execute("CREATE TABLE campaign_notes (id TEXT PRIMARY KEY, body BLOB)")
    blob = "Caf\u00e9 meeting with Marisol Quintero, cr\u00e8me br\u00fbl\u00e9e, 10:30.".encode("latin-1")
    assert len(blob) % 4 == 0 and len(blob) >= 16, "the setup lost its point: the float check must be what decides"
    con.execute("INSERT INTO campaign_notes VALUES ('n1', ?)", (blob,))
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert p.db_other == [{"table": "campaign_notes", "column": "body", "rows": 1}]
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")


def test_a_real_chance_match_inside_a_kept_vector_is_not_taken_for_the_name(home):
    """A short name's letters can stand in the low bytes of a float an embedding holds (each component is under 1, so
    its top byte is no letter). A kept vector whose bytes spell the name that way is numbers, not a trace."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Lia called about the venue.")
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    vector = bytearray(fake_embed("Brand voice: plain and warm.").tobytes())
    vector[100:104] = b"Lia\x3e"                 # one float32, about 0.2, whose low three bytes spell the name
    con = raw_db(home)
    con.execute("UPDATE memories SET embedding = ? WHERE id = ?", (bytes(vector), kept))
    con.commit()
    con.close()
    from apolaki.agent.erase import _is_vector
    assert _is_vector(bytes(vector)), "the setup lost its point: the vector no longer reads as numbers"
    try:
        X.erase("Lia", confirm=X.plan("Lia").code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"a kept vector's bytes were taken for her name: {e}")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]


def test_the_cli_takes_a_ruling_on_each_near_match(home, capsys):
    import apolaki.engine as E
    plant(home)
    s = open_store(home)
    s.store(QUINTEROVA)
    s.close()
    assert E.main(["erase-person", PERSON]) == 0
    out = capsys.readouterr().out
    code = re.search(r"--confirm (\w{12})", out).group(1)
    assert "Near-match" in out and "--not-them 'marisol quinterova'" in out
    assert E.main(["erase-person", PERSON, "--confirm", code, "--by", "x", "--reason", "asked"]) == 2
    assert "near-match" in capsys.readouterr().err
    assert E.main(["erase-person", PERSON, "--confirm", code, "--by", "x", "--reason", "asked",
                   "--not-them", "Marisol Quinterova"]) == 0
    assert "1 near-match" in capsys.readouterr().out


def test_a_dict_key_naming_the_person_is_redacted_in_the_belief_log(home):
    """_redact's key branch on its own: a key that names her becomes "[erased]", its value stays when it doesn't."""
    from apolaki.agent import erase as X
    hit = X._matcher([PERSON])
    assert X._redact({"Marisol Quintero": "quote exactly", "kind": "added"}, hit) == {"[erased]": "quote exactly",
                                                                                     "kind": "added"}
    plant(home)
    with (home / "engine_beliefs_log.jsonl").open("a") as f:
        f.write(json.dumps({"day": "2026-11-02", "kind": "added", "notes": {"Marisol Quintero": "quote exactly"}})
                + "\n")
    try:
        X.erase(PERSON, confirm=X.plan(PERSON).code, by="x", reason="asked")
    except X.EraseError as e:
        pytest.fail(f"the erase left the name in a belief-log key: {e}")
    last = json.loads((home / "engine_beliefs_log.jsonl").read_text().splitlines()[2])
    assert last["notes"] == {"[erased]": "quote exactly"}


def test_a_new_near_match_alone_changes_the_code(home):
    """The code covers what the dry run lists to keep as well as what it removes: a near-match added after the dry run
    is one nobody has read, so the old code no longer erases."""
    from apolaki.agent import erase as X
    plant(home)
    code = X.plan(PERSON).code
    con = raw_db(home)
    con.execute("INSERT INTO memories (id, content, created_at) VALUES ('other', ?, '2026-01-01')", (QUINTEROVA,))
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert p.near and p.code != code
    with pytest.raises(X.EraseError, match="changed since the dry run"):
        X.erase(PERSON, confirm=code, by="x", reason="asked", not_them=("marisol quinterova",))


def test_a_file_outside_memory_with_only_a_near_match_is_listed(home):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quintero leads the tenant union.")
    s.close()
    (home / "approval-queue").mkdir()
    (home / "approval-queue" / "20261101_000000_social.json").write_text(json.dumps({"content": QUINTEROVA}))
    p = X.plan(PERSON)
    assert p.elsewhere == [] and p.elsewhere_near == [("approval-queue/20261101_000000_social.json", 1)]
    assert "approval-queue/20261101_000000_social.json (1 near-match(es))" in X.describe(p)


# ---- round 4: text in a blob in UTF-16 or UTF-32 (2026-11-04 verifier, round 3: a false success) ------------------
# Each encoding with and without its byte-order mark, and at an alignment a header byte moves it to. Before round 4 a
# blob whose every fourth byte is NUL was read as float32 numbers, and an ASCII one as UTF-8 with NULs between letters.
WIDE = [("utf-16-le", b""), ("utf-16-be", b""), ("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"),
        ("utf-32-le", b""), ("utf-32-be", b""), ("utf-32-le", b"\xff\xfe\x00\x00"), ("utf-32-be", b"\x00\x00\xfe\xff"),
        ("utf-16-le", b"\x07"), ("utf-16-be", b"\x07"), ("utf-32-le", b"\x07\x07\x07"), ("utf-32-be", b"\x07")]
WIDE_IDS = [f"{e}{'+' + h.hex() if h else ''}" for e, h in WIDE]
WIDE_TEXTS = [("Marisol Quintero", "Call Marisol Quintero tomorrow."),               # ASCII: valid UTF-8 with NULs
              ("Mar\u00eda L\u00f3pez", "Caf\u00e9 with Mar\u00eda L\u00f3pez, 10:30."),
              ("\u041c\u0430\u0440\u0438\u044f \u041b\u043e\u043f\u0435\u0441",            # Cyrillic: no NUL at all
               "\u0417\u0432\u043e\u043d\u043e\u043a: \u041c\u0430\u0440\u0438\u044f \u041b\u043e\u043f\u0435\u0441.")]


@pytest.mark.parametrize("name,text", WIDE_TEXTS, ids=["ascii", "accented", "cyrillic"])
@pytest.mark.parametrize("encoding,head", WIDE, ids=WIDE_IDS)
def test_a_name_in_a_wide_text_blob_in_a_hand_added_table_is_refused(home, encoding, head, name, text):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    s.close()
    con = raw_db(home)
    con.execute("CREATE TABLE attachments (id TEXT PRIMARY KEY, body BLOB)")
    con.execute("INSERT INTO attachments VALUES ('a1', ?)", (head + text.encode(encoding),))
    con.commit()
    con.close()
    p = X.plan(name)
    assert p.db_other == [{"table": "attachments", "column": "body", "rows": 1}], X.describe(p)
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(name, confirm=p.code, by="x", reason="asked")


@pytest.mark.parametrize("encoding,head", WIDE, ids=WIDE_IDS)
def test_a_name_in_a_wide_text_blob_on_a_memory_takes_the_memory(home, encoding, head):
    """A hand-added column on memories is a column of the memory: the memory goes whole, and the bytes with it."""
    from apolaki.agent import erase as X
    name, text = WIDE_TEXTS[1]
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    kept = s.store("Unrelated note about the garden.")
    s.close()
    con = raw_db(home)
    con.execute("ALTER TABLE memories ADD COLUMN attachment BLOB")
    con.execute("UPDATE memories SET attachment = ? WHERE id = ?", (head + text.encode(encoding), kept))
    con.commit()
    con.close()
    p = X.plan(name)
    assert kept in [m["id"] for m in p.memories], X.describe(p)
    assert p.checks() == ["column:memories.attachment"]
    X.erase(name, confirm=p.code, by="x", reason="asked", checked=p.checks())
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    assert name.encode(encoding) not in raw and "L\u00f3pez".encode(encoding) not in raw
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True


def test_every_blob_is_read_in_each_wide_encoding(home):
    """_readings on its own: a vector (an embedding's float numbers) is read in them too; it holds the name or not.
    Since round 5 a blob's text with its NULs taken out finds ASCII or Latin-1 text in UTF-16 and UTF-32 as well, so
    Cyrillic text, which that doesn't reveal, shows the wide readings are what find it."""
    from apolaki.agent import erase as X
    hit = X._matcher([PERSON])

    def named(value, wide=True, hit=hit):
        return any(X._names_in(hit, t, fold=f) for t, f in X._readings(value, hit, wide=wide))
    vector = fake_embed("Brand voice: plain and warm.").tobytes()
    assert X._is_vector(vector) and X._cell_text(vector) is None, "the setup lost its point"
    # 12 wide readings are made; since round A a reading that is all noise (no letter of the name) isn't kept
    assert len(X._wide_texts(vector)) == 12 and 0 < len(X._readings(vector, hit)) <= 12 and not named(vector)
    cyrillic, text = WIDE_TEXTS[2]
    for encoding, head in WIDE:
        blob = head + "Call Marisol Quintero.".encode(encoding)
        assert named(blob), (encoding, head)
        blob = head + text.encode(encoding)
        assert named(blob, hit=X._matcher([cyrillic])) and not named(blob, wide=False, hit=X._matcher([cyrillic])), (
            encoding, head)
    assert X._readings("Marisol Quintero", hit)[0] == ("Marisol Quintero", X._fold) and X._readings(None, hit) == []


def test_a_wide_reading_keeps_what_can_stand_in_the_name(home):
    """_readings on its own (round 4 mutants): in a wide reading, printable ASCII (escapes), a separator, what folds to
    nothing, a letter past U+FFFF and the parts of a composed letter all stay; the rest, a vector's or a run of zeros'
    noise, reads as one NUL a run."""
    import unicodedata
    from apolaki.agent import erase as X

    def named(name, text, encoding="utf-16-le"):
        hit = X._matcher([name])
        return any(X._names_in(hit, t, fold=f) for t, f in X._readings(text.encode(encoding), hit))
    bs = chr(92)
    maria = "Mar" + chr(0xED) + "a L" + chr(0xF3) + "pez"
    assert named(maria, "Call Mar" + bs + "u00eda L" + bs + "u00f3pez today.")       # escapes are written in ASCII
    assert named(PERSON, "Call Marisol" + chr(0x2013) + "Quintero today.")              # an en dash between the parts
    assert named(PERSON, "Call Mari" + chr(0x200B) + "sol Quintero today.")             # a zero-width space in a part
    assert named(PERSON, "Call " + chr(0x1D40C) + "arisol Quintero.", "utf-32-le")      # a mathematical M, past U+FFFF
    korean = chr(0xAE40) + chr(0xBBFC) + chr(0xC218)
    assert named(korean, unicodedata.normalize("NFD", "Met " + korean + " today."))     # Hangul written as its jamo
    lv_t = chr(0xAE30) + chr(0x11B7)        # a syllable and a final jamo, which compose to the name's first syllable
    assert named(korean, "Met " + lv_t + korean[1:] + " today.")
    hit = X._matcher([PERSON])
    for blob in (fake_embed("Brand voice: plain and warm.").tobytes(), bytes(3072)):
        wide = sum(len(t) for t, _ in X._readings(blob, hit)) - len(X._cell_text(blob) or "")
        assert wide * 4 < sum(map(len, X._wide_texts(blob))), wide


def test_the_check_after_the_erase_reads_wide_text_too(home):
    """_traces, the check's row reading, on its own: the dry run's reading would hide a miss here."""
    from apolaki.agent import erase as X
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, body BLOB)")
    con.execute("INSERT INTO notes VALUES ('a1', ?)", ("Call Marisol Quintero.".encode("utf-16-le"),))
    assert X._traces(con, X._matcher([PERSON])) == [("notes", "body", "a1")]


def test_a_near_match_in_wide_text_is_listed_once(home):
    """UTF-16 text is read whole at one start and all but its first letter at the next, in the other byte order: the
    near-match in it is one word to rule on, listed once."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quintero leads the tenant union.")
    s.close()
    con = raw_db(home)
    con.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, body BLOB)")
    con.execute("INSERT INTO notes VALUES ('n1', ?)", (("Call " + QUINTEROVA).encode("utf-16-le"),))
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert [n["word"] for n in p.near] == ["marisol quinterova"], X.describe(p)


# ---- round 5: wide text in a TEXT cell (2026-11-04 verifier, round 4: a false success) -----------------------------
# CAST(... AS TEXT) keeps a wide text's bytes, and Python reads them back as UTF-8 when they are valid: an ASCII name in
# UTF-16 or UTF-32 comes back with a NUL between its letters, and a Cyrillic one in UTF-16 with control characters and
# no NUL in the name at all. A writer that read the bytes as Latin-1 stores each byte as a letter. Before round 5 only
# a blob was read in the wide encodings, and the erase recorded verified:true with the name's bytes still there.
def cast(text, encoding):
    return "CAST(? AS TEXT)", text.encode(encoding)


def as_latin1(text, encoding):
    return "?", text.encode(encoding).decode("latin-1")


CYRILLIC = WIDE_TEXTS[2]
WIDE_TEXT_CELLS = [(cast, "utf-16-le", WIDE_TEXTS[0]),           # the verifier's first case
                   (as_latin1, "utf-16-le", WIDE_TEXTS[0]),      # the verifier's second case
                   (cast, "utf-16-be", WIDE_TEXTS[0]), (cast, "utf-32-le", WIDE_TEXTS[0]),
                   (cast, "utf-32-be", WIDE_TEXTS[0]), (as_latin1, "utf-32-le", WIDE_TEXTS[0]),
                   (as_latin1, "utf-16-le", WIDE_TEXTS[1]),      # accented: CAST of these bytes isn't valid UTF-8
                   (as_latin1, "utf-32-be", WIDE_TEXTS[1]),
                   (cast, "utf-16-le", CYRILLIC), (cast, "utf-16-be", CYRILLIC), (as_latin1, "utf-16-le", CYRILLIC)]
WIDE_TEXT_IDS = [f"{form.__name__}-{e}-{['ascii', 'accented', 'cyrillic'][WIDE_TEXTS.index(t)]}"
                 for form, e, t in WIDE_TEXT_CELLS]


@pytest.mark.parametrize("form,encoding,name_text", WIDE_TEXT_CELLS, ids=WIDE_TEXT_IDS)
def test_a_name_in_wide_text_in_a_text_cell_of_a_hand_added_table_is_refused(home, form, encoding, name_text):
    from apolaki.agent import erase as X
    name, text = name_text
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    s.close()
    sql, value = form(text, encoding)
    con = raw_db(home)
    con.execute("CREATE TABLE att2 (id TEXT, body TEXT)")
    con.execute(f"INSERT INTO att2 VALUES ('a1', {sql})", (value,))
    con.commit()
    [(kind,)] = con.execute("SELECT typeof(body) FROM att2").fetchall()
    con.close()
    assert kind == "text", "the setup lost its point"
    p = X.plan(name)
    assert p.db_other == [{"table": "att2", "column": "body", "rows": 1}], X.describe(p)
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(name, confirm=p.code, by="x", reason="asked")


@pytest.mark.parametrize("form,encoding", [(as_latin1, "utf-32-le"), (cast, "utf-32-le"), (cast, "utf-16-le"),
                                           (as_latin1, "utf-16-be")],
                         ids=["latin1-utf-32-le (the verifier's third)", "cast-utf-32-le (the verifier's fourth)",
                              "cast-utf-16-le", "latin1-utf-16-be"])
def test_a_name_in_wide_text_in_a_text_column_on_a_memory_takes_the_memory(home, form, encoding):
    """A hand-added TEXT column on memories is a column of the memory: the memory goes whole, and the bytes with it."""
    from apolaki.agent import erase as X
    name, text = WIDE_TEXTS[0]
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    kept = s.store("Unrelated note about the garden.")
    s.close()
    sql, value = form(text, encoding)
    con = raw_db(home)
    con.execute("ALTER TABLE memories ADD COLUMN note TEXT")
    con.execute(f"UPDATE memories SET note = {sql} WHERE id = ?", (value, kept))
    con.commit()
    con.close()
    p = X.plan(name)
    assert kept in [m["id"] for m in p.memories], X.describe(p)
    assert p.checks() == ["column:memories.note"]
    X.erase(name, confirm=p.code, by="x", reason="asked", checked=p.checks())
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    assert name.encode(encoding) not in raw and "Quintero".encode(encoding) not in raw
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True


def test_a_wide_text_blob_in_the_content_column_takes_the_memory(home):
    """The verifier's fifth case, which round 4 already handled: the memory's own text, as a UTF-16 blob."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store("Marisol Quintero leads the tenant union.")
    kept = s.store("Unrelated note about the garden.")
    s.close()
    con = raw_db(home)
    con.execute("UPDATE memories SET content = ? WHERE id = ?", ("Call Marisol Quintero".encode("utf-16-le"), kept))
    con.commit()
    con.close()
    p = X.plan(PERSON)
    assert kept in [m["id"] for m in p.memories], X.describe(p)
    X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    assert "Quintero".encode("utf-16-le") not in raw
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True


def test_a_text_cell_is_read_wide(home):
    """_readings on its own: a str is read in the wide encodings, as its UTF-8 bytes and, when every character fits,
    its Latin-1 bytes, and with its NULs taken out when it holds one. Round 5 read a str wide only when it held a
    control character other than tab, line feed and carriage return; since round A every one is (the Indic and Chinese
    cases below)."""
    from apolaki.agent import erase as X
    hit = X._matcher([PERSON])

    def named(value):
        return any(X._names_in(hit, t, fold=f) for t, f in X._readings(value, hit))
    for encoding, _ in WIDE[:6]:
        utf8 = "Call Marisol Quintero.".encode(encoding).decode("utf-8")
        assert named(utf8) and named("Call Marisol Quintero.".encode(encoding).decode("latin-1")), encoding
    maria = WIDE_TEXTS[1][0]
    assert X._matcher([maria]).search(X._fold(maria)), "the setup lost its point"
    for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
        latin1 = WIDE_TEXTS[1][1].encode(encoding).decode("latin-1")
        assert any(X._names_in(X._matcher([maria]), t, fold=f)
                   for t, f in X._readings(latin1, X._matcher([maria]))), encoding
    cyrillic = CYRILLIC[1].encode("utf-16-le").decode("utf-8")
    assert "\x00" not in cyrillic[cyrillic.index("\x1c"):cyrillic.index("\x1c") + 10], "the setup lost its point"
    assert any(X._names_in(X._matcher([CYRILLIC[0]]), t, fold=f) for t, f in X._readings(cyrillic,
                                                                                          X._matcher([CYRILLIC[0]])))
    assert named("Call Marisol\x00Quintero.") and named("Call M\x00a\x00r\x00i\x00s\x00o\x00l Quintero.")

    def finds(name, value):
        return any(X._names_in(X._matcher([name]), t, fold=f) for t, f in X._readings(value, X._matcher([name])))
    alone = CYRILLIC[0].split()[0]          # one Cyrillic word: in UTF-16 it holds control characters but no NUL
    assert "\x00" not in alone.encode("utf-16-le").decode("utf-8") and finds(alone, alone.encode("utf-16-le").decode(
        "utf-8")), "a control character other than NUL makes a text cell wide"
    # a Cyrillic and a Thai word whose only control characters in UTF-16 are 0x04, and 0x0e and a line feed
    for word in ("\u0421\u0432\u0435\u0442\u043b\u0430\u043d\u0430", "\u0e2a\u0e21\u0e0a\u0e32\u0e22"):
        assert finds(word, word.encode("utf-16-le").decode("utf-8")), word
    greek = "\u0395\u03bb\u03ad\u03bd\u03b7 \u039c\u03b1\u03c1\u03ba\u03bf\u03c5"     # bytes past 0x7f: Latin-1 only
    assert finds(greek, ("Met " + greek).encode("utf-16-le").decode("latin-1"))
    tamil = "\u0bae\u0bc1\u0bb0\u0bc1\u0b95\u0ba9\u0bcd"           # a vertical tab (0x0b) its only control character
    assert finds(tamil, tamil.encode("utf-16-le").decode("latin-1"))
    assert finds(CYRILLIC[0], "\x00".join(CYRILLIC[1]))             # past Latin-1, a NUL between every letter
    # 12 wide readings from each source of bytes: ASCII text has one (its UTF-8 and Latin-1 bytes are the same), text
    # within Latin-1 two, text past it one (it has no Latin-1 bytes)
    assert [len(X._wide_texts(v)) for v in ("Call\x00Marisol", "Caf\u00e9\x00 au lait",
                                            "\u041c\x00 Marisol")] == [12, 24, 12]
    for plain in ("Marisol Quintero", "Line one\nLine two\tthree\r\n", "Caf\u00e9 \u041c\u0430\u0440\u0438\u044f"):
        assert [t for t, _ in X._readings(plain, hit)][0] == plain and len(X._wide_texts(plain)) >= 12, repr(plain)
    # what round 5 didn't read: no control character but tab, line feed or carriage return (one Devanagari word in
    # UTF-16), or none at all (a Chinese name in UTF-16, which is plain ASCII)
    for name in INDIC + [CHINESE]:
        for encoding in ("utf-16-le", "utf-16-be"):
            cell = name.encode(encoding).decode("utf-8")
            assert not re.search("[\x00-\x08\x0b\x0c\x0e-\x1f]", cell), "the setup lost its point"
            assert finds(name, cell), (name, encoding)


def test_the_check_after_the_erase_reads_wide_text_in_a_text_cell_too(home):
    """_traces, the check's row reading, on its own: the dry run's reading would hide a miss here."""
    from apolaki.agent import erase as X
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, body TEXT)")
    con.execute("INSERT INTO notes VALUES ('a1', CAST(? AS TEXT))", ("Call Marisol Quintero.".encode("utf-32-le"),))
    con.execute("INSERT INTO notes VALUES ('a2', ?)", ("Call Marisol Quintero.".encode("utf-16-be").decode("latin-1"),))
    assert X._traces(con, X._matcher([PERSON])) == [("notes", "body", "a1"), ("notes", "body", "a2")]


# ---- round A (2026-11-07, docs/KNOWN_LIMITS.md section 5) -----------------------------------------------------------
def rows_as_bytes(home):
    """Every row of every ordinary table, TEXT read as bytes (a cell that isn't UTF-8 stops sqlite3's own reading)."""
    con = sqlite3.connect(str(home / "db" / "apolaki.db"))
    con.text_factory = bytes
    try:
        tables = [r[0].decode() for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql NOT "
                                                     "LIKE '%VIRTUAL%'")]
        return {t: sorted(map(repr, con.execute(f'SELECT * FROM "{t}"').fetchall())) for t in tables}
    finally:
        con.close()


NOT_UTF8 = "Caf\u00e9 meeting moved to Friday.".encode("latin-1")         # \xe9 alone isn't UTF-8


def test_a_text_cell_that_isnt_utf8_is_listed_and_the_erase_refuses_with_its_own_exit_code(home, capsys):
    """Item 2: before round A the dry run stopped with a Python traceback (sqlite3 can't decode the cell) and exit 1,
    the code of an incomplete erase. Now the dry run lists the cell and the erase refuses, before changing anything,
    with its own exception and exit code 4, whether or not the cell seems to name the person."""
    import apolaki.engine as E
    from apolaki.agent import erase as X
    ids = plant(home)
    con = raw_db(home)
    con.execute("UPDATE memories SET source = CAST(? AS TEXT) WHERE id = ?", (NOT_UTF8, ids["m3"]))
    con.commit()
    [(kind,)] = con.execute("SELECT typeof(source) FROM memories WHERE id = ?", (ids["m3"],)).fetchall()
    con.close()
    assert kind == "text", "the setup lost its point"
    with pytest.raises(sqlite3.OperationalError):          # what sqlite3 does with it on its own
        db_rows(home, "SELECT source FROM memories")
    p = X.plan(PERSON)
    assert p.unreadable == [{"table": "memories", "column": "source", "rows": 1}]
    assert p.counts()["unreadable_cells"] == 1 and not p.empty()
    assert "WILL REFUSE (exit code 4)" in X.describe(p) and "table memories, column source: 1 cell(s)" in X.describe(p)
    before = rows_as_bytes(home)
    with pytest.raises(X.EraseUnreadable, match="Nothing was removed"):
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert rows_as_bytes(home) == before and not (home / "erasures.jsonl").exists()
    assert E.main(["erase-person", PERSON]) == 0
    assert "isn't valid UTF-8" in capsys.readouterr().out
    assert E.main(["erase-person", PERSON, "--confirm", p.code, "--by", "x", "--reason", "asked"]) == 4
    assert "not erased: the database holds text that isn't valid UTF-8" in capsys.readouterr().err
    assert rows_as_bytes(home) == before


def test_the_check_after_the_erase_reports_a_text_cell_that_isnt_utf8(home):
    """leftovers() on its own: such a cell appearing during an erase makes it incomplete, never verified."""
    from apolaki.agent import erase as X
    ids = plant(home)
    con = raw_db(home)
    con.execute("UPDATE memories SET archive_reason = CAST(? AS TEXT) WHERE id = ?", (NOT_UTF8, ids["m3"]))
    con.commit()
    con.close()
    found = X.leftovers(["Dev Okafor"], home)
    assert any("column archive_reason: text that isn't valid UTF-8" in f for f in found), found


# Item 1: the erase certifies only Apolaki's own schema. Round 5's verifier found a false success, verified:true with
# the name still in the database, for UTF-16 of a single Devanagari, Gurmukhi or Malayalam word in a text cell (48 of 48
# plants: every high byte is a tab, line feed or carriage return, which round 5's hint skipped) and of a Chinese name
# (its UTF-16 is plain ASCII). Two parts close it: every text cell is read wide, and a table, column, view or trigger
# Apolaki's code didn't make is listed and needs a person's check, whatever it holds.
INDIC = ["\u092e\u094b\u0939\u0928", "\u0938\u0941\u0928\u0940\u0924\u093e",       # Devanagari
         "\u0a2e\u0a4b\u0a39\u0a28", "\u0d2e\u0d4b\u0d39\u0d7b"]                         # Gurmukhi, Malayalam
CHINESE = "\u4f50\u4f50\u6728"


def hand_add(home, *statements, params=()):
    con = raw_db(home)
    for i, sql in enumerate(statements):
        con.execute(sql, params[i] if i < len(params) else ())
    con.commit()
    con.close()


def test_apolakis_own_schema_needs_no_persons_check(home):
    """What memory_store makes, vector indexes included where sqlite-vec loads, and SQLite's own counters, is
    Apolaki's: nothing to check. An old database the store migrated (archive columns added later) is Apolaki's too."""
    from apolaki.agent import erase as X
    plant(home)
    p = X.plan(PERSON)
    assert p.hand_added == [] and p.checks() == [] and "Not Apolaki's" not in X.describe(p)
    old = home.parent / "old"
    (old / "db").mkdir(parents=True)
    con = sqlite3.connect(str(old / "db" / "apolaki.db"))
    con.executescript(ms.SCHEMA.replace("    archived INTEGER DEFAULT 0,\n    archived_at TEXT,\n"
                                        "    archive_reason TEXT\n", "    source_x TEXT\n").replace(
        "    source TEXT DEFAULT '',\n    source_x TEXT", "    source TEXT DEFAULT ''"))
    assert "archived" not in [r[1] for r in con.execute("PRAGMA table_info(memories)")], "the setup lost its point"
    con.close()
    ms.ApolakiMemoryStore(db_path=old / "db" / "apolaki.db", wiki_path=old / "wiki").close()
    assert X.plan(PERSON, home=old).hand_added == []


def test_what_apolaki_didnt_make_is_listed_and_the_erase_refuses_until_a_person_checks_each(home, capsys):
    import apolaki.engine as E
    from apolaki.agent import erase as X
    plant(home)
    hand_add(home, "CREATE TABLE campaign_notes (id TEXT PRIMARY KEY, body TEXT)",
             "INSERT INTO campaign_notes VALUES ('n1', 'Spring appeal: call the food bank.')",
             "CREATE INDEX idx_campaign_notes_body ON campaign_notes(body)",
             "ALTER TABLE memories ADD COLUMN note TEXT",
             "CREATE VIEW recent AS SELECT id FROM memories",
             "CREATE TRIGGER touched AFTER UPDATE ON memories BEGIN SELECT 1; END")
    p = X.plan(PERSON)
    assert p.checks() == ["column:memories.note", "table:campaign_notes", "trigger:touched", "view:recent"]
    assert p.db_other == [] and p.counts() == X.plan(PERSON).counts()
    text = X.describe(p)
    assert "Not Apolaki's (4)" in text and "WILL REFUSE" in text and "--checked 'table:campaign_notes'" in text
    before = snapshot(home)
    for checked, match in [((), "nobody has said they checked: column:memories.note, table:campaign_notes, "
                                "trigger:touched, view:recent"),
                           (("table:campaign_notes",), "3 thing\\(s\\) Apolaki didn't create"),
                           ((*p.checks(), "table:other"), "didn't list as added by hand")]:
        with pytest.raises(X.EraseError, match=match):
            X.erase(PERSON, confirm=p.code, by="x", reason="asked", checked=checked)
        assert snapshot(home) == before and not (home / "erasures.jsonl").exists()
    args = ["erase-person", PERSON, "--confirm", p.code, "--by", "x", "--reason", "asked"]
    assert E.main(args) == 2 and "Apolaki didn't create" in capsys.readouterr().err
    assert E.main(args + [a for t in p.checks() for a in ("--checked", t)]) == 0
    assert "verified for Apolaki's tables; 4 hand-added table(s), column(s), view(s) or trigger(s) checked by a " \
           "person" in capsys.readouterr().out
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True and rec["verified_for"] == "Apolaki's own tables"
    assert rec["checked_by_person"] == p.checks()


def test_a_new_hand_added_table_alone_changes_the_code(home):
    from apolaki.agent import erase as X
    plant(home)
    code = X.plan(PERSON).code
    hand_add(home, "CREATE TABLE scratch (x TEXT)")
    assert X.plan(PERSON).code != code


def test_a_name_in_a_hand_added_table_in_a_form_the_erase_cant_read_is_never_certified(home):
    """The class, whatever the form: base64 of the name in a hand-added table isn't found (the erase decodes no
    base64), but the table is listed, and the erase refuses until a person says they checked it. At b9bde2f this
    erase recorded verified:true with the name still there."""
    import base64
    from apolaki.agent import erase as X
    plant(home)
    hidden = base64.b64encode(PERSON.encode()).decode()
    hand_add(home, "CREATE TABLE attachments (id TEXT PRIMARY KEY, body TEXT)",
             "INSERT INTO attachments VALUES ('a1', ?)", params=((), (hidden,)))
    p = X.plan(PERSON)
    assert p.db_other == [] and p.checks() == ["table:attachments"], X.describe(p)
    with pytest.raises(X.EraseError, match="nobody has said they checked: table:attachments"):
        X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert db_rows(home, "SELECT body FROM attachments") == [(hidden,)]


@pytest.mark.parametrize("name", INDIC + [CHINESE], ids=["devanagari", "devanagari-6", "gurmukhi", "malayalam",
                                                         "chinese"])
@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_wide_text_with_no_control_character_in_apolakis_own_column_is_found_and_erased(home, name, encoding):
    """Round 5's false success, in one of Apolaki's own columns (a person wrote it there by hand), where no person's
    check stands in: the cell is read wide, the memory goes, and its bytes with it. Before round A this was
    verified:true with the bytes still there."""
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    kept = s.store("Unrelated note about the garden.")
    s.close()
    hand_add(home, "UPDATE memories SET source = CAST(? AS TEXT) WHERE id = ?", params=((name.encode(encoding), kept),))
    [(source,)] = db_rows(home, f"SELECT source FROM memories WHERE id = '{kept}'")
    assert not re.search("[\x00-\x08\x0b\x0c\x0e-\x1f]", source), "the setup lost its point"
    p = X.plan(name)
    assert kept in [m["id"] for m in p.memories] and p.checks() == [], X.describe(p)
    X.erase(name, confirm=p.code, by="x", reason="asked")
    raw = b"".join(f.read_bytes() for f in (home / "db").iterdir() if f.is_file())
    assert name.encode(encoding) not in raw
    [rec] = [json.loads(line) for line in (home / "erasures.jsonl").read_text().splitlines()]
    assert rec["verified"] is True


@pytest.mark.parametrize("name", INDIC[:1] + [CHINESE], ids=["devanagari", "chinese"])
def test_wide_text_with_no_control_character_in_a_hand_added_table_is_found_and_refused(home, name):
    from apolaki.agent import erase as X
    s = open_store(home)
    s.store(f"{name} leads the tenant union.")
    s.close()
    hand_add(home, "CREATE TABLE att2 (id TEXT, body TEXT)", "INSERT INTO att2 VALUES ('a1', CAST(? AS TEXT))",
             params=((), (name.encode("utf-16-le"),)))
    p = X.plan(name)
    assert p.db_other == [{"table": "att2", "column": "body", "rows": 1}] and p.checks() == ["table:att2"]
    with pytest.raises(X.EraseError, match="Nothing was removed"):
        X.erase(name, confirm=p.code, by="x", reason="asked", checked=p.checks())


# Item 4: name forms code can handle. KNOWN_LIMITS section 5 listed each as a form the erase read past, with a false
# success: the separators , ; : and the middle dot, quoted-printable (soft line breaks included), and look-alike letters
# normalize() doesn't fold (small capitals, Cherokee letters that look Latin).
KATAKANA = "\u30de\u30ea\u30bd\u30eb \u30ad\u30f3\u30c6\u30ed"          # "Marisol Quintero" in katakana
NAME_FORMS = [
    ("Contacts: Marisol,Quintero,555-0100", PERSON),                       # a CSV row
    ("Marisol;Quintero;volunteer", PERSON),
    ("organiser:Marisol:Quintero", PERSON),
    ("Marisol\u00b7Quintero leads the union.", PERSON),                    # a middle dot
    ("Marisol\u2027Quintero leads the union.", PERSON),                    # a hyphenation point
    ("\u30de\u30ea\u30bd\u30eb\u30fb\u30ad\u30f3\u30c6\u30ed\u3055\u3093", KATAKANA),   # the katakana middle dot
    ("Thanks to Mar=C3=ADa L=C3=B3pez for hosting.", MARIA),               # quoted-printable
    ("Thanks to Mari=\nsol Quintero for hosting.", PERSON),                # a soft line break
    ("Thanks to Mari=\r\nsol Quintero for hosting.", PERSON),
    ("Thanks to Mari= \r\nsol Quintero for hosting.", PERSON),             # whitespace before the break
    ("Thanks to Marisol=20Quintero.", PERSON),                             # a space written as =20
    ("Thanks to \u1d0d\u1d00\u0280\u026a\ua731\u1d0f\u029f Quintero.", PERSON),        # small capitals
    ("Thanks to \u13b7arisol Quintero.", PERSON),                          # a Cherokee M
    ("Thanks to \uab87arisol Quintero.", PERSON),                          # its small letter
    ("THANKS TO M\u13aaRISOL QUINTERO.", PERSON),                          # a Cherokee A
]
NAME_FORM_IDS = ["comma", "semicolon", "colon", "middle dot", "hyphenation point", "katakana dot", "qp",
                 "qp soft break", "qp soft break crlf", "qp soft break space", "qp space", "small capitals", "cherokee",
                 "cherokee small", "cherokee a"]


@pytest.mark.parametrize("text,name", NAME_FORMS, ids=NAME_FORM_IDS)
def test_a_name_in_a_form_round_a_reads_is_found_and_erased(home, text, name):
    from apolaki.agent import erase as X
    s = open_store(home)
    mid = s.store(text)
    kept = s.store("Brand voice: plain and warm.")
    s.close()
    p = X.plan(name)
    assert [m["id"] for m in p.memories] == [mid], X.describe(p)
    X.erase(name, confirm=p.code, by="the data lead", reason="asked to be removed")
    assert [r[0] for r in db_rows(home, "SELECT id FROM memories")] == [kept]


@pytest.mark.parametrize("tag", ["guest: Mari=\nsol Quintero", "guest: Mar=C3=ADa L=C3=B3pez"], ids=["soft", "bytes"])
def test_quoted_printable_in_escaped_tags_is_read_too(home, tag):
    """store() writes tags with json.dumps, so the soft line break is a backslash-n on disk: escapes are decoded, then
    the quoted-printable."""
    from apolaki.agent import erase as X
    s = open_store(home)
    tagged = s.store("Seating plan for the gala.", tags=[tag])
    s.close()
    name = MARIA if "C3" in tag else PERSON
    assert "\\n" in db_rows(home, "SELECT tags FROM memories")[0][0] or "C3" in tag, "the setup lost its point"
    assert [m["id"] for m in X.plan(name).memories] == [tagged]


@pytest.mark.parametrize("probe", ["\u1d0d\u1d00\u0280\u026a\ua731\u1d0f\u029f", "\u13b7arisol", "\uab87arisol",
                                   "M\u13aaRISOL", "\u0262\u0274\u028f\u0299\u029c\u1d04\u1d05\u1d07\u1d0a\u1d0b"])
def test_the_byte_fold_reads_look_alikes_like_the_full_fold(probe):
    from apolaki.agent import erase as X
    assert X._fold_bytes(probe.encode()) == X._fold(probe) and X._fold(probe).isascii()


def test_a_living_orthographys_letters_are_not_folded_to_latin():
    """Icelandic thorn and Ewe's f, gamma and v with hook stay themselves: a name in them isn't another Latin name."""
    from apolaki.agent import erase as X
    for word in ("\u00fe\u00f3ra", "\u0192ia", "\u0263\u025b", "\u028bevi"):
        assert not X._fold(word).isascii() and not X._fold_bytes(word.encode()).isascii(), word


# Item 5: the erase's reach. Approval-queue items, grant drafts and the grant hunt's files aren't memory, and the erase
# never changes them; the dry run lists each place in them that names the person, read as memory is read, so a person
# sees every place the name remains. Before round A it listed only the files its byte reading found, by name and count.
def test_records_that_arent_memory_are_listed_place_by_place_and_never_changed(home):
    from apolaki.agent import erase as X
    plant(home)
    blog = home / "approval-queue" / "20261102_000000_blog.json"
    blog.write_text(json.dumps({"id": "20261102_000000", "content": "<p>Thanks to Marisol&nbsp;Quintero.</p>",
                                "status": "approved", "context": "spring appeal"}))
    (home / "grant-drafts").mkdir()
    (home / "grant-drafts" / "opp1_draft.md").write_text("# Letter\n\nWe thank our partners.\n\nContact: Marisol\n"
                                                         "Quintero, board.\n")
    (home / "grant-hunt" / "outcomes.jsonl").write_text(
        json.dumps({"key": "OPP-1", "reason": "declined"}) + "\n"
        + json.dumps({"key": "OPP-2", "reason": "the program officer, Marisol Quintero, said no"}) + "\n")
    (home / "grant-hunt" / "outbox").mkdir()
    (home / "grant-hunt" / "outbox" / "post.txt").write_bytes("Draft post thanking Marisol Quintero.".encode("utf-16"))
    hit = X._matcher([PERSON])
    assert not any(hit.search(t) for t in X._byte_texts(blog.read_bytes())), "the setup lost its point"
    records = [f for f in home.rglob("*") if f.is_file() and f.relative_to(home).parts[0] in
               ("approval-queue", "grant-drafts", "grant-hunt")]
    before = {f: f.read_bytes() for f in records}
    p = X.plan(PERSON)
    assert {(r["file"], r["kind"], r["where"]) for r in p.records} == {
        ("approval-queue/20261101_000000_social.json", "approval-queue item (pending)", "content"),
        ("approval-queue/20261102_000000_blog.json", "approval-queue item (approved)", "content"),
        ("grant-drafts/opp1_draft.md", "grant draft", "the file, across lines"),
        ("grant-hunt/outcomes.jsonl", "grant hunt file", "line 2, reason"),
        ("grant-hunt/outbox/post.txt", "grant hunt file", "the file, read as UTF-16, UTF-32 or Latin-1")}
    assert len(p.records) == 5
    assert [r["text"] for r in p.records if r["file"].endswith("social.json")] == [
        "Thanks to Marisol Quintero for hosting."]
    text = X.describe(p)
    assert "Records that aren't memory, so NOT changed by this command: the name is in 5 place(s) in 5 file(s)" in text
    assert "approval-queue/20261102_000000_blog.json (approval-queue item (approved)), content: <p>Thanks to " \
           "Marisol&nbsp;Quintero.</p>" in text
    assert "quarantine/q_0123456789abcdef.json" in text and "seen.json" not in text
    done = X.erase(PERSON, confirm=p.code, by="x", reason="asked")
    assert {f: f.read_bytes() for f in records} == before
    assert {path for path, _ in done["elsewhere"]} >= {r["file"] for r in p.records}
