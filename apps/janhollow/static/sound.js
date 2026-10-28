/* Janhollow — the station you can hear.
 *
 * Everything here is synthesised in the browser. No files are downloaded and
 * nothing is installed: a station hum is three detuned oscillators through a
 * low-pass filter, a footstep is a burst of filtered noise, and the music is a
 * slow chord pad that picks its next note from a fixed scale. That choice is
 * not only about disk — it means the ambience follows the game (the reactor
 * deck hums louder, the night is quieter) instead of being a loop that plays
 * regardless.
 *
 * A browser will not let audio start before a gesture, so nothing is created
 * until the first key press or click. Until then this costs nothing at all.
 */
"use strict";

window.Station = (function () {
  const state = {
    ctx: null,
    on: false,
    master: null,
    ambienceGain: null,
    musicGain: null,
    started: false,
    lastStep: 0,
    nextNote: 0,
    noise: null,
    settings: {
      volume: 0.5,
      ambience: 0.5,
      music: 0.35,
      steps: 0.5,
    },
  };

  /* One second of white noise, made once. Footsteps, the door hiss and the
     air handling are all slices of this through different filters. */
  function noiseBuffer(ctx) {
    if (state.noise) return state.noise;
    const buffer = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    state.noise = buffer;
    return buffer;
  }

  function start() {
    if (state.ctx) return state.ctx;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    const ctx = new Ctx();
    state.ctx = ctx;

    state.master = ctx.createGain();
    state.master.gain.value = state.on ? state.settings.volume : 0;
    state.master.connect(ctx.destination);

    state.ambienceGain = ctx.createGain();
    state.ambienceGain.gain.value = state.settings.ambience;
    state.ambienceGain.connect(state.master);

    state.musicGain = ctx.createGain();
    state.musicGain.gain.value = state.settings.music;
    state.musicGain.connect(state.master);

    buildAmbience(ctx);
    state.started = true;
    return ctx;
  }

  /* The room tone: a low drone, a fifth above it, and the hiss of air being
     pushed around. Detuned slightly so the two oscillators beat against each
     other, which is what stops a drone sounding like a test tone. */
  function buildAmbience(ctx) {
    const filter = ctx.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.value = 320;
    filter.connect(state.ambienceGain);

    for (const [freq, detune, gain] of [[55, -7, 0.5], [82.5, 6, 0.28], [110, 11, 0.16]]) {
      const osc = ctx.createOscillator();
      osc.type = "sawtooth";
      osc.frequency.value = freq;
      osc.detune.value = detune;
      const level = ctx.createGain();
      level.gain.value = gain;
      osc.connect(level).connect(filter);
      osc.start();
    }

    const air = ctx.createBufferSource();
    air.buffer = noiseBuffer(ctx);
    air.loop = true;
    const airFilter = ctx.createBiquadFilter();
    airFilter.type = "bandpass";
    airFilter.frequency.value = 480;
    airFilter.Q.value = 0.6;
    const airLevel = ctx.createGain();
    airLevel.gain.value = 0.05;
    air.connect(airFilter).connect(airLevel).connect(state.ambienceGain);
    air.start();

    /* The hum breathes, very slowly. A perfectly steady drone stops being
       heard after a minute; one that moves stays present. */
    const breath = ctx.createOscillator();
    breath.frequency.value = 0.045;
    const depth = ctx.createGain();
    depth.gain.value = 90;
    breath.connect(depth).connect(filter.frequency);
    breath.start();
  }

  function ping(freq, when, length, type, gain) {
    const ctx = state.ctx;
    const osc = ctx.createOscillator();
    osc.type = type || "triangle";
    osc.frequency.value = freq;
    const env = ctx.createGain();
    env.gain.setValueAtTime(0, when);
    env.gain.linearRampToValueAtTime(gain, when + Math.min(0.35, length * 0.35));
    env.gain.exponentialRampToValueAtTime(0.0001, when + length);
    osc.connect(env).connect(state.musicGain);
    osc.start(when);
    osc.stop(when + length + 0.05);
  }

  /* A slow pad in a minor scale. It picks a note, plays it with a long attack
     and lets it ring; two or three overlap at any time. It is deliberately
     sparse — this is a station at night, not a title screen. */
  const SCALE = [110, 130.81, 146.83, 164.81, 196, 220, 261.63, 293.66];

  function music(now) {
    if (!state.ctx || !state.on || state.settings.music <= 0) return;
    if (now < state.nextNote) return;
    const ctx = state.ctx;
    const at = ctx.currentTime + 0.05;
    const root = SCALE[Math.floor(Math.random() * SCALE.length)];
    ping(root, at, 7 + Math.random() * 4, "triangle", 0.09);
    if (Math.random() < 0.6) ping(root * 1.5, at + 0.8, 6, "sine", 0.05);
    if (Math.random() < 0.3) ping(root * 2, at + 1.6, 5, "sine", 0.035);
    state.nextNote = now + 6000 + Math.random() * 7000;
  }

  function step() {
    const ctx = state.ctx;
    if (!ctx || !state.on || state.settings.steps <= 0) return;
    const now = performance.now();
    if (now - state.lastStep < 290) return;
    state.lastStep = now;
    const at = ctx.currentTime;
    const source = ctx.createBufferSource();
    source.buffer = noiseBuffer(ctx);
    const filter = ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.value = 160 + Math.random() * 90;
    filter.Q.value = 1.4;
    const env = ctx.createGain();
    env.gain.setValueAtTime(state.settings.steps * 0.5, at);
    env.gain.exponentialRampToValueAtTime(0.0001, at + 0.11);
    source.connect(filter).connect(env).connect(state.master);
    source.start(at);
    source.stop(at + 0.14);
  }

  function chime(kind) {
    if (!state.ctx || !state.on) return;
    const at = state.ctx.currentTime;
    if (kind === "lift") {
      ping(392, at, 0.5, "sine", 0.16);
      ping(523.25, at + 0.16, 0.6, "sine", 0.13);
    } else if (kind === "talk") {
      ping(659.25, at, 0.22, "sine", 0.08);
    } else if (kind === "door") {
      const source = state.ctx.createBufferSource();
      source.buffer = noiseBuffer(state.ctx);
      const filter = state.ctx.createBiquadFilter();
      filter.type = "highpass";
      filter.frequency.value = 900;
      const env = state.ctx.createGain();
      env.gain.setValueAtTime(0.12, at);
      env.gain.exponentialRampToValueAtTime(0.0001, at + 0.3);
      source.connect(filter).connect(env).connect(state.master);
      source.start(at);
      source.stop(at + 0.34);
    }
  }

  return {
    settings: state.settings,
    get on() {
      return state.on;
    },
    /* Called from the first gesture. Browsers refuse to make noise before one,
       and doing it earlier would just create a suspended context. */
    wake() {
      if (!state.ctx) start();
      if (state.ctx && state.ctx.state === "suspended" && !state.resting) state.ctx.resume();
    },
    toggle() {
      state.on = !state.on;
      this.wake();
      if (state.master) {
        state.master.gain.setTargetAtTime(
          state.on ? state.settings.volume : 0,
          state.ctx.currentTime,
          0.25
        );
      }
      /* Off means silent and idle: once the fade is done the context is
         suspended, so the ambience bed stops being computed at all. */
      clearTimeout(state.quietTimer);
      if (!state.on && state.ctx) {
        state.quietTimer = setTimeout(() => {
          if (!state.on && state.ctx.state === "running") state.ctx.suspend();
        }, 1200);
      }
      return state.on;
    },
    /* Out of sight (hidden tab, or another Forge app in front) the station
       goes quiet and the audio thread rests; back in sight it carries on if
       the sound was on. */
    rest(resting) {
      state.resting = !!resting;
      if (!state.ctx) return;
      if (resting) {
        if (state.ctx.state === "running") state.ctx.suspend();
      } else if (state.on && state.ctx.state === "suspended") {
        state.ctx.resume();
      }
    },
    setVolume(value) {
      state.settings.volume = Math.max(0, Math.min(1, value));
      if (state.master && state.on) {
        state.master.gain.setTargetAtTime(state.settings.volume, state.ctx.currentTime, 0.1);
      }
    },
    /* Called every frame with what the game is doing, so the ambience can
       follow it rather than ignore it. */
    frame(now, scene) {
      if (!state.ctx || !state.on) return;
      music(now);
      if (scene && scene.walking) step();
      if (state.ambienceGain && scene) {
        /* Quieter at night, louder near the reactor. */
        const night = scene.minute != null && (scene.minute < 360 || scene.minute > 1320);
        const want =
          state.settings.ambience * (night ? 0.55 : 1) * (scene.loud ? 1.5 : 1);
        state.ambienceGain.gain.setTargetAtTime(want, state.ctx.currentTime, 1.5);
      }
    },
    chime,
  };
})();
