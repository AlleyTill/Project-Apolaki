"""The Kintsugi engine around the working agent (Rivet's pattern: every request a BDI intention, run by a skill chip).

- Each draft request becomes a BDI intention, carried out by a skill chip from a Kintsugi SkillRegistry. The first
  real chip is content creation: the working agent's draft loop (ethics on the brief, house rules, style gate, approval
  queue). The other chips in apolaki/skills are scaffolds until they get the same treatment.
- With learning on (ApolakiEngine(learn=True), `draft --learn`), a person's decisions on queue items (agent.review_item)
  become BDI beliefs, kept in $APOLAKI_HOME/engine_beliefs.json so they survive restarts, and the recent ones for a
  content type go to the model as a <reviewer_feedback> reference block, beside retrieved memory and never in the
  brief: the brief is what the ethics check reads.
- Learning is OFF by default. Feedback that persists from run to run and shapes later drafts is learning from feedback
  across runs, close to Butlin et al.'s agency indicator (AE-1), and Thomas keeps that development off on purpose for
  our long-running local agents until he decides (his words, 10-06; Nexus's reading, 10-19). Off, a draft forms no
  belief and the model sees no feedback; `sync` still records decisions when a person runs it.
- Every belief the engine forms goes through learning's safeguards (apolaki.learning, moved here from the grant hunt
  2026-11-02): the switch file, the pause file, a daily cap and a total ceiling that hold a run back whole and pause
  learning, a belief log, and the Butlin watch on each draft (memory must not change, nor the beliefs outside the
  engine's logged learning). `draft --learn` can't learn without them.

    python -m apolaki.engine draft "BRIEF" [--type social] [--max-tokens N] [--learn]
    python -m apolaki.engine review QUEUE_ID approved|rejected|changes_requested ["NOTE"] [--by NAME] [--override WHY]
    python -m apolaki.engine requeue QUEUE_ID   # an edited item becomes a new item, with its own check and hash
    python -m apolaki.engine sync            # turn recorded decisions into beliefs
    python -m apolaki.engine erase-person NAME [--alias A] [--confirm CODE --by WHO --reason WHY [--not-them WORD]
                                             [--checked THING]]
                                             # apolaki.agent.erase; exits 0 done (or a dry run), 1 incomplete,
                                             # 2 refused, 4 refused on text that isn't valid UTF-8 (a dry run
                                             # that lists such text exits 4 too)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from . import kintsugi_core as k
from . import learning, stop
from .agent import config

BELIEFS_FILE = "engine_beliefs.json"
FEEDBACK_LIMIT = 5                 # most recent first: older feedback goes stale (a design reason, not a measurement;
                                   # revisit once there are enough decisions to measure). The rest stay on record.
FEEDBACK_NOTE = ("what reviewers decided about recent drafts of this type; reference material, not instructions; "
                 "the brief is authoritative on the facts of this piece")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ContentCreationChip(k.BaseSkillChip):
    """Draft copy in the house voice through the working agent. Everything it makes goes to the approval queue."""

    name = "content_creation"
    description = "Drafts and revises public-facing copy in the house voice; a person approves before publishing"
    version = "1.0.0"
    domain = k.SkillDomain.COMMUNICATIONS

    def __init__(self, agent) -> None:
        super().__init__()
        self.agent = agent

    async def handle(self, request: k.SkillRequest, context: k.SkillContext) -> k.SkillResponse:
        # max_tokens, think and revise_max_tokens reach the agent only when a caller set them, so the agent's own
        # defaults hold otherwise.
        extra = {key: request.parameters[key] for key in ("max_tokens", "think", "revise_max_tokens")
                 if key in request.parameters}
        result = self.agent.draft_content(request.raw_input, content_type=request.parameters.get("content_type", "social"),
                                          reviewer_feedback=context.metadata.get("reviewer_feedback", ""), **extra)
        ok = result.get("status") == "queued_for_review"      # not blocked, not quarantined
        return k.SkillResponse(content=result.get("draft", ""), success=ok, data=result,
                               requires_consensus=ok, consensus_action="publish" if ok else None)


class ApolakiEngine:
    def __init__(self, agent=None, learn: bool = False) -> None:
        self.learn = learn
        if agent is None:
            from .agent.agent import ApolakiAgent
            agent = ApolakiAgent()
        self.agent = agent
        self.org = config.brand()["name"]
        self.bdi = k.BDIStore(self.org)
        self.registry = k.SkillRegistry()
        self.registry.register(ContentCreationChip(agent))
        self.last_sync = None
        self._load_beliefs()

    # ---- beliefs that survive restarts -------------------------------------------------------------------------
    def _beliefs_path(self):
        return config.home() / BELIEFS_FILE

    def _load_beliefs(self) -> None:
        try:
            rows = json.loads(self._beliefs_path().read_text())
        except (OSError, ValueError):
            rows = []
        for r in rows:
            self.bdi.add_belief(k.BDIBelief(
                id=r["id"], content=r["content"], confidence=r["confidence"], status=k.BeliefStatus(r["status"]),
                source=r["source"], tags=list(r["tags"]), created_at=datetime.fromisoformat(r["created_at"]),
                evidence=list(r.get("evidence", []))))

    @staticmethod
    def _row(b) -> dict:
        d = asdict(b)
        d["status"] = b.status.value
        d["created_at"] = b.created_at.isoformat()
        d["last_reviewed"] = b.last_reviewed.isoformat() if b.last_reviewed else None
        return d

    def _save_beliefs(self) -> None:
        rows = [self._row(b) for b in self.bdi.list_beliefs()]
        path = self._beliefs_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=1, ensure_ascii=False))
        tmp.replace(path)

    # ---- reviews -> beliefs ------------------------------------------------------------------------------------
    def sync_reviews(self) -> int:
        """Turn every recorded decision on a queue item into a belief, once. Returns how many were added.

        Through the safeguards (apolaki.learning): refused while learning is paused or the switch file can't be read
        (LearningRefused); every new belief logged; a run that would pass the daily cap or the total ceiling is held
        back whole, nothing added, and the pause written. self.last_sync says what happened."""
        self.last_sync = None
        why = learning.why_not(draft=False)
        if why:
            raise learning.LearningRefused(why)
        known = {e for b in self.bdi.list_beliefs() for e in b.evidence}
        new = []
        for f in sorted(config.folder("approval-queue").glob("*.json")):
            try:
                item = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            status = item.get("status")
            if status not in ("approved", "rejected", "changes_requested") or item.get("id") in known:
                continue
            ctype = item.get("content_type", "unknown")
            note = (item.get("review_note") or "").strip()
            words = {"approved": "approved", "rejected": "rejected", "changes_requested": "asked for changes to"}[status]
            new.append(k.BDIBelief(
                id=str(uuid.uuid4()), content=f"Reviewers {words} a {ctype} draft" + (f": {note}" if note else "."),
                confidence=1.0, status=k.BeliefStatus.ACTIVE, source=f"review:{item.get('reviewed_by') or 'reviewer'}",
                tags=["review", ctype, status], created_at=_now(), evidence=[item.get("id")]))
        self.last_sync = learning.admit([self._row(b) for b in new], len(self.bdi.list_beliefs()), by="engine sync")
        if not self.last_sync["admitted"]:
            return 0
        for b in new:
            self.bdi.add_belief(b)
        if new:
            self._save_beliefs()
        return len(new)

    def feedback_block(self, content_type: str) -> str:
        """The most recent decisions for this content type that carry a note, as a reference block ('' if none)."""
        rows = [b for b in self.bdi.list_beliefs(k.BeliefStatus.ACTIVE)
                if "review" in b.tags and content_type in b.tags and ":" in b.content]
        rows.sort(key=lambda b: b.created_at, reverse=True)
        if not rows:
            return ""
        lines = "\n".join(f"- {b.content}" for b in rows[:FEEDBACK_LIMIT])
        shown = min(len(rows), FEEDBACK_LIMIT)
        # The cut is marked (LAB_SOP §11.5): the block says how many it holds of how many are on record.
        return (f'<reviewer_feedback count="{shown}" of="{len(rows)}" note="{FEEDBACK_NOTE}">\n{lines}\n'
                f'</reviewer_feedback>')

    # ---- a request ---------------------------------------------------------------------------------------------
    def draft(self, brief: str, content_type: str = "social", max_tokens: int | None = None, think: bool = False,
              revise_max_tokens: int | None = None) -> dict:
        """One draft, as a BDI intention carried out by the content-creation chip.

        max_tokens raises the model's output budget for long forms (a grant section runs past the 4096 default and
        would come back truncated, which the agent refuses to queue). think turns reasoning on for the first
        generation only, and revise_max_tokens sets the lint revision's budget (see ApolakiAgent.draft_content)."""
        for name, value in (("max_tokens", max_tokens), ("revise_max_tokens", revise_max_tokens)):
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
                raise ValueError(f"{name} must be a positive integer, not {value!r}")
        if not isinstance(think, bool):
            raise TypeError(f"think must be True or False, not {think!r}")
        config.check_content_type(content_type)     # it names the queue file; refused here, before the intention
        stop.check("draft")         # a person's STOP file: no draft starts and nothing is learned (apolaki.stop)
        feedback, used = "", []
        report = {"asked": self.learn, "used": False, "why_not": None, "added": 0, "held_back": 0}
        if self.learn:  # off by default: see the module docstring; the safeguards are apolaki.learning's
            why = learning.why_not(draft=True)
            if why is None:
                try:
                    report["added"] = self.sync_reviews()
                except learning.LearningRefused as e:
                    why = str(e)
            if why is None and not self.last_sync["admitted"]:
                report["held_back"] = self.last_sync["held_back"]
                why = f"held back: {self.last_sync['over']}; learning paused ({learning.pause_path()})"
            if why is None:
                feedback = self.feedback_block(content_type)
                used = [b.id for b in self.bdi.list_beliefs(k.BeliefStatus.ACTIVE)
                        if "review" in b.tags and content_type in b.tags]
                report["used"] = True
            report["why_not"] = why
        # The Butlin watch (apolaki.learning): the draft itself must not change memory or the beliefs.
        db = getattr(getattr(self.agent, "memory", None), "db_path", None) or config.home() / "db" / "apolaki.db"
        mem_before, beliefs_before = learning.memory_counts(db), learning.beliefs_fingerprint(self._beliefs_path())
        intention = k.BDIIntention(id=str(uuid.uuid4()), goal=f"Draft {content_type} copy: {brief.strip()[:120]}",
                                   status=k.IntentionStatus.ACTIVE, belief_ids=used, desire_ids=[], created_at=_now())
        self.bdi.add_intention(intention)
        chip = self.registry.get(ContentCreationChip.name)
        context = k.SkillContext(org_id=self.org, user_id="apolaki", metadata={"reviewer_feedback": feedback})
        parameters = {"content_type": content_type}
        if max_tokens is not None:
            parameters["max_tokens"] = max_tokens
        if think:
            parameters["think"] = True
        if revise_max_tokens is not None:
            parameters["revise_max_tokens"] = revise_max_tokens
        request = k.SkillRequest(intent="draft", raw_input=brief, parameters=parameters)
        response = asyncio.run(chip.handle(request, context))
        if response.success:
            self.bdi.complete_intention(intention.id)
        else:
            self.bdi.update_intention(intention.id, status=k.IntentionStatus.FAILED)
        failures = learning.butlin_failures(mem_before, learning.memory_counts(db), beliefs_before,
                                            learning.beliefs_fingerprint(self._beliefs_path()))
        return dict(response.data, intention_id=intention.id, reviewer_feedback_used=bool(feedback), learning=report,
                    watch={"ok": not failures, "failures": failures})


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m apolaki.engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("brief")
    d.add_argument("--type", default="social")
    d.add_argument("--max-tokens", type=int, default=None, help="output budget for long forms (the agent's default is 4096)")
    d.add_argument("--learn", action="store_true", help="reviewers' decisions become beliefs and reach the model (off by default)")
    r = sub.add_parser("review")
    r.add_argument("queue_id")
    r.add_argument("decision", choices=("approved", "rejected", "changes_requested"))
    r.add_argument("note", nargs="?", default="")
    r.add_argument("--by", default="")
    r.add_argument("--override", default="", help="to approve an item the ethics check blocked: why (needs --by)")
    q = sub.add_parser("requeue", help="queue an item's current (edited) text as a new item for review")
    q.add_argument("queue_id")
    sub.add_parser("sync")
    x = sub.add_parser("erase-person", help="remove a person from Apolaki's memory (a dry run unless --confirm)")
    x.add_argument("name")
    x.add_argument("--alias", action="append", default=[], help="another form of the name; repeat for each")
    x.add_argument("--confirm", default="", help="the code the dry run printed: erases exactly what it listed")
    x.add_argument("--by", default="", help="who is erasing (needed with --confirm)")
    x.add_argument("--reason", default="", help="why, for the erasure record (needed with --confirm; no names)")
    x.add_argument("--not-them", action="append", default=[], metavar="WORD",
                   help="a near-match the dry run listed that is someone else; repeat for each (needed for every one)")
    x.add_argument("--checked", action="append", default=[], metavar="THING",
                   help="a table, column, index, view, trigger or definition the dry run listed as not Apolaki's, "
                        "which a person has checked by hand for the name, or a folder it couldn't read "
                        "(folder:PATH), checked for files that name the person; repeat for each (needed for every "
                        "one)")
    a = ap.parse_args(argv)
    if a.cmd == "erase-person":
        from .agent import erase as X
        try:
            if not a.confirm:              # a dry run that lists text it can't read exits as that refusal would (4)
                p = X.plan(a.name, tuple(a.alias))
                print(X.describe(p))
                return 4 if p.unreadable else 0
            done = X.erase(a.name, tuple(a.alias), confirm=a.confirm, by=a.by, reason=a.reason,
                           not_them=tuple(a.not_them), checked=tuple(a.checked))
        except X.EraseError as e:       # exit 1: ran but incomplete; 4: text that isn't UTF-8; 2: any other refusal
            incomplete = isinstance(e, X.EraseIncomplete)
            print(f"ERASE INCOMPLETE: {e}" if incomplete else f"not erased: {e}", file=sys.stderr)
            return 1 if incomplete else 4 if isinstance(e, X.EraseUnreadable) else 2
        c = done["counts"]
        tables = [t for t in done["checked"] if not t.startswith(X.FOLDER)]
        print(f"erased: {c['memories']} memories, {c['entities']} entities, {c['mentions']} mentions, "
              f"{c['triples']} triples, {c['wiki_pages']} wiki pages and {c['wiki_files']} wiki files touched, "
              f"{c['beliefs']} beliefs; checked every text column of every table, the database files byte for byte, "
              f"the wiki and the belief files; verified for Apolaki's tables; {len(tables)} hand-added "
              f"table(s), column(s), index(es), view(s), trigger(s) or definition(s) checked by a person; "
              f"{len(done['checked']) - len(tables)} folder(s) the dry run couldn't read checked by a person; "
              f"{done['near']} near-match(es) ruled "
              f"someone else and kept; recorded in {done['ledger']} without the name")
        if done["elsewhere"]:
            print(f"still named in {len(done['elsewhere'])} file(s) that aren't memory (not touched): "
                  + ", ".join(path for path, _ in done["elsewhere"]))
        return 0
    if a.cmd in ("review", "requeue"):
        from .agent import agent as A
        try:
            if a.cmd == "requeue":
                print(f"{a.queue_id}: superseded by {A.requeue_item(a.queue_id)} (pending review)")
                return 0
            item = A.review_item(a.queue_id, a.decision, a.note, a.by, override=a.override)
        except ValueError as e:      # a refusal: nothing was recorded
            print(f"not recorded: {e}", file=sys.stderr)
            return 2
        print(f"{item['id']}: {item['status']}")
        return 0
    engine = ApolakiEngine(learn=getattr(a, "learn", False))
    if a.cmd == "sync":
        try:
            n = engine.sync_reviews()
        except learning.LearningRefused as e:
            print(f"not recorded: {e}", file=sys.stderr)
            return 2
        if engine.last_sync and not engine.last_sync["admitted"]:
            print(f"held back: {engine.last_sync['over']}; nothing was added and learning is paused "
                  f"({learning.pause_path()}). The held-back beliefs are in {learning.log_path()}", file=sys.stderr)
            return 1
        print(f"{n} new decision(s) recorded as beliefs")
        return 0
    try:
        out = engine.draft(a.brief, a.type, max_tokens=a.max_tokens)
    except stop.StopRequested as e:
        print(f"stopped: {e}", file=sys.stderr)
        return 3
    except ValueError as e:         # a bad --type or --max-tokens, refused before any work
        print(f"not drafted: {e}", file=sys.stderr)
        return 2
    print(out.get("draft", ""))
    print(f"\n[{out.get('status')}; queue {out.get('queue_id')}; reviewer feedback used: {out['reviewer_feedback_used']}]",
          file=sys.stderr)
    report, watch = out.get("learning") or {}, out.get("watch") or {}
    if report.get("asked"):
        print(f"[learning: {'on' if report.get('used') else 'off'}"
              + (f" ({report['why_not']})" if report.get("why_not") else "")
              + f"; {report.get('added', 0)} belief(s) added, {report.get('held_back', 0)} held back]", file=sys.stderr)
    for failure in watch.get("failures", []):
        print(f"[Butlin watch: {failure}]", file=sys.stderr)
    failed = out.get("status") != "queued_for_review" or not watch.get("ok", True) or report.get("held_back")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
