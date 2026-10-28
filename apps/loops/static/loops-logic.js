// The parts of Loops that need no page: timing, patterns and the WAV
// encoder. Kept free of the DOM so node --test runs them (tests/).

export const STEP_COUNTS = [8, 12, 16, 24, 32];
export const MAX_TRACKS = 24; // loops_core.MAX_TRACKS
export const CELL_LEVELS = [0, 1, 0.5]; // a click cycles off, loud, soft

/** Seconds one step lasts: steps are sixteenth notes. */
export function stepSeconds(bpm) {
  return 60 / bpm / 4;
}

export function loopSeconds(steps, bpm) {
  return steps * stepSeconds(bpm);
}

/** When each step starts inside one loop; swing delays every off step. */
export function stepTimes(steps, bpm, swing = 0) {
  const len = stepSeconds(bpm);
  return Array.from({ length: steps }, (_, i) => i * len + (i % 2 ? swing * len : 0));
}

export function nextLevel(value) {
  const at = CELL_LEVELS.findIndex((v) => Math.abs(v - value) < 1e-6);
  return CELL_LEVELS[(at + 1) % CELL_LEVELS.length];
}

/** A pattern the page starts from: every instrument, nothing playing. */
export function emptyPattern(instruments, steps = 16, bpm = 110) {
  return {
    bpm,
    swing: 0,
    steps,
    tracks: instruments.slice(0, MAX_TRACKS).map((i) => ({
      instrument: i.id,
      gain: 0.8,
      mute: false,
      cells: new Array(steps).fill(0),
    })),
  };
}

/** The same pattern with a new step count; it repeats to grow and cuts to shrink. */
export function resize(pattern, steps) {
  return {
    ...pattern,
    steps,
    tracks: pattern.tracks.map((t) => ({
      ...t,
      cells: Array.from({ length: steps }, (_, i) => t.cells[i % t.cells.length] || 0),
    })),
  };
}

/** Every hit in `repeats` loops as [seconds, track index, velocity]. */
export function hits(pattern, repeats = 1) {
  const times = stepTimes(pattern.steps, pattern.bpm, pattern.swing);
  const loop = loopSeconds(pattern.steps, pattern.bpm);
  const out = [];
  for (let r = 0; r < repeats; r++) {
    pattern.tracks.forEach((t, n) => {
      if (t.mute) return;
      t.cells.forEach((v, i) => {
        if (v > 0) out.push([r * loop + times[i], n, v * t.gain]);
      });
    });
  }
  return out.sort((a, b) => a[0] - b[0]);
}

/** 16-bit PCM WAV bytes from one Float32Array per channel. */
export function encodeWav(channels, sampleRate) {
  const frames = channels[0].length;
  const block = channels.length * 2;
  const buf = new ArrayBuffer(44 + frames * block);
  const v = new DataView(buf);
  const text = (at, s) => [...s].forEach((c, i) => v.setUint8(at + i, c.charCodeAt(0)));
  text(0, "RIFF");
  v.setUint32(4, 36 + frames * block, true);
  text(8, "WAVE");
  text(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, channels.length, true);
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * block, true);
  v.setUint16(32, block, true);
  v.setUint16(34, 16, true);
  text(36, "data");
  v.setUint32(40, frames * block, true);
  let at = 44;
  for (let f = 0; f < frames; f++) {
    for (const ch of channels) {
      const s = Math.max(-1, Math.min(1, ch[f]));
      v.setInt16(at, s < 0 ? s * 0x8000 : s * 0x7fff, true);
      at += 2;
    }
  }
  return buf;
}

/** The loudest sample, to tell a silent render from a real one. */
export function peak(channels) {
  let top = 0;
  for (const ch of channels) for (const s of ch) top = Math.max(top, Math.abs(s));
  return top;
}

/** A render of N loops plus a tail, folded so the tail rings into the
 * start: the result is exactly N loops long and repeats without a gap. */
export function foldTail(channel, loopFrames) {
  const out = channel.slice(0, loopFrames);
  for (let i = loopFrames; i < channel.length; i++) out[i % loopFrames] += channel[i];
  return out;
}

/** An opened pattern plus an empty row for each instrument it lacks
 * (added to the registry since it was saved), in registry order. */
export function withAllInstruments(pattern, instruments) {
  const have = new Set(pattern.tracks.map((t) => t.instrument));
  const extra = instruments
    .filter((i) => !have.has(i.id))
    .slice(0, Math.max(0, MAX_TRACKS - pattern.tracks.length))
    .map((i) => ({ instrument: i.id, gain: 0.8, mute: false, cells: new Array(pattern.steps).fill(0) }));
  return { ...pattern, tracks: [...pattern.tracks, ...extra] };
}
