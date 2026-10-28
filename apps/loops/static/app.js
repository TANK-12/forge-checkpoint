// Loops: the grid, live playback with a look-ahead scheduler, patterns
// saved through the backend and WAV export rendered offline in the page.

import { VOICES, bus } from "./voices.js";
import {
  STEP_COUNTS,
  emptyPattern,
  encodeWav,
  foldTail,
  hits,
  loopSeconds,
  nextLevel,
  peak,
  resize,
  stepTimes,
  withAllInstruments,
} from "./loops-logic.js";

const $ = (id) => document.getElementById(id);
const AHEAD = 0.12; // seconds of sound scheduled ahead of the clock
const TAIL = 1.5; // seconds rendered past the end, then folded in
const RATE = 44100;

let instruments = [];
let byId = {};
let pattern = null;
let current = ""; // the name of the pattern last opened or saved
let audio = null;
let playing = null; // {nextStep, nextAt, timer}: what plays next and when

function say(text, bad = false) {
  $("status").textContent = text;
  $("status").classList.toggle("bad", bad);
}

async function api(path, options = {}) {
  const r = await fetch(path, options);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || `${r.status}`);
  return body;
}

function play(ctx, out, time, track, velocity) {
  const inst = byId[track.instrument];
  VOICES[inst.voice](ctx, out, time, inst.params, velocity);
}

/* ---------- grid ---------- */

function drawGrid() {
  const grid = $("grid");
  grid.replaceChildren();
  pattern.tracks.forEach((track, n) => {
    const row = document.createElement("div");
    row.className = "track" + (track.mute ? " muted" : "");
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = byId[track.instrument].label;
    const mute = document.createElement("button");
    mute.className = "btn mute" + (track.mute ? " on" : "");
    mute.textContent = "M";
    mute.title = "Mute";
    mute.onclick = () => {
      track.mute = !track.mute;
      drawGrid();
    };
    const vol = document.createElement("input");
    vol.type = "range";
    vol.min = "0";
    vol.max = "1.5";
    vol.step = "0.05";
    vol.value = String(track.gain);
    vol.title = "Volume";
    vol.oninput = () => (track.gain = Number(vol.value));
    const cells = document.createElement("div");
    cells.className = "cells";
    cells.style.gridTemplateColumns = `repeat(${pattern.steps}, minmax(18px, 1fr))`;
    track.cells.forEach((v, i) => {
      const c = document.createElement("button");
      c.className = "cell" + (i % 4 === 0 ? " beat" : "");
      c.dataset.v = String(v);
      c.dataset.step = String(i);
      c.setAttribute("aria-label", `${label.textContent} step ${i + 1}`);
      c.onclick = () => {
        track.cells[i] = nextLevel(track.cells[i]);
        c.dataset.v = String(track.cells[i]);
        if (track.cells[i] > 0 && !playing) audition(track, track.cells[i]);
      };
      cells.append(c);
    });
    row.append(label, mute, vol, cells);
    grid.append(row);
  });
}

function showStep(step) {
  document.querySelectorAll(".cell.now").forEach((c) => c.classList.remove("now"));
  if (step === null) return;
  document.querySelectorAll(`.cell[data-step="${step}"]`).forEach((c) => c.classList.add("now"));
}

function syncControls() {
  $("bpm").value = String(pattern.bpm);
  $("swing").value = String(pattern.swing);
  $("swing-val").textContent = `${Math.round(pattern.swing * 100)}%`;
  $("steps").value = String(pattern.steps);
  $("name").value = current;
}

/* ---------- playback ---------- */

function context() {
  if (!audio) audio = new AudioContext();
  if (audio.state === "suspended") audio.resume();
  return audio;
}

function audition(track, velocity) {
  const ctx = context();
  play(ctx, bus(ctx), ctx.currentTime + 0.01, track, velocity * track.gain);
}

// Each step is timed from the one before it with the settings of the
// moment, so a change of tempo or swing while playing takes effect from
// the next step instead of moving the whole loop.
function schedule() {
  const ctx = audio;
  const run = playing;
  // after a stall (a hidden tab runs timers about once a second) carry
  // on from now rather than play the missed steps in one burst
  if (run.nextAt < ctx.currentTime - 0.05) run.nextAt = ctx.currentTime;
  while (run.nextAt <= ctx.currentTime + AHEAD) {
    const step = run.nextStep % pattern.steps;
    const at = Math.max(run.nextAt, ctx.currentTime);
    for (const track of pattern.tracks) {
      const v = track.cells[step];
      if (!track.mute && v > 0) play(ctx, bus(ctx), at, track, v * track.gain);
    }
    const delay = Math.max(0, (at - ctx.currentTime) * 1000);
    setTimeout(() => playing === run && showStep(step), delay);
    const times = stepTimes(pattern.steps, pattern.bpm, pattern.swing);
    const end = step + 1 < pattern.steps ? times[step + 1] : loopSeconds(pattern.steps, pattern.bpm);
    run.nextAt = at + end - times[step];
    run.nextStep = step + 1;
  }
}

function start() {
  const ctx = context();
  playing = { nextStep: 0, nextAt: ctx.currentTime + 0.05, timer: 0 };
  schedule();
  playing.timer = setInterval(schedule, 25);
  $("play").textContent = "Stop";
}

function stop() {
  if (playing) clearInterval(playing.timer);
  playing = null;
  showStep(null);
  $("play").textContent = "Play";
}

/* ---------- patterns ---------- */

async function refreshList() {
  const state = await api("/api/state");
  const box = $("patterns");
  box.replaceChildren();
  if (!state.patterns.length) {
    const p = document.createElement("p");
    p.className = "muted small";
    p.textContent = "No saved patterns yet.";
    box.append(p);
  }
  for (const item of state.patterns) {
    const row = document.createElement("div");
    row.className = "row";
    const open = document.createElement("button");
    open.className = "open" + (item.name === current ? " on" : "");
    open.textContent = item.name;
    open.onclick = () => openPattern(item.name);
    const del = document.createElement("button");
    del.className = "del";
    del.textContent = "✕";
    del.title = `Move ${item.name} to the trash`;
    del.setAttribute("aria-label", del.title);
    del.onclick = () => trashPattern(item.name);
    row.append(open, del);
    box.append(row);
  }
}

async function openPattern(name) {
  try {
    const got = await api(`/api/patterns/${encodeURIComponent(name)}`);
    pattern = withAllInstruments(got.pattern, instruments);
    current = name;
    syncControls();
    drawGrid();
    await refreshList();
    const gone = got.dropped.length
      ? ` Left out, no longer an instrument: ${got.dropped.join(", ")}.`
      : "";
    say(`Opened ${name}.${gone}`, !!gone);
  } catch (err) {
    say(`${name} did not open: ${err.message}`, true);
  }
}

async function savePattern() {
  const name = $("name").value.trim();
  if (!name) return say("Give the pattern a name first.", true);
  try {
    await api(`/api/patterns/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(pattern),
    });
    current = name;
    await refreshList();
    say(`Saved ${name}.`);
  } catch (err) {
    say(`Not saved: ${err.message}`, true);
  }
}

async function trashPattern(name) {
  if (!confirm(`Move the pattern ${name} to the trash?`)) return;
  try {
    await api(`/api/patterns/${encodeURIComponent(name)}`, { method: "DELETE" });
    if (current === name) current = "";
    await refreshList();
    say(`${name} is in the trash.`);
  } catch (err) {
    say(`Not moved: ${err.message}`, true);
  }
}

/* ---------- export ---------- */

export async function render(repeats) {
  const loopFrames = Math.round(loopSeconds(pattern.steps, pattern.bpm) * RATE);
  const total = loopFrames * repeats + Math.round(TAIL * RATE);
  const ctx = new OfflineAudioContext(2, total, RATE);
  for (const [time, n, velocity] of hits(pattern, repeats)) {
    play(ctx, bus(ctx), time, pattern.tracks[n], velocity);
  }
  const buf = await ctx.startRendering();
  const span = loopFrames * repeats;
  return [0, 1].map((c) => foldTail(buf.getChannelData(c), span));
}

async function exportWav() {
  const name = $("name").value.trim() || current || "loop";
  const repeats = Number($("repeats").value);
  $("export").disabled = true;
  say("Rendering...");
  try {
    const channels = await render(repeats);
    if (peak(channels) < 1e-4) throw new Error("the loop is silent; switch some steps on");
    const wav = encodeWav(channels, RATE);
    const saved = await api(`/api/export?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wav,
    });
    const preview = $("preview");
    preview.src = URL.createObjectURL(new Blob([wav], { type: "audio/wav" }));
    preview.hidden = false;
    say(`Saved ${saved.saved} to the loops folder.`);
  } catch (err) {
    say(`Not exported: ${err.message}`, true);
  } finally {
    $("export").disabled = false;
  }
}

/* ---------- start ---------- */

async function boot() {
  const state = await api("/api/state");
  instruments = state.instruments;
  byId = Object.fromEntries(instruments.map((i) => [i.id, i]));
  $("out-dir").textContent = state.out_dir;
  for (const n of STEP_COUNTS) $("steps").append(new Option(String(n), String(n)));
  pattern = emptyPattern(instruments);
  // a starting beat, so Play makes a sound straight away
  const set = (id, steps) =>
    steps.forEach((s) => {
      const track = pattern.tracks.find((t) => t.instrument === id);
      if (track) track.cells[s] = 1;
    });
  set("kick", [0, 8, 10]);
  set("snare", [4, 12]);
  set("hat", [0, 2, 4, 6, 8, 10, 12, 14]);
  syncControls();
  drawGrid();
  await refreshList();

  $("play").onclick = () => (playing ? stop() : start());
  $("bpm").onchange = () => {
    const v = Number($("bpm").value);
    if (v >= 40 && v <= 240) pattern.bpm = v;
    else $("bpm").value = String(pattern.bpm);
  };
  $("swing").oninput = () => {
    pattern.swing = Number($("swing").value);
    $("swing-val").textContent = `${Math.round(pattern.swing * 100)}%`;
  };
  $("steps").onchange = () => {
    const was = !!playing;
    stop();
    pattern = resize(pattern, Number($("steps").value));
    drawGrid();
    if (was) start();
  };
  $("clear").onclick = () => {
    pattern.tracks.forEach((t) => t.cells.fill(0));
    drawGrid();
  };
  $("save").onclick = savePattern;
  $("export").onclick = exportWav;
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space" && !e.target.closest("input, select, textarea")) {
      e.preventDefault();
      playing ? stop() : start();
    }
  });
}

boot().catch((err) => say(`Loops did not start: ${err.message}`, true));
