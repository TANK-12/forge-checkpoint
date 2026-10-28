/* Goals: three per level, from data/levels.json. A goal is {type, n, text},
   and `type` names a run statistic below. A level is done when all three of
   its goals have been met, in any runs; the next level opens then. */

export function newStats() {
  return {
    distance: 0, score: 0, flips: 0, jump_flips: 0, combo: 0, grind: 0,
    coins: 0, goats: 0, rocks: 0, chasms: 0, night_distance: 0, storm_distance: 0,
  };
}

export const STAT_TYPES = Object.keys(newStats());

export function goalKey(levelIndex, goalIndex) {
  return `${levelIndex}:${goalIndex}`;
}

// The first level with a goal not yet met, or the last level when all are.
export function currentLevel(levels, done) {
  for (let i = 0; i < levels.length; i++) {
    if (levels[i].goals.some((_, g) => !done[goalKey(i, g)])) return i;
  }
  return Math.max(0, levels.length - 1);
}

// Goals of `level` that this run's stats have just met, not met before.
export function newlyMet(levels, levelIndex, stats, done) {
  const level = levels[levelIndex];
  if (!level) return [];
  const met = [];
  level.goals.forEach((goal, g) => {
    const key = goalKey(levelIndex, g);
    if (!done[key] && (stats[goal.type] || 0) >= goal.n) met.push(key);
  });
  return met;
}

export function progressText(goal, stats) {
  const v = Math.floor(stats[goal.type] || 0);
  return `${Math.min(v, goal.n).toLocaleString()} / ${goal.n.toLocaleString()}`;
}
