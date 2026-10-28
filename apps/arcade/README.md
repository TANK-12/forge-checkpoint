# Arcade — "Phosphor"

Fourteen small modules — nine games, five experiments — in one cabinet, served as
a Forge tab on port 8433. Everything visual and playable is in
`static/index.html`; the Python backend exists only for the two things a browser
cannot do alone.

Also published as a claude.ai Artifact from this exact file, so the same page
runs with or without a backend.

Press **F** (or the **Full** button in the top bar) for real fullscreen. Any
non-menu screen also asks the Forge hub to hide its sidebar via
`postMessage({forge:"chrome",hidden:true})` — the mechanism `hub/index.html`
already honours — and hands it back on the menu.

## The games

| game | verb | notes |
|---|---|---|
| **Standing Wave** | steer & survive | The play field is a live cymatics simulation driven by the FFT of your MP3. Bright antinodes drain you; ride the dark nodal lines. **Needs a track.** |
| **Aphelion** | aim & release | Gravity slingshot. Drag to aim — the predicted trajectory is computed with the same integrator the probe uses, and turns cyan when the shot will reach the beacon. |
| **Zero Beat** | tune | Match a target waveform harmonic by harmonic. The monitor tone detunes with your error, so a match is an audible unison — the actual "zero beat". |
| **Hearsay** | question | Five crew, one wiped log. NPCs remember what they told you, what you told them, and gossip spreads between them. **Uses Jan.** |
| **Escapement** | swing | One button. Hold to catch the ring above, let go at the top of the arc. The rope only pulls, never pushes — it is a real pendulum constraint, not a spring. Only grabs rings ahead of you, so a catch never reverses the swing. |
| **Catenary** | swing, fairly | Escapement's sibling, built on one promise: **no course is ever impossible**. Rings are never further apart than `REACH`, and holding the rope reels it to `MINROPE`, so `MINROPE + REACH = 358 < 360 = GRAB` — the next ring is always inside the grab radius and the rope hands itself forward while you hold. Buffered grab, a drawn reach circle, three ropes instead of one life. |
| **Waveguide** | rotate | Only the angles are wrong. Rotate the amber mirrors until the beam lights every receiver. Splitters fork the beam and walls absorb it — both are bolted down. Later boards feed two or three receivers from one source. |
| **Downbeat** | jump | One-button rhythm runner. The whole track is analysed up front (onset detection on a kick-band envelope; demo tone falls back to a fixed grid) and a spike is placed at `beatTime × SPEED`. The runner's position is driven straight off the audio clock, so a spike is under you exactly when its beat plays — you jump *on* the music, not after it. Hold through a run. **Needs a track.** |
| **Lanternfall** | drift & flare | Your light is your life and it burns down; sparks feed it. Shadow wisps hunt you and shy from a bright lantern, so a dim one is hunted. A flare (click/space) spends light to stun wisps in reach, and stunned wisps break into sparks. Combo up to x9. |

## The experiments

Nothing to win. Each opens with a console of sliders and keeps running.

| experiment | what it is |
|---|---|
| **Physarum** | Slime-mould transport networks. Thousands of agents each sense the trail ahead-left / ahead / ahead-right and steer toward the strongest, then deposit. Drag to lay food. Sensor angle and reach decide whether you get veins, spirals or lace. Deposit rate rides the bass when a track is loaded. |
| **Gray–Scott** | Reaction–diffusion. Two reagents, one rule, and coral grows. Feed and kill are the whole system — a thousandth either way changes the species. Paint with the pointer; the preset button walks the classic parameter set. |
| **Divergence** | An ensemble of double pendulums released a millionth of a radian apart. They agree for about ten seconds and then never again. The readout tracks the spread as it blows up. Count reaches 1200, the nudge 1e-14, gravity 90. Drawn as a ribbon joining neighbouring members, each segment faded by its own length — a decohered ensemble drawn as dots is grey mush, and the mush was a drawing problem, not a physics one. |
| **Filament** | Divergence with the lid off. The same real physics — a planar chain of 2–4 links solved as a mass matrix and integrated with RK4 — but the ensemble's starting curve, the colour meaning, the trail and a kaleidoscope mirror are all controls. Drawn as the *curve* it is rather than as loose dots, with each segment faded by its own length, which is what keeps full chaos legible instead of grey. |
| **Waterfall** | Your track as a scrolling spectrogram — time down, frequency across, loudness as brightness — with a live waveform scope above it. Log frequency by default, which is what music actually looks like. Scrolls through a scratch canvas (drawing a canvas onto itself with `globalCompositeOperation: "copy"` renders blank in Chromium — that was the "doesn't work" bug). **Needs a track.** |

## Why there is a backend

1. **Jan.** The LLM server is a different origin, so the page cannot call it
   directly. `POST /api/jan/chat` proxies to `JAN_BASE_URL`
   (default `http://127.0.0.1:1337/v1`) and auto-detects whichever model Jan
   currently has loaded — hardcoding a model id breaks the moment you swap one.
2. **Memory.** Hearsay's NPC state is persisted to `~/ForgeArcadeData/` so a
   reload does not wipe the case.

`GET /api/status` reports `{backend, jan, model}`. The page calls it once on
load; if it 404s (Artifact) or reports `jan:false` (Jan not running), Hearsay
falls back to a built-in template brain and stays fully playable.

## The rule that keeps Hearsay coherent

**The engine decides what an NPC says. Jan only decides how they say it.**

The case — culprit, motive, true locations, who saw whom, the one keystone
observation that breaks the cover story — is generated deterministically in
JavaScript. When you ask a question, the engine computes the *content* of the
answer and passes it to Jan as "convey exactly this, in your own voice." The
notebook logs the engine's version, never the model's.

This is why a small local model cannot corrupt the mystery: it can ramble,
mis-punctuate or go off-tone, and the case logic is untouched. It also means
the game is winnable with Jan switched off.

Each NPC's prompt carries their prior claims and what others have told them, so
they stay consistent across a conversation — that is the "memory" you can feel.

## Files

```
web_app.py          FastAPI: /api/status, /api/jan/chat, /api/hearsay/save
static/index.html   the whole cabinet — shell + nine games + five experiments, no libraries
tools/smoke.js      every module driven headlessly; reads its list off the GAMES registry
tools/catenary_sweep.js   proves no Catenary course can be impossible
tools/filament_energy.js  proves the chain obeys mechanics (energy drift, 2-4 links)
tools/wg_sweep.js   Waveguide solvability
tests/console_registry.test.mjs  node --test: console knob rounding, registry units
forge_app.json      port 8433, order 6
.venv/              fastapi + uvicorn + httpx
```

User data: `~/ForgeArcadeData/hearsay_save.json`. Nothing is written into this
folder.

## Running it standalone

```bash
cd ~/Forge/apps/arcade
FORGE_SHARED_DIR=~/Forge/shared .venv/bin/python -m uvicorn web_app:app --host 127.0.0.1 --port 8433
```

Then open <http://127.0.0.1:8433>. Jan must be running on port 1337 for
Hearsay's dialogue to come from the model rather than the fallback.

## Notes for the next session

- No libraries anywhere. Canvas 2D + Web Audio only, so there is nothing to
  keep pinned or updated.
- All fourteen modules share one `<canvas>`, one virtual coordinate space
  (1280×800, letterboxed) and one particle/text FX module. A module is an object
  with `begin / frame / pointer / key / hud / onEnter / onExit`; the shell owns
  the menu, intro, pause and game-over panels.
- **Phase gates everything.** `setPhase(p)` is the one place that shows/hides
  screens, hides `#gameUI` unless `p==="play"`, arms a one-shot repaint
  (`needsPaint`) so a paused module stops churning the canvas, drives
  `AUDIO.resume()/suspend()`, and posts the sidebar-hide message. `AUDIO.suspend()`
  pauses the `<audio>` element **and** `ac.suspend()`, which freezes the demo
  generator, the Zero Beat tone, the ambient beds and the analyser in one call —
  that is what stops a game running in the background of another. Sound plays
  only in the play phase.
- **Music.** The imported/demo track (`AUDIO`) belongs to the *music games* —
  the ones with `needsAudio` / `likesAudio`, plus Zero Beat. Every other game
  names a generated ambient bed with a `music:"<style>"` registry field;
  `enterGame` starts it, `openMenu` stops it, and while a bed is playing the
  `bedActive` flag holds the imported track back so it stays scoped to the music
  games. Bed builders live in the `BEDS` object — one entry, no other wiring.
  All Web Audio, nothing downloaded.
- `S.makePanel(mods, footer)` builds the instrument console (a rack of labelled
  sliders plus readouts and toggle buttons) and returns a live `v` object the
  module reads each frame. All five experiments use it (Zero Beat has its own
  rack) — adding a knob is one entry in an array, no event wiring. A knob whose
  `fmt` shows a plain number (optionally with an `x` prefix or a `°`/`x` suffix)
  gets a typeable number field beside its slider; one whose `fmt` shows a word
  or `1e-8` keeps a read-only readout. Code that moves a knob (a preset) calls
  `panel.knob(key, value)` so the slider and field follow; writing `v[key]`
  directly still works but leaves the slider where it was. A typed value may be
  finer than the slider's step, except on a knob whose step is a whole number
  (STEPS, COUNT, MIRROR...), which only takes whole numbers so the field, the
  slider and the model always agree. `tests/console_registry.test.mjs` checks this.
- Each game card shows the best score saved for it (`phosphor.<id>.best`) with
  the unit from the game's `unit:"m"` registry field, and nothing when there is
  none. The game-over panel reads the same field, so the card and the panel can
  never disagree, and a best saved before units existed still shows its unit.
  `tests/console_registry.test.mjs` fails if a module's `S.gameOver` unit and
  its registry `unit` drift apart. Enter or Space starts from the intro, Retry takes
  the focus a moment after game over, Resume takes it on pause, and the menu
  hands the focus back to the card you left. Focus is only moved when the page
  already has the keyboard, so Arcade never pulls it from another Forge app.
- A registry entry with `kind:"experiment"` lands in the second menu section,
  gets an "Open" button instead of "Begin", a Reset in the top bar, and no
  best-score tracking. Everything else defaults to a game.
- Hearsay and the experiments build DOM into `#gameUI`; the rest are pure canvas.
- Canvas modules use **virtual** coords (1280×800) for `FX.*` calls and
  **screen** coords (`S.px/py/pd`) for `glow()` and raw `ctx` draws. Mixing them
  up is the usual new-module bug.

### Fairness is a property you can test, not a feeling

Catenary exists because the user said Escapement is "every so often
impossible", and it is: `tools/catenary_sweep.js` measures **26% of
Escapement's consecutive ring pairs are further apart than its own 300px grab
radius**. A run lost that way was lost when the course was drawn.

Catenary answers it with arithmetic rather than tuning. Read the comment block
at the top of the module — the three constants are a bound:

```
MINROPE + REACH  =  70 + 288  =  358   <   360 = GRAB
```

Rings are never further apart than `REACH`; holding reels the rope down to
`MINROPE`; so the next ring is *always* inside the grab radius and `transfer()`
can hand the rope forward. **If you change any of those three numbers, run the
sweep** — it checks the inequality directly, and it also flies a
press-once-and-never-let-go player over 200 courses to confirm it never dies
and is never stranded for more than a few seconds.

Two bugs the sweep found that no amount of playing would have surfaced quickly:
a bob that comes to rest exactly under a ring with the rope fully reeled in
used to sit there forever (fixed by the swing pump), and before rope transfer a
no-look player lost 85 ropes over 200 runs where it now loses about two.

### Filament's physics is checked, not assumed

`tools/filament_energy.js` runs the chain undamped and watches total energy.
Drift over 20 simulated seconds is 0.0000% at two and three links and 0.0063%
at four. That check matters more than it looks: a wrong sign or a bad mass
matrix still produces something that swings convincingly on screen while
quietly gaining or bleeding energy, and "the physics is real" is the whole
claim the experiment rests on.

The user's actual complaint about Divergence was that it "doesn't look as cool
when it gets realistically chaotic" but that they did not want the realistic
outcomes removed. Nothing about the simulation changed. What changed is that
the ensemble is drawn as the **curve** it is — a material line being stretched
and folded — with each segment faded by its own length, so the ribbon survives
where the line is still a line and dissolves where chaos has genuinely torn it.

### Waveguide's level generator has a real invariant

Levels are built by construction, then **verified by tracing the intended
solution** before being accepted, and decoys *and walls* are placed only after
that trace, never on a cell the beam actually visits. Both steps are
load-bearing:

- Construction alone is not sufficient — a later turn-mirror can land on a cell
  an *earlier* segment already crossed, so the beam deflects on the first pass
  and the constructed path is not the real path.
- A decoy on the true beam re-routes it at **both** of its rotations, so no
  amount of rotating the other mirrors recovers. Placing decoys against the
  constructed path rather than the traced one reintroduces this.

**Splitters and walls are fixed scenery — only the amber mirrors rotate.** That
keeps solvability tractable: splitters (which fork the beam via `trace()`'s
stack) are dropped on straight pass-through cells of the traced solution, each
running a short corridor to an extra receiver, and the whole board is re-traced
at the intended solution before it ships. If no scramble comes out unsolved, a
fallback sets the path mirrors to their solution and flips exactly one.

Regression check (`tools/wg_sweep.js` — extracts `build`/`trace` and runs
in node): **30,000 boards over levels 1–20, zero unsolvable, zero handed over
already solved.** Splitters appear on ~99.9% of level-5+ boards, walls on every
level-3+ board. Re-run this after touching the generator.

- **Not visually verified.** There is no screenshot capability in the agent
  sandbox and the Chrome extension is not connected, so the layout, feel and
  balance of every module are unconfirmed — Downbeat's jump/gravity constants in
  particular are reasoned, not playtested. Static checks that were run: JS
  syntax, element-id cross-check, registry-target resolution, the Waveguide
  solvability sweep above, a headless smoke test that runs every module for 3000
  frames with random input (`tools/smoke.js`), and backend endpoint
  round-trips.
