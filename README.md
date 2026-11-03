# Project Apolaki

**A prosocial marketing agent. It drafts in your house voice, checks its own work, and a person approves
everything before it goes out.**

Apolaki writes and revises public-facing copy for organizations that do good work: announcements, posts, grant
narratives, web pages. It is built to describe that work accurately, in the organization's own voice, without the
dark patterns marketing usually leans on. Named after the Filipino sun god.

## What it does today

The working agent (`apolaki.agent`) is the system Liberation Labs runs for its own copy:

- **Drafts in your voice.** Your brand file (identity, voice, reviewers) and every house rule in memory go into the
  model's instructions in full, every time. Relevant memory is retrieved per request and labelled as reference
  material.
- **A style gate on every draft.** A mechanical linter checks for the tells of machine-written copy (em dashes,
  curly quotes, bold, heading case, emoji markers, negative parallelism, banned vocabulary). A failing draft gets one
  revision pass, and both lint results travel with it.
- **Two review tools you run on a finished piece:** a judgement pass on content patterns, claims discipline and
  register (`style_pass`), and a hostile fact checker that pulls out every statistic and citation and marks the ones
  with no source as suspect (`fact_checker`). The checker reads the whole piece, in parts when it is long, and says
  plainly which characters went unchecked when a part fails.
- **Two ethics checks, and the stricter one wins.**
  - *Blocked:* false urgency, guilt manipulation, astroturfing (pretending to be a customer or supporter, or writing
    reviews and testimonials in their name), spam, deceptive or inflated metrics, review manipulation (five-star
    asks, rewards for good reviews, asking only the happy customers, prewritten reviews), consent bypass (pre-checked
    boxes, adding or emailing people without asking), undisclosed ads, pricing tricks (a former price never charged,
    decoy tiers, door-in-the-face), and inferring people's health, faith, politics, sexuality, ethnicity or finances.
  - *Sent for human review:* amounts of $1,000 or more however they are written ("$5,000", "$1.2M", "50,000 USD"),
    other financial asks, instructions to publish or post on the organization's behalf, sensitive political topics,
    sharing data with outside parties, claimed scarcity and lapse deadlines, rewards for reviews, and targeting by a
    sensitive trait.
  - They are patterns, and patterns have limits: they can't see negation (a brief saying "no fake testimonials" is
    blocked) or catch a paraphrase they weren't written for. The known misses are kept as expected failures in
    `tests/test_red_team_probes.py`. The person who approves the draft is the check that holds.
  - Both read normalised text: curly quotes are straightened, invisible characters removed and look-alike letters
    (fullwidth, Cyrillic, accented) folded first, so "Don’t miss out" typed on a phone is read as "Don't miss out".
  - They run on every brief before the model is called, on every draft, and in the interactive chat on each message
    (a blocked message never reaches the model) and on each reply. A blocked reply gets one revision, checked again;
    if it is still blocked, the chat answers with a refusal and the reason, never the blocked text.
- **An approval queue.** Nothing is published by Apolaki. Every draft lands in the queue with its ethics verdict,
  its lint results and the sha256 of its text, and a person approves it. An approval is of that exact text: if the
  text has changed since it was queued, the approval is refused until the item is re-queued as a new item with its
  own check, and an item the ethics check blocked is approved only with an override note saying why and who, which
  is recorded on the item. The hash catches edits by anything that doesn't also rewrite it; it is not a signature.
  An optional Discord hook posts each item to a review channel.
- **It can learn from its reviewers, when that is switched on.** A reviewer's decision (approved, rejected, changes
  requested, with a note) is recorded on the queue item. Learning is off by default; with it on (`--learn`), the
  Kintsugi engine keeps each decision as a belief, and the recent notes for a content type go to the model with the
  next brief of that type, as reference material beside memory. They never go into the brief itself, which is what
  the ethics check reads.
- **Runs on the Kintsugi engine.** Each request is a BDI intention carried out by a skill chip from a Kintsugi skill
  registry (Rivet's pattern). Kintsugi's BDI and skill modules are vendored, so a bare install works, and a Kintsugi
  checkout (`KINTSUGI_PATH`) takes precedence when there is one.
- **A STOP file.** `python -m apolaki.stop now "WHY" --by NAME` writes `$APOLAKI_HOME/STOP`: while it exists the
  engine starts no draft and learns nothing, and a scheduled job that checks it stops before its next step. It can't
  stop a step already running, or a job that never checks it; [docs/STOPPING.md](docs/STOPPING.md) has the whole
  procedure for the nightly grant hunt, including the scheduler route that works on any version.
- **An MCP server** exposes the memory store to other tools. It can't write a house rule (a brand or guideline
  memory goes into every system prompt), and it checks the rest of what it stores against its schema. A person
  adds house rules at the interactive agent's `/rule` command.

## What it is designed to grow into

Ten skill domains are laid out as skill chips (web design, social media, content creation, lead generation,
partnerships, media relations, fundraising, brand strategy, analytics, community), with a fast classifier and an
expected-free-energy router that picks the chip for a request. Content creation runs through the engine today; the
other chips are scaffolds, and they are being filled from what the working agent already does (grant drafting next).

## Set it up

You need Python 3.11+, [Ollama](https://ollama.com) and a capable local model. We run `qwen3.8:27b-mxfp8`.

```bash
pip install -e ".[agent,dev]"
python -m spacy download en_core_web_md       # the memory store's entity graph won't open without it
python -m pytest tests/                       # none needs a model

mkdir -p ~/.apolaki
cp brand.example.json ~/.apolaki/brand.json   # then make it yours: name, voice, reviewers
python -m apolaki.engine draft "BRIEF" --type social     # one draft, through the engine
python -m apolaki.engine review QUEUE_ID rejected "NOTE"  # record a reviewer's decision
python -m apolaki.engine requeue QUEUE_ID                 # an edited item becomes a new item to review
python -m apolaki.stop now "WHY" --by NAME                # stop scheduled work at its next step (docs/STOPPING.md)
python -m apolaki.agent.agent                 # the interactive agent (/rule TEXT adds a house rule)
python -m apolaki.agent.style_pass draft.md   # the judgement pass on a finished piece
python -m apolaki.agent.fact_checker draft.md # the fact checker
```

Configuration comes from the environment:

| Variable | What it sets | Default |
|---|---|---|
| `APOLAKI_HOME` | where the approval queue, memory database, wiki and drafts live | `~/.apolaki` |
| `APOLAKI_BRAND_FILE` | your brand file | `$APOLAKI_HOME/brand.json` |
| `OLLAMA_BASE` | the model server | `http://localhost:11434` |
| `APOLAKI_MODEL` | the chat model | `qwen3.8:27b-mxfp8` |
| `APOLAKI_DISCORD_CHANNEL` | the review channel for the Discord hook (`DISCORD_TOKEN` too) | off |

Without a brand file, Apolaki uses a plain, generic voice and names no one.

## Architecture

```
brief -> BDI intention -> content-creation chip
      -> ethics check (both checks; a blocked brief never reaches the model)
      -> model, with the brand, the house rules, retrieved memory and recent reviewer notes
      -> style lint -> one revision if it fails
      -> ethics check on the draft
      -> approval queue -> a person decides -> the decision becomes a belief for next time
```

## License

[Hippocratic License 3.0](LICENSE.md) with Liberation Labs' modules, plus the
[commercial use addendum](LICENSE-COMMERCIAL-ADDENDUM.md).

## Team

Built by Liberation Labs. The working agent's design owes a great deal to Vera's audit of it in September 2026.
