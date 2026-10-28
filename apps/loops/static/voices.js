// The sound makers Loops plays, one function per voice. instruments.json
// names a voice and its params; a voice takes the audio context, the node
// to play into, the start time, the params and a velocity (0..1) and
// schedules its own nodes. The same code plays live and renders the WAV
// (an OfflineAudioContext is an audio context too).

const noiseBuffers = new WeakMap();

function noise(ctx) {
  let buf = noiseBuffers.get(ctx);
  if (!buf) {
    buf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const data = buf.getChannelData(0);
    let seed = 22222; // fixed, so an export is the same every time
    for (let i = 0; i < data.length; i++) {
      seed = (seed * 16807) % 2147483647;
      data[i] = (seed / 2147483647) * 2 - 1;
    }
    noiseBuffers.set(ctx, buf);
  }
  return buf;
}

function envelope(ctx, out, time, level, decay) {
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.0001, time);
  g.gain.exponentialRampToValueAtTime(Math.max(level, 0.0002), time + 0.003);
  g.gain.exponentialRampToValueAtTime(0.0001, time + decay);
  g.connect(out);
  return g;
}

function noiseSource(ctx, time, length) {
  const src = ctx.createBufferSource();
  src.buffer = noise(ctx);
  src.start(time, 0, length);
  return src;
}

const buses = new WeakMap();

/** Where every voice plays into: a quieter master through a compressor,
 * so a full row of hits does not clip. */
export function bus(ctx) {
  let input = buses.get(ctx);
  if (!input) {
    const squash = ctx.createDynamicsCompressor();
    squash.threshold.value = -10;
    squash.ratio.value = 6;
    squash.connect(ctx.destination);
    input = ctx.createGain();
    input.gain.value = 0.55;
    input.connect(squash);
    buses.set(ctx, input);
  }
  return input;
}

export function midiToHz(note) {
  return 440 * Math.pow(2, (note - 69) / 12);
}

export const VOICES = {
  kick(ctx, out, time, p, vel) {
    const osc = ctx.createOscillator();
    osc.frequency.setValueAtTime(p.start, time);
    osc.frequency.exponentialRampToValueAtTime(p.end, time + p.decay * 0.4);
    osc.connect(envelope(ctx, out, time, vel, p.decay));
    osc.start(time);
    osc.stop(time + p.decay + 0.05);
  },

  snare(ctx, out, time, p, vel) {
    const body = ctx.createOscillator();
    body.type = "triangle";
    body.frequency.setValueAtTime(p.tone, time);
    body.connect(envelope(ctx, out, time, vel * 0.5, p.decay * 0.6));
    body.start(time);
    body.stop(time + p.decay);
    const hiss = noiseSource(ctx, time, p.decay + 0.05);
    const hp = ctx.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.value = 1500;
    hiss.connect(hp);
    hp.connect(envelope(ctx, out, time, vel * 0.7, p.decay));
  },

  noise(ctx, out, time, p, vel) {
    const filter = ctx.createBiquadFilter();
    filter.type = p.filter || "highpass";
    filter.frequency.value = p.freq;
    const bursts = p.bursts || 1;
    for (let b = 0; b < bursts; b++) {
      const at = time + b * 0.012;
      const last = b === bursts - 1;
      const decay = last ? p.decay : 0.01;
      const src = noiseSource(ctx, at, decay + 0.05);
      const g = envelope(ctx, filter, at, vel, decay);
      src.connect(g);
    }
    filter.connect(out);
  },

  tone(ctx, out, time, p, vel) {
    const osc = ctx.createOscillator();
    osc.type = p.wave || "sine";
    const hz = midiToHz(p.note);
    osc.frequency.setValueAtTime(hz * (p.bend ? 1 + p.bend : 1), time);
    if (p.bend) osc.frequency.exponentialRampToValueAtTime(hz, time + 0.06);
    let into = envelope(ctx, out, time, vel * 0.6, p.decay);
    if (p.cutoff) {
      const lp = ctx.createBiquadFilter();
      lp.type = "lowpass";
      lp.frequency.value = p.cutoff;
      lp.connect(into);
      into = lp;
    }
    osc.connect(into);
    osc.start(time);
    osc.stop(time + p.decay + 0.05);
  },
};
