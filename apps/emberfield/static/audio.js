/* Emberfield's sound: synthesised from the content store, never sampled.

   There are no audio files anywhere in this project. Every effect is a small
   Web Audio graph built from a dozen numbers in ~/ForgeGameData/sounds/*.json,
   which buys three things that matter here:

     * it costs about four kilobytes instead of megabytes, on a laptop the user
       has asked repeatedly not to fill;
     * it is editable by hand -- a hoe that sounds wrong is a number to nudge,
       not a sample to re-record;
     * and it follows the same rule as everything else in the game: adding a
       sound for a new event is one more file and no code.

   The cost is honest to state: this will never sound like a recorded foley
   library. It sounds like a synthesiser, which suits pixel art better than it
   would suit anything else.

   The synthesis itself lives in shared/forge_sound.js, because Pixel Forge
   edits these recipes and has to hear exactly what the game will play. This
   file is the game's half: which event maps to which recipe, the master
   volume, and the ambience beds whose level the clock steers. Adding a sound
   for a new event is still one more file in the content store.

   Browsers refuse to start audio until the user has interacted with the page,
   so the context is created lazily on the first key or click and everything
   before that is silently dropped rather than queued.
*/
"use strict";

const Sound = (function () {
  let ctx = null;
  let master = null;
  let byEvent = new Map();
  let volume = 0.7;
  let muted = false;
  const beds = new Map();      // event -> { gain, peak } for looping ambience

  /* One buffer of white noise, made once and reused. */
  let noiseBuffer = null;

  function ensure() {
    if (ctx) return ctx.state !== "closed";
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return false;
    ctx = new Ctx();
    master = ctx.createGain();
    master.gain.value = muted ? 0 : volume;
    master.connect(ctx.destination);
    noiseBuffer = ForgeSound.makeNoise(ctx, 1.0);
    return true;
  }

  return {
    /* Sounds come from the content store like everything else. Called once the
       store has loaded; a second call re-reads it, which is what makes editing
       a sound file and reloading enough to hear the change. */
    load(store) {
      byEvent = new Map();
      for (const def of Object.values((store.types && store.types.sounds) || {})) {
        if (def.event) byEvent.set(def.event, def);
      }
      return byEvent.size;
    },

    setVolume(value) {
      volume = Math.max(0, Math.min(1, value));
      if (master) master.gain.value = muted ? 0 : volume;
    },

    setMuted(value) {
      muted = !!value;
      if (master) master.gain.value = muted ? 0 : volume;
    },

    /* Called from the first real keypress or click. Browsers will not let audio
       start before that, and calling it earlier leaves a suspended context that
       never recovers. */
    unlock() {
      if (!ensure()) return false;
      if (ctx.state === "suspended") ctx.resume();
      return true;
    },

    /* Off screen or paused: stop the audio clock, so the ambience bed is not
       mixed for nobody. unlock() starts it again on the next key or click. */
    rest() {
      if (ctx && ctx.state === "running") ctx.suspend();
    },

    play(event, options) {
      const def = byEvent.get(event);
      if (!def || muted) return false;
      if (!ctx || ctx.state !== "running") return false;
      ForgeSound.schedule(ctx, master, noiseBuffer, def, ctx.currentTime,
        (options && options.pitch) || 1);
      return true;
    },

    /* Ambience is a held bed whose level is steered every frame rather than a
       clip that starts and stops, so dusk fades in instead of switching on. */
    ambience(event, level) {
      if (!ctx || ctx.state !== "running") return;
      const def = byEvent.get(event);
      if (!def) return;
      let bed = beds.get(event);
      const wanted = Math.max(0, Math.min(1, level));

      if (!bed) {
        if (wanted <= 0) return;   // do not build a graph for silence
        const source = ctx.createBufferSource();
        source.buffer = noiseBuffer;
        source.loop = true;
        const filter = ctx.createBiquadFilter();
        filter.type = "lowpass";
        filter.frequency.value = Math.max(40, def.filter || 400);
        const gain = ctx.createGain();
        gain.gain.value = 0.0001;
        source.connect(filter);
        filter.connect(gain);
        gain.connect(master);
        source.start();
        bed = { source, gain, peak: def.gain != null ? def.gain : 0.05 };
        beds.set(event, bed);
      }
      const target = Math.max(0.0001, wanted * bed.peak);
      bed.gain.gain.setTargetAtTime(target, ctx.currentTime, 0.6);
    },

    silenceAmbience() {
      for (const bed of beds.values()) {
        if (ctx) bed.gain.gain.setTargetAtTime(0.0001, ctx.currentTime, 0.3);
      }
    },

    /* For the self-test: what the engine believes it can play. */
    events() { return Array.from(byEvent.keys()); },
    ready() { return !!(ctx && ctx.state === "running"); },
    def(event) { return byEvent.get(event) || null; },

    /* Render one sound offline and report its peak amplitude.

       This is how the synthesis gets verified. A headless browser will not play
       audio, and "the code ran without throwing" is not evidence that anything
       audible came out -- a wrong envelope, or a low-pass cutoff below the
       fundamental, produces a perfectly valid, perfectly silent graph.
       Rendering it and measuring the waveform is the only check that means
       anything. Returns a promise of { peak, rms, frames, ... }.
    */
    renderOffline(event) {
      const def = byEvent.get(event);
      if (!def) throw new Error(`no sound for event ${event}`);
      return ForgeSound.renderOffline(def);
    },
  };
})();
