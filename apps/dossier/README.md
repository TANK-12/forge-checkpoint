# Dossier

Builds **sourced, factual portfolios** on public figures and the structures
around them — people, political parties, political systems, countries,
companies, alliances and wars — so that opinions and plans can be formed
afterwards from a base that can be checked.

The design rule behind every decision here: **a model is never the reason a
fact is in a dossier.** Identity comes from Wikidata, timelines come from
Wikidata's dated structure, quotes come from Wikiquote with their citations,
and claims must quote a sentence that is provably in the source text. The local
LLM is used for judgement that genuinely needs it — "is this article about the
right person", "what does this paragraph claim" — and its output is filtered by
ordinary Python before anyone sees it.

Runs at <http://127.0.0.1:8437> inside Forge, or standalone:

```
FORGE_SHARED_DIR=~/Forge/shared \
  .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8437
```

---

## 1. Where things live

| What | Where | Why |
|---|---|---|
| App code | `~/Forge/apps/dossier/` | The working install; `.venv` needs ext4 |
| Research data | `/run/media/<user>/Forge/DossierData/` | Grows forever, and the internal disk is at 95% |
| Portable copy | `/run/media/<user>/Forge/Dossier-app/` | Source beside its data; refresh with `tools/sync_usb.py` |
| Fallback | `~/DossierData-local/` | Used only when the drive is unplugged; the header says so |

`store.data_root()` decides which of the two data roots to use on every call by
actually testing a write, so pulling the drive degrades rather than crashes.

Per subject: `subject.json`, `timeline.json`, `claims.json`, `quotes.json`,
`relations.json`, `sources.json`, `notes.json`, `history.json`, `article.json`
(the whole Wikipedia article by section), and
`text.json.gz` — every extracted article text in **one** compressed bundle, so
a quote stays checkable after the original link dies.

The bundle is not tidiness. exfat allocates a 256 KB cluster per file, so 675
per-source extracts with a median size of 181 bytes turned 3.9 MB of text into
303 MB on disk. One file per subject cut that to 134 MB.

---

## 2. The pipeline

```
  name ──▶ Wikidata identity ──▶ gather ──▶ canonicalise ──▶ score ──▶ cluster
             (Q-number,           (7 source   (one URL per   (0–1 per   (one story
              context terms)       adapters)   document)      document)  per report)
                                                                  │
                        ┌─────────────────────────────────────────┘
                        ▼
             triage the uncertain middle ──▶ extract claims ──▶ corroborate ──▶ merge & save
                    (2B, only 0.28–0.62)        (4B, deep only)   (independent    (never
                                                                   voices)         duplicates)
```

**Identity first.** `sources/wikidata.py` resolves the name to a Q-number and
reads out occupation, party, country and birth year. Those become the *context
terms* the scorer uses, which is what stops a different person with the same
surname contaminating a dossier.

**Relevance is a number, not a filter.** `research/scoring.py` gives every
document a 0–1 score from title hits, mention density, how early the subject
appears, whether they are the actor in their sentences, and how much of their
Wikidata context also appears — then multiplies by source tier and a
*disambiguation* factor that collapses the score when none of the context is
present. Every score carries its own breakdown, so the interface can answer
"why 0.42?". The slider in the UI re-filters a whole dossier live.

**Duplicates collapse twice over.** `research/canonical.py` reduces AMP pages,
tracking parameters and aggregator wrappers to one URL per document.
`research/dedupe.py` then fingerprints the text (SimHash over 5-word shingles,
confirmed by Jaccard) so forty outlets running one wire story become one story
carrying forty outlets.

**Corroboration counts voices, not URLs.** `research/corroborate.py` treats one
story cluster as one reporting act and one domain owner as one voice, so
syndication cannot manufacture confirmation:

| Tier | Rule |
|---|---|
| `verified` | 2+ independent voices, at least one primary/encyclopedic (or 3+ voices) |
| `reported` | 1 independent voice |
| `disputed` | sources conflict — **both sides kept, never resolved** |
| `unsourced` | asserted with nothing behind it — shown greyed, never mixed in |

---

## 3. The three registries

This is the part to preserve. Everything the app *knows about* is discovered
from a package, never listed in code:

- **`sources/`** — one file per place to look. Drop in a module with a `SPEC`
  and it is a source. `entity_types=("*",)` means "any subject", so adding a
  new kind of dossier needs no edits here.
- **`entities/`** — one file per kind of dossier, declaring its pages, the
  Wikidata hints that identify it, and how to build its context terms.
- **`pages/`** — one file per page, returning generic *blocks* (`facts`,
  `timeline`, `claims`, `quotes`, `sources`, `relations`, `prose`, `notes`).
  The frontend draws block kinds and knows nothing about individual pages, so a
  new page needs no frontend work.

`tests/test_registries.py` fails if any of that stops being true.

---

## 4. Jan, and why it is fast enough

Two tiers, both auto-detected from whatever Jan has loaded (`llm.py`):

- **triage — Qwen3.5-2B**: is this document about the right subject? Run only
  on documents scoring in the uncertain band (0.28–0.62); the arithmetic
  already knows about the rest.
- **reason — Qwen3.5-4B**: claim extraction, contradiction detection, briefing
  and answer writing.

**`enable_thinking: false` is mandatory and is set on every call.** Qwen3.5 is a
hybrid reasoning model: left alone it spends the entire token budget narrating
its reasoning and returns an **empty** `content` field. Measured here: 16.8 s
and no answer with thinking on, 0.4 s and `"Yes"` with it off.

With Jan off, the app still gathers, scores, dedupes, and builds timelines and
quotes. Only claim extraction and written prose wait.

---

## 5. How a model is kept honest

Three gates, all plain Python, all tested:

1. **The span gate.** Claim extraction asks for the *first six words* of the
   sentence a claim came from. `_locate_sentence` finds that anchor in the
   article and reads the sentence out of the source. An anchor that is not
   there means the model was working from memory, and the claim is discarded.
   A quotation shown to the user is therefore always the source's own words.
2. **The citation gate.** The briefing and the answer box require a marker
   (`[E3]`, `[4]`) on every sentence. Sentences without one, or citing an item
   that was not supplied, are deleted before display — which is why
   "Not in the sources" is a real answer rather than one the model has to be
   trusted to give.
3. **The notes wall.** `notes.json` is written only by the user's own save.
   No pipeline stage and no model ever touches it.

---

## 6. Bulk research

`research/seeds.py` holds SPARQL recipes that fetch real subject lists from
Wikidata — every current head of government, parties holding seats, live
conflicts, alliances, big companies. Each row arrives with its Q-number
attached and a **prominence** figure (how many language Wikipedias carry the
subject), and the queue works most-covered-first, so a job stopped early has
still done the consequential names rather than an alphabetical slice.

`jobqueue.py` keeps the queue on disk, as **several named queues with one
active at a time**. Workers only pull from the active one. Each queue remembers
across a shutdown whether it is paused and whether it may **redo subjects
already held** — off by default, so a job whose subject is already in the
library is marked `skipped` when it comes up to run rather than researched
twice. That check happens when the job starts, not when it was queued, because
a subject can arrive in the library in between. A deep dive on a subject held
only at quick depth still runs, so deepening is unaffected.

Anything left `running` when the process dies is put back to `queued` on
restart, so a crash costs at most the subjects in flight.

---

## 6a. Connections

`research/graph.py` builds an undirected graph from every subject's
`relations.json`. Two kinds of node:

- **held** — a subject with a dossier, keyed by its slug
- **outside** — something named by a subject's relations that has no dossier
  yet: a university, an ideology, an office

Outside nodes are the point. Two politicians who never mention each other turn
out to have been educated in the same place, and that shared node is the link.
Traversal is undirected — *how are they linked* does not care which of the two
named the other — and shortest paths visit hub nodes last, so a route through a
shared employer beats a route through "social democracy".

**No model is involved at any point, deliberately.** A model asked how two
people are connected will invent a plausible chain, and a plausible chain is
exactly what this app exists not to produce. Every hop is a stored relation
carrying the dossier that recorded it, so a chain can always be checked. Being
model-free is also what lets this run on the CPU while the iGPU is busy.

What becomes an edge is declared in `sources/properties.py`:

```python
RELATIONS = {
    "Party": "member of",
    "Educated at": "educated at",
    "Spouse": "spouse",
    ...
}
```

One line per edge kind, keyed by the same label as the fact table above it.
This used to be four relation kinds named inline in the Wikidata adapter, which
is why the graph was thin — the data for the rest was already in the harvest
and was simply thrown away.

The Connections tab draws a mind map as inline SVG with a spring layout run in
the page (no graph library, the same approach as the world map) and answers
*how are they linked* as a list of hops. A map has its own URL:
`#/links/<subject>`.

### Arcs on the world map

`research/arcs.py` is the same idea projected onto geography: stored relations
become arcs drawn between countries on the World tab. Also model-free, also
CPU-only.

Adding a kind of tie is one entry in `ARC_KINDS`, which declares which entity
type produces it, which relations name the parties and the place, and which of
two shapes it draws. The endpoint names no arc kind and the frontend builds its
filter from whatever the backend reports.

The shape matters, and it is a question of honesty rather than layout.
Wikidata's participant list **does not record which side anyone was on**, so
joining two participants of a war to each other would assert a hostility that
is not in the record. A conflict therefore joins each participant to *where it
was fought*, and a conflict with no recorded location draws nothing at all.
Bloc membership genuinely is symmetric, so that one is drawn between members.

Arcs merge: two wars fought in the same place by the same country are one
thicker line carrying both, and every arc names the dossiers behind it, so
hovering explains it and clicking opens one.

A country the map has no border for - a historical state like the Soviet Union
- is simply not drawn. That is the same documented limitation as the country
shading, not a separate bug. Such places are not lost, though: the *Not on the
map* card under the map lists every held place that matches no map country
(historical states, places too small to draw, and subjects with no recorded
country), and clicking one opens the same panel a country does. When a place
has more subjects than its panel lists, *Look for all N in the library* opens
the library filtered to exactly those subjects (`GET /api/world/place?name=…`,
counted the same way as the map); the *Place* chip above the cards clears it.

---

## 6b. Pictures and speech

**Pictures.** `sources/properties.py` declares which properties are pictures
(`IMAGES`) alongside which are facts. References arrive in the same Wikidata
payload as everything else and cost nothing, so every pass collects them.
`research/images.py` is the separate step that downloads the files, and it is
its own queue phase because that is the part with a real cost — two per kind,
content-type checked so an error page is never saved as a `.jpg`, and never
re-fetched once on disk.

**Speech.** `research/speech.py` reads a dossier aloud, or answers a typed
question and speaks the answer. It shells out to the Piper binary in
**NovelForge's** venv using the voice models already in
`~/NovelMakerData/tts_voices/` — nothing is installed here and there is no
second copy of a 120MB model.

A tour is built straight from the stored timeline and the corroborated claims
with **no model involved at all**, so there is nothing for one to invent. It is
the record read in order. Disputed claims are counted aloud but not read out. A
person's tour leaves out economic indicators; a country's keeps them, because
there they are the story.

A spoken answer goes through `ask.py` first, which has already deleted any
sentence citing nothing. Citation markers are stripped before speaking — `[4]`
is not a sound — but kept in the transcript that comes back with the file. The
rule is that if a sentence is not good enough to appear in writing, it is not
good enough to be spoken, where it is harder to check.

Rendering is a queue phase, not a button that blocks: 3 minutes 41 seconds of
narration takes about 74 seconds of CPU. Recordings are keyed by a hash of the
script, so asking twice for an unchanged dossier costs nothing.

---

## 6c. Indicators, and the two publishers

Two adapters supply dated figures, and both are treated as **primary** sources
because they publish the statistic rather than reporting on someone else's:

- `sources/worldbank.py` - the economic nine: GDP, GDP per person, population,
  unemployment, inflation, inequality, life expectancy, military spending,
  government debt. They appear on the **Economy & society** tab.
- `sources/imf.py` - the World Economic Outlook, and **the only source here
  that reports the future**. Growth, inflation, unemployment, the government
  balance, debt and the current account, with the IMF's own projections stored
  as `kind: "projection"` rather than `kind: "indicator"` and marked as staff
  estimates in their title and detail. The **current year counts as a
  projection**: the year is not over, so the figure has not been observed. The
  summary document a model later reads quotes only observed figures, so a
  forecast cannot be read back as a fact.
- `sources/owid.py` - the social, environmental and democratic nine: life
  expectancy, child mortality, CO2 per person, median age, the human
  development index, the regime classification, life satisfaction, the urban
  share and extreme poverty. They appear on the **Society & development** tab.

Both emit dated timeline entries of kind `indicator`, so neither needed a new
storage shape; the two pages tell them apart with `source_id`. The Economy tab
filters on the kind only, so it shows both.

**OWID serves two shapes of chart, and the difference is not cosmetic.** A line
chart honours `country=~DEU` and returns that country's whole history. A *map*
chart ignores the country filter and returns every country for the latest year
- which is about 5 KB, smaller than a filtered request would have been. The
shape is therefore declared per indicator: `series` is fetched per subject,
`snapshot` is fetched once per process and read out of a cache for every
subject afterwards. Treating a snapshot as a series would download the whole
world once per subject.

Every slug and column in that table was checked against the live endpoint.
Three candidates (`literacy-rate`, `corruption-perception-index`,
`primary-energy-consumption-per-capita`) returned nothing or 404 and were
dropped rather than left in to fail quietly.

Resolving a country name to its ISO3 code lives in `sources/countrycodes.py`
and is shared by both adapters, so a name that resolves for one resolves for
the other.

## 6d. The news watcher

News is gathered per subject when that subject is researched, and the briefing
assembles what is already stored. Nothing polled for new events on its own, so
a library left alone slowly went stale and the briefing quietly described an
older world. `watcher.py` closes that loop from its own **Watch** tab: on a
timer it queues another quick pass over whichever held subjects have gone
longest without one, and the ordinary merge rules fold in whatever is new.

Settings and the sweep history live in `watcher.json` beside the research, so
the schedule survives a restart exactly as the queue does. It is **off by
default**.

The rules that matter are the ones about not trampling the user, and each has a
test:

- It never clears a pause. A pause is a decision, and the point of it surviving
  a restart is that it survives everything.
- It never shoulders past work already queued. If the active queue still has
  jobs waiting or running, the sweep is deferred.
- It never overrides the memory guard.

A deferred sweep is deliberately **not** recorded as having happened, so the
clock does not restart and the refresh is retried rather than skipped.

Sweeps go into their own queue, created with `redo_held=True`: refreshing a
held subject is the entire job, and with redo off every sweep would queue
subjects and then skip all of them.

It shares the half-hourly thread that writes the briefs rather than starting a
second one - deciding whether a sweep is due costs nothing when it is not.

## 6e. Five years of news, and the whole article

The user's complaint: *"it just does timelines, I want more info, and the past
year and five years of news"*. Two things were true. Every news adapter looked
back a few weeks at most, and `wikipedia.py` downloaded the whole article and
kept only its first paragraph.

**The whole article.** `sources/wikipedia.py` now splits the plain-text extract
on its `== Heading ==` markers (reference lists, "See also" and the like are
dropped) and stores it as `article.json` - one living document per subject,
replaced by a fresh copy and never merged. The **In depth** page draws it one
fold per section. Zelenskyy's article is 34 sections.

**The news archive.** `research/news_archive.py` reads Wikipedia's
**Current Events portal**, a daily edited digest of world news in which every
person, country, party and war mentioned is a wiki link, and every item cites
the outlets it came from. Three properties made it the right source:

- **One request per month.** The month page transcludes every day, so five
  years is sixty requests, done once and shared by the whole library at
  `news_archive/YYYY-MM.json`. A month ended more than a week before it was
  fetched is final and never fetched again; the current month is refreshed
  after six hours.
- **Linking is exact.** An item belongs to a subject because it links the
  subject's article, or a redirect to it (`titles_for()` asks for those - the
  portal writes "Zelensky" and "Russian" far more often than the canonical
  title). No surname matching and no model. An item filed under a subject as a
  topic heading ("Russo-Ukrainian War" › "Battle of Kyiv") counts too, and is
  kept first when a subject passes the 1,500-item cap.
- **It is sourced.** Items keep their citations and are filed `kind: "news"`,
  `confidence: "reported"` - an editor's summary of reporting, never
  `verified`.

`sources/news_archive.py` is the adapter (quick and deep phases, every subject
type). The **News** page shows news and Google News headlines newest first,
split into *past year* and *one to five years ago*, with per-year counts and a
filter. Overview's timeline now leaves news out, and a timeline cut at its
limit now keeps the newest entries rather than the oldest. The spoken tour
already filters by kind, so it does not read news aloud; the briefing and the
ask box do see it.

**Get all the new info** (`enrich.py`, Watch tab card, `POST /api/history`)
catches up a library researched before any of this: it downloads missing
months, then for each held subject folds in the matched news and fetches the
article if none is held. **Old data is kept**: news merges on the date-and-title
key and never replaces an item, and a held article is left alone.

Every dossier also has a **Get new info** button beside Update
(`POST /api/subject/{slug}/new-info`). It runs the same pass for that one
subject, outside the queue, with `refresh_articles=True` so the article is a
fresh copy; the page waits on `GET /api/history`, reloads, and says how many
news items were added. Unlike Update it does not re-run every source, so it
takes seconds rather than a research pass. It merges with `dossier.add_events()`, which uses the same keys as
`save()` but skips the per-subject reindex - over a thousand subjects on the
USB drive that reindex is a million file reads - and reindexes once at the end.

## 7. Layout

```
web_app.py          FastAPI. Thin: it names no source, subject type or page.
store.py            Drive-or-fallback resolution, atomic writes, gzip text
dossier.py          Load / merge / save. The accumulate-never-duplicate rules.
jobqueue.py         The persistent work queue
llm.py              Jan client: tier routing, thinking off, one call at a time
ask.py              Per-subject Q&A over stored evidence only
briefing.py         The state-of-the-world assembly
watcher.py          The news watcher: refresh the stalest subjects on a timer
enrich.py           Fill in history: five years of news + articles for the library
janidle.py          Unloads Jan models idle for 5 minutes; Jan reloads on demand
manifest.py         Crash record every 5 minutes, to the data drive and ~/Forge/outputs
research/           canonical, dedupe, scoring, claims, corroborate, fetcher,
                    pipeline, seeds, graph, arcs, images, speech, news_archive
sources/            registry + wikidata, wikipedia, wikiquote, ddg_lite,
                    news_rss, gdelt, sec_edgar, worldbank, owid, imf,
                    news_archive
                    (+ properties.py and countrycodes.py, which are shared
                    tables rather than sources - they carry no SPEC, so the
                    registry walks past them)
entities/           registry + person, party, political_system, country,
                    organisation, alliance, conflict
pages/              registry + common + 22 page types (Everything is the newest)
static/             index.html, app.js, app.css, world-map.json
tools/              build_map.py (regenerate the map), sync_usb.py
tests/              297 tests, no network, no model
```
