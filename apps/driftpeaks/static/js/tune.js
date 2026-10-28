/* Drift Peaks' own tune: a slow, calm soundtrack made in Web Audio, so the
   game is never silent when the music folder is empty (a fresh install ships
   no tracks). Four soft chords go round, each held for one bar, with a few
   bell notes from the chord's own scale on top. Nothing is recorded; the
   notes come from tuneBar(), which tests can read without a browser. */

const BAR_SECONDS = 6.4;
// A minor, F, C, G: MIDI notes of each chord, low to high
const CHORDS = [
  [45, 57, 60, 64],
  [41, 57, 60, 65],
  [48, 55, 60, 64],
  [43, 55, 59, 62],
];
const BELLS = [69, 72, 74, 76, 79, 81]; // A minor pentatonic, up high

export function midiToHz(n) {
  return 440 * 2 ** ((n - 69) / 12);
}

// Bar n's chord and bell notes ({note, at} with `at` in seconds into the bar).
// A small fixed shuffle so the bells differ bar to bar but repeat every 16.
export function tuneBar(n) {
  const chord = CHORDS[((n % CHORDS.length) + CHORDS.length) % CHORDS.length];
  const bells = [];
  let s = (((n % 16) + 16) % 16) * 7919 + 13;
  for (let i = 0; i < 3; i++) {
    s = (s * 1103515245 + 12345) % 2147483648;
    if (s % 3 === 0) continue; // some beats rest
    bells.push({ note: BELLS[s % BELLS.length], at: 0.8 + i * 1.9 });
  }
  return { chord, bells, seconds: BAR_SECONDS };
}

export function createTune() {
  let ctx = null;
  let out = null;
  let bar = 0;
  let next = 0;
  let timer = 0;
  let level = 0;

  const voice = (hz, start, length, peak, type) => {
    const osc = ctx.createOscillator();
    const amp = ctx.createGain();
    osc.type = type;
    osc.frequency.value = hz;
    amp.gain.setValueAtTime(0, start);
    amp.gain.linearRampToValueAtTime(peak, start + Math.min(1.6, length / 3));
    amp.gain.exponentialRampToValueAtTime(0.0001, start + length);
    osc.connect(amp).connect(out);
    osc.start(start);
    osc.stop(start + length + 0.05);
  };

  const schedule = () => {
    // keep about two bars queued ahead of the clock
    while (next < ctx.currentTime + BAR_SECONDS * 2) {
      const { chord, bells, seconds } = tuneBar(bar++);
      for (const n of chord) voice(midiToHz(n), next, seconds + 1.2, 0.05, "triangle");
      for (const b of bells) voice(midiToHz(b.note), next + b.at, 3.2, 0.035, "sine");
      next += seconds;
    }
  };

  return {
    play() {
      if (!ctx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        ctx = new AC();
        const soft = ctx.createBiquadFilter();
        soft.type = "lowpass";
        soft.frequency.value = 2400;
        out = ctx.createGain();
        out.connect(soft).connect(ctx.destination);
      }
      out.gain.value = level;
      ctx.resume().catch(() => {});
      if (!timer) {
        next = Math.max(next, ctx.currentTime + 0.1);
        schedule();
        timer = setInterval(schedule, 1000);
      }
    },
    pause() {
      clearInterval(timer);
      timer = 0;
      if (ctx) ctx.suspend().catch(() => {});
    },
    setVolume(v) {
      level = Math.max(0, Math.min(1, v));
      if (out) out.gain.value = level;
    },
    get playing() {
      return !!timer;
    },
  };
}
