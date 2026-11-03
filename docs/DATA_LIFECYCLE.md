# What Apolaki keeps, about whom, for how long, and who can erase it

Everything below lives in one folder, `$APOLAKI_HOME` (default `~/.apolaki`). **Nothing in it expires.** Every file
stays until a person removes it; Apolaki deletes nothing on its own. The one command that deletes memory is
`erase-person`, at the end.

| Where | What it holds | About whom |
|---|---|---|
| `brand.json` | the organisation's name, voice and reviewers | the organisation; reviewers by role or name |
| `db/apolaki.db` (+ `-wal`, `-shm`) | memories (text, type, tags, source) and an embedding of each; an entity graph that extracts the names of people, organisations and places from every memory automatically, with an embedding of each name, the sentence each was mentioned in, and which names appear together; wiki pages | anyone a memory mentions |
| `wiki/` | a generated page per entity: what it is connected to, and the memories that mention it | anyone a memory mentions |
| `approval-queue/` | every draft, the brief it came from, its checks, and the reviewer's decision, note and name | anyone a brief or draft mentions; reviewers |
| `engine_beliefs.json`, `engine_beliefs_log.jsonl` | reviewers' decisions kept as beliefs when learning is on, and every change to them | reviewers, and anyone their notes mention |
| `grant-hunt/` | listings and funder pages seen, drafts and their posts (`outbox/`), daily logs, learning's switch, pause and logs, the outcome log | organisations; sometimes a named contact in a listing; whoever an outcome's reason cites |
| `quarantine/` | outside text the injection screen held, whole, with where it came from | whoever wrote or is named in it |
| `erasures.jsonl` | each erase: who ran it, why, when, how much; never the name | the person who ran it |
| `STOP` | why scheduled work is stopped, and who stopped it | the person who stopped it |

Copies outside `$APOLAKI_HOME` are out of Apolaki's reach: drafts posted to the review channel, backups of the folder,
and any repository it was committed to.

**Keep people out where you can.** Write roles, not names, in briefs, reviewer notes and an outcome's source ("the
program officer's email", not their name). Archiving a memory hides it from Apolaki but keeps it, its embedding and
its graph entries: archive is for Apolaki's own beliefs, not for someone's personal data.

## Erasing a person

```bash
python -m apolaki.engine erase-person "NAME" --alias "OTHER FORM"        # a dry run: nothing changes
python -m apolaki.engine erase-person "NAME" --alias "OTHER FORM" --confirm CODE --by WHO --reason WHY
```

Stop the scheduled jobs and the MCP server first (docs/STOPPING.md): the erase needs the database to itself.

The dry run lists every memory (archived ones too), entity, graph row, wiki page and engine belief that names the
person, and every other file in `$APOLAKI_HOME` the name appears in. The erase removes exactly what the dry run
listed, if the code still matches: memories with their embeddings, the person's entities and the entities that came
only from those memories, graph rows, wiki pages (pages that named the person are rebuilt without them), beliefs,
and the name in the belief log. It rebuilds the vector indexes, compacts the database so no deleted bytes stay in
it, then checks byte by byte and with a second dry run. A check that still finds the name is an error.

What it leaves to a person: the files the dry run lists as "not erased" (approval-queue items, grant-hunt files, the
quarantine, logs, backups). They are records of what was drafted, reviewed or received, and are edited or deleted
by hand. It finds the person only by the name and aliases given, so list nicknames and other spellings as aliases.
A memory that names the person goes whole.

Who can erase: anyone who can run commands as the account that owns `$APOLAKI_HOME`. There is no erase over MCP,
and nothing erases on Apolaki's own initiative.

## An open question for the project lead

Apolaki's licence carries the SAFE-AI module, whose first requirement, Memory Sovereignty, says no external system
may read, modify or delete a persistent agent's memories without its explicit consent. `erase-person` deletes
memories on a person's command, for a third party's request to be forgotten. Whether Apolaki counts as a persistent
agent here, and if so how its consent is sought or the deletion justified, is not decided in code. Until it is, each
erase is recorded in `erasures.jsonl` without the name, so the record of what was done to Apolaki's memory survives.
