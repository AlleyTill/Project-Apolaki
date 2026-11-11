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
python -m apolaki.engine erase-person "NAME" ... --not-them "WORD"         # once for each near-match, if any
python -m apolaki.engine erase-person "NAME" ... --checked "table:NAME"    # once for each thing Apolaki didn't make
python -m apolaki.engine erase-person "NAME" ... --checked "folder:PATH"   # and each folder the dry run can't read
```

Stop the scheduled jobs and the MCP server first (docs/STOPPING.md): the erase needs the database to itself.

The dry run lists every memory (archived ones too), entity, graph row, wiki page and engine belief that names the
person; each place in an approval-queue item, a grant draft or a grant hunt file that names them, with the text
around it; and every other file in `$APOLAKI_HOME` the name appears in. The erase removes exactly what the dry run
listed, if the code still matches: memories with their embeddings, the person's entities and the entities that came
only from those memories, graph rows, wiki pages (pages that named the person are rebuilt without them) and the wiki
folders that leaves empty, beliefs, and the name in the belief log. It rebuilds the vector indexes, compacts the
database so no deleted bytes stay in it, then checks every text column of every table, the database files byte by
byte, the wiki (every file, and the name of everything in it) and the belief files, and runs a second dry run. A check that still finds the name, or a compaction or log truncation that failed, is an error
(`ERASE INCOMPLETE`, recorded as not verified), never a success.

What counts as the name: case, accents, the common look-alike letters (Cyrillic, Greek and Armenian ones that look
Latin, small capitals, and Cherokee letters that look Latin; not every look-alike, docs/KNOWN_LIMITS.md) and invisible
characters don't matter; the parts of a name may be joined by white space, by any character Unicode counts as
punctuation or a symbol (hyphens and dashes, apostrophes, full stops, underscores, markup characters such as `*`, `[`,
`(` and `/`, commas, semicolons, colons, middle dots, bullets, `&`, `@`, a raised dot, a broken bar, an emoji), or by
nothing ("Jean-Luc Moreau" also finds "Jean Luc Moreau", "JeanLuc Moreau" and "jean_luc_moreau"; "Marisol Quintero"
finds "**Marisol** Quintero", "Marisol/Quintero", "Marisol,Quintero" and "Marisol@Quintero"). A symbol is read that way
before accents and look-alikes are folded, so "Marisol™Quintero" is the name too. The exceptions are the 472 symbols
that are a look-alike of one letter, such as a circled or squared letter ("Ⓐ") or a Kangxi radical: each is read as
that letter, so a name written in circled letters is found, but one between the parts reads as a letter there would.
A middle name or initial between the parts ("Marisol Elena Quintero") isn't found, so give that form as an alias.
Escaped text is read decoded (the store writes tags as JSON, so "L\u00f3pez" on disk is "López"), markup is read
taken out (a Markdown link
"[Marisol](url) Quintero", HTML tags and entities, percent-encoding, the last two decoded until nothing changes, so
"&amp;oacute;" is read as "ó"), and quoted-printable is read decoded ("L=C3=B3pez", soft line breaks included). A blob
(binary data in a column) is read as text too, in Latin-1, UTF-16 and UTF-32, either byte order, with a byte-order mark
or without, and so is every text cell in UTF-16 and UTF-32, except the vector indexes' own chunks, which the erase drops
and refills. A digit after the name is still the name ("marisol.quintero85@...", "@MarisolQuintero1990"). In scripts
written without spaces (Chinese, Japanese, Thai and the like) and in Korean there is no word edge to keep, so a mention
inside a sentence is found, and a character of those scripts next to a name in another script is a separator ("Quintero"
with a Japanese honorific attached). An Arabic name with an attached prefix ("with", "and", "the") is found.

A near-match is the name inside a longer word ("Marisol Quinterova"). It may be someone else, or the person. The dry
run lists every near-match in what the erase keeps, with where it is and the text around it, and the erase refuses
until a person rules on each one: `--not-them "WORD"` (the word exactly as the dry run prints it) says it is someone
else and keeps it; giving it as an `--alias` says it is the person, and the next dry run lists it for removal. The
erasure record lists each near-match ruled someone else by where it is, never by the word. The check after the erase
accepts the name, read without word edges in the database's bytes, only where a ruled near-match stands in a kept row
(or, for a short name, by chance inside a kept embedding's numbers).

If the dry run finds the name in a table or column the erase doesn't remove from, or in the database's schema (a
table, view, trigger or index name or definition, a column default), it lists it and the erase refuses before
changing anything, until a person has dealt with it. So does a text cell, or one of the engine's belief files, that
isn't valid UTF-8 (exit code 4, and the dry run that lists such a cell exits 4 too), since what it says can't be read
with certainty.

The erase certifies only Apolaki's own tables. Every table, column (a generated column too), index, view and trigger
Apolaki's code didn't make is listed in the dry run, whatever it holds, and so is any of Apolaki's own tables and
indexes whose definition says more than its code writes (a default, a constraint, an index's expression); the erase
refuses until a person has checked each by hand and names it with `--checked`, exactly as the dry run prints it
(`table:NAME`, `column:TABLE.COLUMN`, `index:NAME`, `view:NAME`, `trigger:NAME`, `definition:NAME`). An index matters
because an index on an expression keeps that expression's values, which no row holds, and a partial index's `WHERE` is
text in the schema: before November's round A3 one added by hand wasn't listed, and base64 of the name written into
it was certified. The erase doesn't read an index's values; its byte check afterwards finds the name there only as
plain text (and then reports the erase incomplete), so checking an index means reading its definition for what it
computes or filters on. An index SQLite makes itself for a table's `UNIQUE` or `PRIMARY KEY` isn't listed: it holds
only that table's columns. The report then reads "verified for Apolaki's tables; N hand-added ... checked by a
person", and the erasure record lists what the person named.

What it leaves to a person: the records and files the dry run lists as not changed (approval-queue items, grant drafts,
grant-hunt files, the quarantine, logs, backups), including a file whose name names the person, and an empty folder or a
link (one that leads to no file, or to a folder) whose name does. They are records of what was drafted, reviewed or
received, and are edited or deleted by hand. A folder or a link in the wiki whose name names the person, and which the
erase doesn't empty, stays, and the check then reports the erase incomplete: remove it by hand first. A folder under
`$APOLAKI_HOME` that the dry run can't read (it can't list what the folder holds, or can't look at it) is listed
whether or not its name names the person, since it could hold files that do. The erase refuses until a person has
checked each such folder by hand and names it with `--checked "folder:PATH"`. It finds the person only by the name and
aliases given, so list nicknames and other spellings as aliases. A memory that names the person goes whole.

Who can erase: anyone who can run commands as the account that owns `$APOLAKI_HOME`. There is no erase over MCP,
and nothing erases on Apolaki's own initiative.

## An open question for the project lead

Apolaki's licence carries the SAFE-AI module, whose first requirement, Memory Sovereignty, says no external system
may read, modify or delete a persistent agent's memories without its explicit consent. `erase-person` deletes
memories on a person's command, for a third party's request to be forgotten. Whether Apolaki counts as a persistent
agent here, and if so how its consent is sought or the deletion justified, is not decided in code. Until it is, each
erase is recorded in `erasures.jsonl` without the name, so the record of what was done to Apolaki's memory survives.
