/* The save file, read before anything is written back.

   If the backend could not be reached while the page opened (restarting or
   busy), the game starts from an empty save. Writing that empty save would
   put zero bests and coins on top of the real ones, so game.js holds every
   write until the real save has been read. Anything ridden in the meantime
   is then laid on top of the real save by mergeSave: the better of the two
   bests, both sets of finished goals, and the coins and runs added up (the
   empty save started from zero, so what it holds was all earned since). */

export const EMPTY_SAVE = Object.freeze({
  best: Object.freeze({ score: 0, distance: 0 }),
  coins: 0,
  done: Object.freeze({}),
  settings: Object.freeze({}),
  runs: 0,
});

const num = (v) => (Number.isFinite(Number(v)) ? Number(v) : 0);
const obj = (v) => (v && typeof v === "object" && !Array.isArray(v) ? v : {});

// The newer day's summary wins; on the same day the bests are the better of
// the two and the runs add up.
function mergeDaily(real, here) {
  if (!here || !here.day) return real;
  if (!real || !real.day || here.day > real.day) return here;
  if (real.day > here.day) return real;
  return {
    day: real.day,
    distance: Math.max(num(real.distance), num(here.distance)),
    score: Math.max(num(real.score), num(here.score)),
    runs: num(real.runs) + num(here.runs),
  };
}

// real: the save the backend sent. here: this page's save, which started from
// EMPTY_SAVE because the read failed. settingsChanged: the player changed a
// setting before the real save arrived, so this page's settings are kept.
export function mergeSave(real, here = EMPTY_SAVE, settingsChanged = false) {
  const r = obj(real), h = obj(here);
  const rb = obj(r.best), hb = obj(h.best);
  const merged = {
    ...r,
    best: {
      ...rb,
      score: Math.max(num(rb.score), num(hb.score)),
      distance: Math.max(num(rb.distance), num(hb.distance)),
    },
    coins: num(r.coins) + num(h.coins),
    done: { ...obj(r.done), ...obj(h.done) },
    settings: settingsChanged ? obj(h.settings) : obj(r.settings),
    runs: num(r.runs) + num(h.runs),
  };
  const daily = mergeDaily(r.daily, h.daily);
  if (daily) merged.daily = daily;
  const mode = h.mode || r.mode;
  if (mode) merged.mode = mode;
  return merged;
}

// The end-of-run title and whether the level-complete chime plays. Until the
// real save has been read, this page's save started empty, so a best or a
// finished level would be measured against nothing: the title says the save
// has not loaded instead of claiming either.
export function overTitle({ saveRead, levelDone, levelName, newBest, dayBest }) {
  if (!saveRead) return { title: "Run over (save not loaded yet)", cheer: false };
  if (levelDone) return { title: `${levelName} complete!`, cheer: true };
  return { title: newBest ? "New best!" : dayBest ? "New best today!" : "Run over", cheer: false };
}
