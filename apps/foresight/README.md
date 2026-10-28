# Foresight

The layer above Dossier. **Dossier settles what is true; Foresight works out
what it means.** It measures the attention and argument around the subjects
Dossier holds, finds where a subject departs from its own baseline, and answers
questions about it — at a tier you pick, **including one that uses no model at
all**.

Runs at <http://127.0.0.1:8438> inside Forge, or standalone:

```
FORGE_SHARED_DIR=~/Forge/shared \
  .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8438
```

---

## 1. The rule that shapes everything

**Anything a rule can settle, a rule settles.** A z-score cannot hallucinate,
costs nothing, gives the same answer twice and runs on the CPU while the iGPU
is busy. A model is asked only what arithmetic genuinely cannot decide.

That is why `rules` is a **tier**, not a fallback:

| tier | what it is | model |
|---|---|---|
| `rules` | arithmetic and lookups over what is stored | **none** |
| `chat` | the small model — instant, conversational | Qwen3.5-2B |
| `analyse` | the middle model — summarising, judgement | Qwen3.5-4B |
| `think` | the big model, **thinking on**, minutes allowed | an MoE, ideally |

Two consequences:

- **The whole app works with Jan switched off.** Signals, findings and every
  rules answer need no model server at all.
- **Every answer says which tier produced it**, in the interface and in the
  API (`used_model`). A rules answer must never be mistaken for a model's —
  `tests/test_tiers.py` fails if the rules tier so much as touches Jan.

`prefer_rules` (on by default) lets a solver answer even when a model tier was
selected, and says so. The cheapest correct answer wins.

### Why `think` turns thinking on

Dossier forces `enable_thinking: false` everywhere, for a measured reason:
Qwen3.5 will otherwise spend its whole budget narrating and return an empty
`content` field. Foresight keeps that for `chat` and `analyse` and **inverts it
for `think`**, where a long chain of thought is the product rather than waste.
The reasoning is kept and shown in the interface, folded away.

This is also why the `think` tier's preference list starts with a
**mixture-of-experts** model: an MoE activates a fraction of its parameters per
token, so a long reasoning chain is affordable on a CPU. A dense model of the
same nominal size produces the same thinking far too slowly to use. Without one
downloaded it falls back to the 9B already on disk, and the header says so
rather than pretending.

### The no-swap safeguard

This machine has 31 GB and no swap, so exhausting memory locks it up rather
than degrading. `llm.chat()` refuses to start a **thinking** call when
`MemAvailable` is under 3 GB and raises `NotEnoughMemory`; the interface shows
that as a plain answer pointing at the rules tier. Only the thinking tier is
gated — the small models are not the risk.

---

## 2. Where things live

| What | Where | Why |
|---|---|---|
| App code | `~/Forge/apps/foresight/` | `.venv` needs ext4 |
| Signal data | `/run/media/<user>/Forge/ForesightData/` | Grows forever; **everything information-based goes to the drive** |
| Fallback | `~/ForesightData-local/` | Used only when the drive is unplugged; the header says so |
| Dossier's library | `/run/media/<user>/Forge/DossierData/` | **Read only. Never written to.** |

`ForesightData` is a **sibling** of `DossierData`, not a tenant of it. Nothing
here opens a Dossier file for writing, which is what keeps the factual record
something you can trust has not been edited by a planner. The one action
Foresight can take against Dossier — asking it to research a subject — goes
through Dossier's own HTTP API, so its queue and merge rules stay in charge.

One file per subject per source, holding a dated list. A sweep appends today's
reading and rewrites one small file rather than one enormous one, and a corrupt
file costs one series instead of the lot.

---

## 3. The registries

Same rule as Dossier: **discovered, not declared.**

### `signals/` — where attention, money and coverage are read

A signal is **not a fact**. Dossier makes a model prove every claim against a
source sentence; a signal is a *measurement*, and measurements are noisy,
gameable and often meaningless alone. So every source must declare a `caveat`,
and the interface shows it beside the number. A test fails if one is missing.

| source | measures | verified |
|---|---|---|
| `pageviews.py` | Wikipedia daily article views | live |
| `hn.py` | Hacker News stories, points, comments | live |
| `lemmy.py` | Lemmy posts, scores, comments | live |
| `worldbank.py` | nine annual economic indicators | live |
| `fx.py` | the subject's currency per US dollar, daily (ECB) | live |
| `gdelt.py` | share of world coverage and tone | off - rate-limited |
| `news_events.py` | Current Events items linking the subject, per month | see section 8 |

**The first sweep of a source reads five years** (`sweep.HISTORY_DAYS`); later
sweeps read the recent window. Pageviews and exchange rates both serve five
years in one request.

**Reddit is not here.** It returns 403 to anything without OAuth. Adding it
means registering a free API app and a credentials field; the spec supports
`needs_credentials`, and such a source is excluded from automatic sweeps.

### `analysis/` — what turns signals into something worth reading

`trend.py` finds where a subject departs from **its own** baseline — a far
better question than "is this number big". Trump's pageviews are always
enormous; the interesting day is the one where they are enormous *for him*.

It uses a **median-based z-score**, not mean and standard deviation, because
both of those are dragged around by the very spikes being looked for: one huge
day raises the bar enough to hide the next one. The median barely moves.

The noise floor is the **square root of the level** — these are counts, so their
irreducible noise is roughly Poisson. A floor proportional to the median was
tried first and was wrong the other way: it made a collapse from 500 to 5 read
as two sigma.

---

## 4. Tiers and solvers

`tiers.py` is the single place deciding how a question gets answered. Solvers
are the rules tier's repertoire — `movers`, `coverage`, `rank`, `fact`,
`subject` — and they are declared rather than discovered, because each is a
named capability the interface offers as a button.

### Two passes, and the second one is what stopped it refusing everything

Matching used to be keywords alone, and the tier turned away almost everything.
The user typed *"population of australia"*, *"trump"* and *"who is important"*
and was refused all three — while the answers sat in the library.

So a solver may now also declare `handles_stored(question, world)`, a second
pass run **only when no keyword matched**, and allowed to look at what is
actually held. Keyword matching cannot know that "trump" names a subject; the
library can. That gives three behaviours the tier did not have:

- **a bare name is a question.** Naming something held routes to the subject
  solver, so *"trump"* returns everything stored about Donald Trump.
- **a stored fact is a lookup.** *"population of Australia"*, *"currency of
  Japan"*, *"head of government of Germany"*. The fact is matched against the
  keys **that subject actually has**, never a list written in `tiers.py` —
  Dossier harvests a little over a hundred Wikidata properties, and a second
  copy of that list here would go stale the first time one was added. Widening
  what the rules tier can answer is a Dossier-side change with nothing to edit
  here.
- **ranking is arithmetic.** *"who is important"*, *"the biggest countries"*.
  It says what it ranked by, and that the measure is coverage rather than merit.

Where a fact has several stored values — Wikidata keeps every head of
government a country has ever had — the answer says so rather than passing the
list off as a statement about today.

### Matching is whole-word, and an overlap has to be most of both

Solver keyword matching is **whole-word**. It began as a substring check and
routed *"should I move to another country?"* to the coverage solver, because
"country" contains "count".

`world.match_subject()` has the same hazard one level down. It matches a full
name first and then any distinctive word of a name, which is what makes a
surname work — but a single incidental word must not drag a subject in.
*"What is the meaning of life"* matched a company called **Orange Life
Insurance** on the word "life". The overlap must now cover at least half the
question **and** at least half the name.

A solver that grabs the wrong question is worse than one that grabs none: you
get a confident, irrelevant, correct-looking answer, which is precisely what
this app exists not to produce. Both guards are tested.

A refusal now lists what would have worked. A dead end that does not tell you
the next thing to type is most of why this tier felt useless.

---

## 5. Layout

```
web_app.py        FastAPI. Names no source, analyser or tier.
store.py          Drive-or-fallback resolution, atomic writes, series merging
dossier_link.py   Read-only access to Dossier's library + its research API
llm.py            Jan client: four tiers, thinking on for exactly one
tiers.py          How a question is answered, including the no-model tier
world.py          One read-only view shared by the solvers and the models
plans.py          Scenarios, their falsifiable indicators, and the ledger
sweep.py          Gathering, and turning what is stored into findings
signals/          registry + pageviews, hn, lemmy, worldbank, fx, gdelt,
                  news_events
analysis/         registry + trend, level
static/           index.html, app.js, app.css
tests/            100 tests, no network, no model
```

Dossier's `research.fetcher` is imported rather than copied — it carries
per-domain pacing, robots handling and retry that took a session to get right,
and a second copy would drift out of step. `research` is a package name unique
to Dossier and imports nothing from its top level, so putting that directory on
the path cannot shadow anything here.

---

## 6. What is not built yet

This is **stage 1 of four**. Built: signals, breakouts, the tier system with its
rules tier, and the interface. Not built:

- ~~**Scenarios and plans**~~ — built. See section 7.
- ~~**The forecast ledger**~~ — built, and covered by tests, but nothing has
  come due yet: every live indicator was dated months ahead, so no forecast has
  actually been marked `met` or `missed` in anger. Since 2026-10-19 a rules-tier
  scenario can be written two weeks or a month out (section 7), so the first
  real marks are a fortnight away once one is written.
- **Embedding retrieval** — `sentence-transformer-mini` is already in Jan
  (44 MB, on disk). `world.context_for()` is name matching until it lands.
- **The agent loop** — the tool registry with its `reversible` flag, the
  approval queue for irreversible actions, the audit log and the kill switch.
- **The whole personal half** — profile, named folders, browser history,
  schedule, tasks and the university portal, plus the study-companion features
  on top of them.
- **Sentiment** — the forum sources gather volume and engagement, not feeling.
  GDELT's tone series would be the first real one, but it is off by default:
  Dossier saturates GDELT's per-IP rate limit from this same machine.


---

## 7. Plans and scenarios

The half that makes this a foresight app rather than a dashboard. `plans.py`,
`/api/plans`, and the **Plans** tab.

### A scenario is not a paragraph

It is branches of the future, and **every branch carries dated, falsifiable
indicators**. An indicator names a stored series, a direction, a number and a
date:

```
worldbank.unemployment  above  4.6   by 2028-09-10
fx.per-usd              below  1.36  by 2026-12-10
```

That is the whole vocabulary on purpose. Anything richer would need judgement to
score, and an indicator that needs judgement is not an indicator. "Tensions may
rise" is an opinion; this is a claim.

### The ledger marks them, and no model is consulted

`score()` reads the stored series and decides met / missed by arithmetic. A
scenario written by the `think` tier is marked by exactly the same code as one
written by the rules tier, which is the only way the two can be compared
honestly — and `record()` reports the hit rate per tier, so you can find out
whether the model is beating a straight line.

Two rules stop the ledger flattering itself, and both are tested:

- **A reading older than the forecast cannot test it.** An annual series whose
  next figure has not published yet still holds the reading the projection was
  drawn from. Marking against that would score every forecast correct for free.
  Such an indicator is `unscorable`, not `met`.
- **Accuracy is `None`, not `0`, when nothing has settled.** Nothing having come
  due is not a 0% hit rate, and showing one would be a lie the interface repeats.

### The rules tier writes one too, and it is not a fallback

Ordinary least squares over each stored series, carried forward, stated as a
claim — plus the exact complement, so the two branches cover every outcome and
the ledger always learns something. No model, works with Jan off, and it is the
baseline a cleverer forecast has to beat. Having it in the ledger beside the
model's is how you find out whether the model is worth its minutes.

A slow series is **not** projected to a date it cannot reach: a yearly figure
projected three months out could never be marked, so that claim is never made.

### Choosing how far ahead

By default a rules-tier scenario claims three dates: three months, a year and
two years out (`plans.HORIZONS`, which the backtest also uses). The Plans tab's
second picker can ask for one horizon instead, from `plans.HORIZON_CHOICES`
(two weeks, a month, or one of the usual three), sent as `horizon_days`; the
list is served by `GET /api/plans` as `horizons`, so the page names none
itself. A two-week scenario comes due in two weeks, which is the quickest way
to get the ledger marking something real. Only a daily or weekly series can
make a two-week claim; an annual one is skipped by the rule above, and when
nothing qualifies the refusal says so. A model tier writes its own dates, so
the picker hides itself there and the API answers 400 if one is sent.

The line runs from the **last reading to the claim's date**, not a fixed number
of days past the last reading. With readings a month old, a two-week claim is a
six-week projection; it used to stop a fortnight short of its own date, and the
window and the "series too young" check now use the same reach.

### What a model is allowed to contribute

It is asked for branches and handed the list of series that actually exist. Every
indicator it proposes is forced through the same shape, and one that names a
series this app does not hold, or gives a date in the past, is **discarded** —
as is any branch left with no indicators. Same rule Dossier applies to an
uncited sentence: if it cannot be checked, it does not get stored.

---

## 8. History, and learning from it

The user asked for the app to *"learn and take info from the past year and five
years of news"*.

### Five years in, on the first sweep

- `sweep.sweep_subject()` gives a source it has never stored for this subject
  `days = HISTORY_DAYS` (five years). After that, the usual window.
- `signals/news_events.py` counts items in **Dossier's** five-year Current
  Events archive that link the subject's Wikipedia article or a redirect to
  it, month by month. It is read-only: an empty archive is no series here, not
  a download into Dossier's library. The month in progress is left out, because
  a half-month count reads as a collapse.
- `fx.py` now calls `api.frankfurter.dev/v1`. The old `frankfurter.app` host
  answers every request with a 301.
- `analysis/trend.py` measures a breakout against the last **90** readings
  (`BASELINE`), not the whole series. With five years stored, a median over
  all of it compares today against 2021.

### Get all new info for what is held

A subject swept before this history existed would otherwise keep its short
series forever, because the five-year read only happens for a source the
subject has never stored. The Signals tab button **Get all new info for what is
held** (`POST /api/sweep {"history": true}`) re-reads five years from every
source for every subject that already has signals (`sweep.held_subjects()`;
the watchlist when none has), adds the monthly news counts, then runs
`plans.learn()` for each. **Old readings are kept**: series merge by date, so a
reading older than the window stays exactly as it was.

`start_sweep` marks the sweep running before its thread starts. Without that, a
status read straight after the request answered "idle" and the page stopped
watching a sweep that was under way.

### Stopping a sweep, and one bad subject

**Stop after this subject** (Signals tab, shown only while a sweep runs; `POST
/api/sweep/stop`) lets the subject under way finish, so nothing is left
half-merged, then ends the sweep; everything already read is kept. A subject
that throws is logged as `NAME: failed - Error: message` and the sweep moves on
to the next one. A fetcher that cannot even be built ends the sweep cleanly:
before 2026-10-19 that raised outside the `try`, leaving the sweep marked
running for good, so every later sweep answered 409 until the app restarted.
While a sweep runs, the three buttons that start one are greyed out.

`GET /api/sweep` carries `outcome` (`finished`, `stopped` or `failed`) and
`error` once a sweep ends, and the page picks its message from that: "Sweep
stopped: N of M subjects read, and kept." only when a stop was asked for, and
"Sweep failed ...: reason" in red when the sweep crashed. The line under the
progress bar says the same between sweeps. A sweep this page starts is
reported even when it is over before the first progress read.

### The rules tier learns which claims work

The ledger only learns when a forecast comes due, which is months away. With
years of history held, `plans.backtest()` stands at up to twelve points in the
past per series and horizon, makes the rules tier's projection from **only the
readings before that point**, and marks it against what followed - using the
same "latest reading after the forecast, no later than its date" rule as the
live ledger. Two methods are compared on the same trials:

- `trend` - the straight line `from_rules` draws, fitted over a recent window
  (`_window`: twice the horizon, or six readings' worth for a slow series)
- `persistence` - assume nothing changes

`plans.learn(slug)` keeps the result in `learned/<slug>.json`. `from_rules()`
calls it and then:

- **leaves out** any projection where persistence matched or beat the line on
  at least three trials, and says how many it left out in the scenario's basis;
- **annotates** every claim it does make with how often that claim held in
  backtests, e.g. *"held 9 of 11 times when backtested on this series"*.
- **drops** any projection that carries a count below zero. A source whose
  registry entry sets `non_negative=True` (hn, lemmy, pageviews, news_events,
  fx) cannot fall below nothing, so "hn below -5.74" is never claimed; the
  backtest floors the same line at zero. Count thresholds (`whole_numbers=True`) are
  whole numbers, and one under 1 is not claimed. World Bank series are not flagged
  (inflation and growth can be negative).

Findings carry `age_days` and `stale`: a reading is stale once it is older than
its source's `fresh_days` (7 by default, 45 for monthly news counts, 548 for
annual World Bank figures). The Findings tab greys stale cards, prints
"from 2026-09-11 (28 days ago)" on every card, and offers *Sweep the watchlist
now* (up to 25 subjects, those with stale findings first, through the
normal sweep path); the rules answer to "what is
moving" says when its newest reading is from.

The Plans tab shows **What history taught** beside the ledger, with a *Learn
from history* button (`POST /api/plans/learn`). It is kept apart from the live
hit rate on purpose: a method marked against the past it could have been
tuned on has not been marked against an unseen future, and adding the two
together would flatter the record.
