/* The Forge sound engine: small Web Audio graphs built from a recipe.
 *
 * The companion to forge_art.js. That module turns palette-indexed character
 * rows into pixels; this one turns a dozen numbers into a noise. Both read the
 * same kind of thing -- plain JSON owned by no single app -- and both are
 * shared because more than one app needs them: Emberfield plays these sounds,
 * PixelForge edits them, and a second game would do both.
 *
 * A recipe is the `sounds` content type in ~/ForgeGameData:
 *
 *   { "wave": "noise", "duration": 0.22, "gain": 0.34,
 *     "filter": 1400, "filter_to": 240 }
 *
 * There are no audio files anywhere in Forge. That is a deliberate trade: a
 * folder of .wav files would sound better, but it would be megabytes on a
 * laptop short on disk, un-editable without an audio editor, and impossible to
 * tune by hand. A dozen numbers can be nudged until a hoe stroke sounds right.
 *
 * Every function here takes its AudioContext as an argument rather than
 * closing over a live one, so exactly the same graph can be rendered into an
 * OfflineAudioContext. That is what makes the synthesis testable and what lets
 * an editor draw a waveform without playing it: a headless browser cannot play
 * a sound, but it can render one and measure it -- and a wrong envelope or a
 * filter cutoff below the fundamental produces a perfectly valid, perfectly
 * silent graph that throws nothing at all.
 */
"use strict";

const ForgeSound = (function () {
  /* One second of white noise. Made once per context and reused -- generating
     it per shot would allocate a second of samples on every hoe stroke. */
  function makeNoise(actx, seconds = 1.0) {
    const frames = Math.floor(actx.sampleRate * seconds);
    const buffer = actx.createBuffer(1, frames, actx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < frames; i++) data[i] = Math.random() * 2 - 1;
    return buffer;
  }

  /* Build one voice -- an oscillator or a slice of the noise buffer, through an
     optional low-pass, through its own envelope. */
  function voice(actx, dest, noise, def, when, detuneCents) {
    const duration = Math.max(0.02, def.duration || 0.18);
    const gainNode = actx.createGain();

    let source;
    if (def.wave === "noise") {
      source = actx.createBufferSource();
      source.buffer = noise;
      source.loop = true;
    } else {
      source = actx.createOscillator();
      source.type = def.wave || "triangle";
      const freq = Math.max(20, def.freq || 440);
      source.frequency.setValueAtTime(freq, when);
      if (def.freq_to) {
        /* Exponential rather than linear: pitch is heard logarithmically, so a
           linear glide from 300Hz to 60Hz spends most of its time sounding like
           it has already arrived. */
        source.frequency.exponentialRampToValueAtTime(
          Math.max(20, def.freq_to), when + duration);
      }
      if (detuneCents) source.detune.setValueAtTime(detuneCents, when);
    }

    if (def.filter) {
      const filter = actx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.setValueAtTime(Math.max(40, def.filter), when);
      if (def.filter_to) {
        filter.frequency.exponentialRampToValueAtTime(
          Math.max(40, def.filter_to), when + duration);
      }
      source.connect(filter);
      filter.connect(gainNode);
    } else {
      source.connect(gainNode);
    }

    const peak = Math.max(0.0001, def.gain != null ? def.gain : 0.3);
    const attack = Math.min(Math.max(0.001, def.attack || 0.005), duration * 0.9);
    gainNode.gain.setValueAtTime(0.0001, when);
    gainNode.gain.linearRampToValueAtTime(peak, when + attack);
    gainNode.gain.exponentialRampToValueAtTime(0.0001, when + duration);
    gainNode.connect(dest);

    source.start(when);
    source.stop(when + duration + 0.02);
    return { source, gain: gainNode, ends: when + duration };
  }

  /* How long the whole recipe runs, repeats included. */
  function totalDuration(def) {
    const duration = Math.max(0.02, def.duration || 0.18);
    const repeat = Math.max(1, def.repeat || 1);
    const gap = def.repeat_gap || duration * 0.9;
    return duration + gap * (repeat - 1);
  }

  /* Schedule a whole recipe -- its repeats, and the optional second voice a few
     cents away that gives a thin oscillator some body. One oscillator reads as
     a beep; two read as a sound. */
  function schedule(actx, dest, noise, def, when, pitch) {
    const repeat = Math.max(1, def.repeat || 1);
    const gap = def.repeat_gap || (def.duration || 0.18) * 0.9;
    const shaped = !pitch || pitch === 1 ? def : Object.assign({}, def, {
      freq: (def.freq || 440) * pitch,
      freq_to: def.freq_to ? def.freq_to * pitch : 0,
    });
    for (let i = 0; i < repeat; i++) {
      const at = when + i * gap;
      voice(actx, dest, noise, shaped, at, 0);
      if (def.detune) voice(actx, dest, noise, shaped, at, def.detune);
    }
    return when + totalDuration(def);
  }

  /* Render a recipe offline and measure it. Returns
     { peak, rms, frames, sampleRate, samples } -- `samples` is the raw
     Float32Array, which is what lets an editor draw the waveform. */
  async function renderOffline(def, rate = 44100) {
    const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Offline) throw new Error("no OfflineAudioContext in this browser");
    const total = totalDuration(def) + 0.05;
    const actx = new Offline(1, Math.ceil(rate * total), rate);
    const noise = makeNoise(actx, 1.0);
    schedule(actx, actx.destination, noise, def, 0, 1);
    const rendered = await actx.startRendering();
    const out = rendered.getChannelData(0);
    let peak = 0, sum = 0;
    for (let i = 0; i < out.length; i++) {
      const v = Math.abs(out[i]);
      if (v > peak) peak = v;
      sum += out[i] * out[i];
    }
    return {
      peak,
      rms: Math.sqrt(sum / out.length),
      frames: out.length,
      sampleRate: rate,
      samples: out,
    };
  }

  /* The fields a recipe understands, with their defaults and what they do.
     Editors read this rather than hardcoding a form, so a new field is one
     entry here plus one in forge_content.TYPES["sounds"]. */
  const FIELDS = [
    { key: "wave", label: "waveform", kind: "choice", def: "triangle",
      choices: ["sine", "square", "sawtooth", "triangle", "noise"],
      help: "noise ignores the pitch fields entirely" },
    { key: "freq", label: "pitch", kind: "number", def: 440, min: 20, max: 6000, step: 10,
      help: "Hz at the start. Ignored by noise." },
    { key: "freq_to", label: "glide to", kind: "number", def: 0, min: 0, max: 6000, step: 10,
      help: "0 holds the pitch. Glides are exponential, because pitch is heard that way." },
    { key: "duration", label: "length", kind: "number", def: 0.18, min: 0.02, max: 3, step: 0.01,
      help: "seconds" },
    { key: "attack", label: "attack", kind: "number", def: 0.005, min: 0.001, max: 1, step: 0.005,
      help: "seconds to reach full level. Long attacks make a pad; short ones a hit." },
    { key: "gain", label: "level", kind: "number", def: 0.3, min: 0, max: 1, step: 0.02 },
    { key: "filter", label: "low-pass", kind: "number", def: 0, min: 0, max: 12000, step: 100,
      help: "0 means no filter" },
    { key: "filter_to", label: "sweep to", kind: "number", def: 0, min: 0, max: 12000, step: 100,
      help: "sweeps the cutoff across the sound's length" },
    { key: "detune", label: "detune", kind: "number", def: 0, min: -1400, max: 1400, step: 50,
      help: "cents for a doubled second voice. One oscillator is a beep; two are a sound." },
    { key: "repeat", label: "repeats", kind: "number", def: 1, min: 1, max: 8, step: 1 },
    { key: "repeat_gap", label: "repeat gap", kind: "number", def: 0, min: 0, max: 1, step: 0.01,
      help: "seconds between repeats; 0 uses 90% of the length" },
    { key: "loop", label: "ambience bed", kind: "bool", def: false,
      help: "a held bed a game steers the level of, not a one-shot effect" },
  ];

  return { makeNoise, voice, schedule, totalDuration, renderOffline, FIELDS };
})();
