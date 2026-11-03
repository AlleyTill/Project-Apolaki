# Stopping the scheduled grant hunt

The grant hunt is the one Apolaki job that runs on its own: a timer starts it every night, it searches for funding
calls, has the local model rate and draft them, and posts drafts and a summary to the team's review channel. Nobody
watches it run. This page is how a person stops it, and how to start it again.

Two routes. The STOP file is the gentle one: the job stops at its next step and the person who finds the file reads
why. The scheduler route stops the job from starting at all, whatever version of it is installed.

## 1. The STOP file

```bash
python -m apolaki.stop now "WHY" --by NAME     # writes $APOLAKI_HOME/STOP with the reason, who and when
python -m apolaki.stop status                   # exit 1 while stopped
python -m apolaki.stop clear                    # resume: the next timed run goes ahead
```

`touch "$APOLAKI_HOME/STOP"` works too, and so does any file or folder of that name, even one that can't be read: a
STOP made in a hurry still stops. `$APOLAKI_HOME` is the job's own folder (the one holding `grant-hunt/`, `db/` and
`approval-queue/`).

What it does:
- `ApolakiEngine.draft` checks it before anything else, so no draft starts and nothing is learned, from any caller.
  This holds as soon as this package version is installed, whatever the job's own code does.
- A job that calls `apolaki.stop.check(step)` before each step stops at the next one, with `StopRequested` naming the
  step and the reason.

What it can't do:
- Stop a step already running. A model call in flight finishes or times out first (a draft can take up to 30
  minutes: 20 for its first generation with reasoning on, 10 for its style revision), then the next check stops
  the job.
- Stop a job that doesn't call `check()`. **A grant hunt deployed before this package version checks nothing
  itself.** With only the package updated, its drafts are refused (each is listed in the summary as a failed draft,
  `StopRequested`), but its search, its triage by the model and its summary post go on. Until the job calls
  `check()` before each step (search, watchlist, each triage, each draft, each post), use route 2 to stop it
  completely.

## 2. The scheduler (works today, on any version)

The job is a launchd LaunchAgent on the machine that runs it. Find its label first, in its own command (a `grep` in
the same pipeline as other searches can match itself):

```bash
launchctl list | grep -i grant
```

Then, with `LABEL` set to what that shows:

```bash
launchctl bootout gui/$(id -u)/LABEL     # unload it: no more timed runs; a run in progress gets SIGTERM
launchctl disable gui/$(id -u)/LABEL     # keep it unloaded across logins and reboots
```

`bootout` alone lasts until the next login, when launchd loads the plist from `~/Library/LaunchAgents/` again;
`disable` is what keeps it off. To start it again:

```bash
launchctl enable gui/$(id -u)/LABEL
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/LABEL.plist
```

To end a run already in progress without touching the schedule, find its process in a command of its own, then
stop it:

```bash
pgrep -fl grant_hunt.py
kill PID        # SIGTERM; its lock is released when the process exits
```

A killed run keeps what it saved: the listings it rated so far, any draft already in the approval queue or the
outbox. The next run carries on from there.

## 3. Stopping only the posts

Moving the review channel's webhook file aside stops the posts and nothing else: the job still runs, rates and
drafts, and keeps the drafts in its outbox folder. Use it when the drafting is fine and the channel needs quiet.

## Who decides

Anyone on the team can stop the job; a person who stops it writes why (`now "WHY" --by NAME`). Starting it again
is for whoever stopped it, once the reason is dealt with.
