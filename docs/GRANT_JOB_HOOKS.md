# What a scheduled grant job calls in this package

The nightly grant job lives with each deployment, not in this package. This package gives it the safeguards below.
Some hold on their own once the package is installed; the others work only when the job calls them.

## Holds without the job changing

- **STOP file.** `ApolakiEngine.draft` refuses while `$APOLAKI_HOME/STOP` exists (`StopRequested`, before any model
  call). A job that catches exceptions per draft lists each one as a failed draft.
- **Injection screen on briefs.** `ApolakiAgent.draft_content` screens the brief first. A job that puts listing or
  page text in its briefs gets `status: "quarantined"` back, with the reason in `ethics.reason`, and the model is
  never called. Treat it like any status other than `queued_for_review`.
- **Learning's safeguards.** With `learn=True` the engine applies the daily cap and total ceiling, reading them from
  the job's switch file (`grant-hunt/learning.json`); it honours the job's pause file (`grant-hunt/learning.paused`)
  and writes it when it holds a run back. Its belief log is `engine_beliefs_log.jsonl`, separate from any log the job
  keeps, so a job that also counts belief changes counts each change once in its own log. An engine pause sends no
  notice: a job that posts notices should read `result["learning"]["held_back"]`.
- **The Butlin watch.** Every draft result carries `watch: {ok, failures}`: memory tables counted before and after,
  and the beliefs fingerprinted around the draft.

## Needs the job to call it

| When | Call | On a refusal |
|---|---|---|
| before each step (search, watchlist, each triage, each draft, each post) | `apolaki.stop.check("STEP")` | `StopRequested`: stop, post nothing more |
| after fetching a listing's details, before triage | `apolaki.grants.intake.admit_listing(KEY, {"hit": hit, "details": details})`: the search hit too, since triage reads its title | `None`: skip it this run; a person reads `python -m apolaki.intake list` |
| after fetching a funder page, before a model reads it | `apolaki.grants.intake.admit_page(URL, text)` | `None`: skip the page |
| for each call a model extracts from a page, before recording it | `admit_listing(KEY, call, kind="watchlist call")` | `None`: don't record it |
| at the end of a run | `result["learning"]`, `result["watch"]` from each draft | report them in the summary |

`admit_listing` screens every string in what it is given, at any depth (the applicant `types` list, nested dicts)
and the dict keys, so pass everything a model will read from that listing in one call.

Count what was quarantined in the run's summary, so the screen's work shows the same way the other gates do.

The outcome log (`grant-hunt/outcomes.jsonl`, `python -m apolaki.grants outcome ...`) is filled in by a person. A job
doesn't read it, and nothing should feed it into triage without the learning switch and Thomas's decision.
