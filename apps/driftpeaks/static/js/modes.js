/* Ways to ride, in one list. The title screen's mode buttons are built from
   it, `#<link>` in the address starts one straight away, and the game asks the
   mode what a run does instead of checking its name. Adding a mode is one
   entry here.

     scored      points count, and the run ends in a summary
     crashEnds   a crash ends the run (otherwise the rider is put back on
                 the snow a moment later)
     goals       the level goals are counted
     seed(day)   a fixed mountain for the run; without it the run uses the
                 Settings seed, or a new mountain each time
     best(save, day)  the distance in metres the best-run flag marks (0: none)
     summary(save, day)  the line under the buttons on the title screen
     record(save, day, stats)  keeps what the mode remembers about a finished
                 run; true when it was a best */

export const MODES = {
  goals: {
    label: "Goals", link: "ride", scored: true, crashEnds: true, goals: true,
    help: "Three goals per level. A crash ends the run.",
    best: (save) => (save.best && save.best.distance) || 0,
  },
  zen: {
    label: "Zen", link: "zen", scored: false, crashEnds: false, goals: false,
    help: "No score and no end. Fall, and you are back on the snow. Just ride.",
  },
  daily: {
    label: "Today", link: "daily", scored: true, crashEnds: true, goals: false,
    help: "Today's mountain: the same slope all day, a new one tomorrow. A crash ends the run.",
    seed: (day) => daySeed(day),
    best: (save, day) => (save.daily && save.daily.day === day ? save.daily.distance : 0),
    summary(save, day) {
      const d = save.daily && save.daily.day === day ? save.daily : null;
      if (!d || !d.runs) return "No runs on today's mountain yet.";
      const runs = d.runs === 1 ? "1 run" : `${d.runs} runs`;
      return `Best today ${d.distance.toLocaleString()} m · ${d.score.toLocaleString()} points · ${runs}`;
    },
    record: (save, day, stats) => recordDaily(save, day, stats),
  },
};

// Today's date on this computer, as "YYYY-MM-DD".
export function todayKey(d = new Date()) {
  const two = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;
}

// A mountain seed from a day (FNV-1a over the date text), never 0.
export function daySeed(day) {
  let h = 0x811c9dc5;
  for (const ch of String(day)) h = Math.imul(h ^ ch.charCodeAt(0), 0x01000193) >>> 0;
  return h || 1;
}

// Today's best distance and score, and how many runs today; a new day starts
// the count again. True when the distance beat today's best.
export function recordDaily(save, day, stats) {
  const was = save.daily && save.daily.day === day ? save.daily : { day, distance: 0, score: 0, runs: 0 };
  const distance = Math.floor(stats.distance || 0), score = Math.floor(stats.score || 0);
  save.daily = { day, distance: Math.max(was.distance, distance), score: Math.max(was.score, score), runs: was.runs + 1 };
  return distance > was.distance;
}

export function modeFromLink(hash) {
  const link = String(hash || "").replace(/^#/, "");
  const hit = Object.entries(MODES).find(([, m]) => m.link === link);
  return hit ? hit[0] : null;
}

export function flagMetres(mode, save, day) {
  const m = MODES[mode];
  return m && m.best ? Math.max(0, Number(m.best(save, day)) || 0) : 0;
}
