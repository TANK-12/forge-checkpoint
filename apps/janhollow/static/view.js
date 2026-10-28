"use strict";
/* Which deck the screen shows (review JH-I1 and JH-I2, 2026-10-09).
 *
 * Aboard, the view used to be welded to your deck: every poll snapped it back,
 * so the deck buttons did nothing. Now a deck button, Tab or a crew name can
 * look somewhere else ("peeking"), and walking or Back to me ends the look.
 * Pure functions of plain values so node can test them without a page.
 *
 * Each takes { aboard, playerDeck, ... } and returns { deck, peeking }.
 */
const JanView = {
  /* After a poll: a followed crew member wins, then you, then whatever was
     showing. Peeking only means something while you are aboard. */
  afterSnapshot({ current, aboard, playerDeck, peeking, followDeck }) {
    const mine = !!(aboard && playerDeck);
    if (followDeck) return { deck: followDeck, peeking: mine && followDeck !== playerDeck };
    if (mine && !peeking) return { deck: playerDeck, peeking: false };
    return { deck: current, peeking: mine && !!peeking && current !== playerDeck };
  },

  /* A deck button or Tab. Picking your own deck is the same as Back to me. */
  pick({ target, aboard, playerDeck }) {
    const mine = !!(aboard && playerDeck);
    return { deck: target, peeking: mine && target !== playerDeck };
  },

  /* Walking or Back to me. Watching (not aboard) there is nothing to return to. */
  backToMe({ current, aboard, playerDeck }) {
    if (aboard && playerDeck) return { deck: playerDeck, peeking: false };
    return { deck: current, peeking: false };
  },

  /* Who the camera is on: a crew member being found when they are on the
     deck showing (your own deck too), else you on your deck, else nobody
     (null: the camera holds still). me and found are { x, y } (+ deck). */
  cameraOn({ deck, aboard, playerDeck, me, found }) {
    if (found && found.deck === deck) return { x: found.x, y: found.y };
    if (aboard && me && playerDeck === deck) return { x: me.x, y: me.y };
    return null;
  },

  /* The Back to me button: aboard, and looking at a deck or a person that is
     not you. */
  showBack({ aboard, peeking, finding }) {
    return !!(aboard && (peeking || finding));
  },

  /* One axis of the camera: where the deck's edge goes on screen (px). size
     is the deck, view the canvas, unit one tile, cam the tile to centre on.
     pad is how much of the top the play bar covers; with a pad the camera
     centres in what is left below it and lets the hull's top edge sit under
     the bar rather than the person (critic follow-up, 2026-10-09). With no
     pad it is exactly the old render.js formula. */
  axis({ size, view, cam, unit, pad = 0 }) {
    if (size <= view - pad) return pad + (view - pad - size) / 2;
    const want = (view + pad) / 2 - (cam + 0.5) * unit;
    return Math.min(pad, Math.max(view - size, want));
  },

  /* The area the light and atmosphere bakes cover (Relay task 174,
     2026-10-14). The bakes used to be exactly the screen and keyed on the
     camera offset, so a moving camera rebaked several full-screen canvases
     every frame. Now they cover the screen plus a margin, in deck pixels
     (screen x minus ox), with the corner on a whole-tile step. prev is kept
     while it still covers the screen and its scope (deck, canvas size, zoom)
     is the same, so one bake lasts several tiles of camera travel. ox and oy
     are whole pixels and so is the result, which keeps every blit on a whole
     pixel and the picture the same. */
  bakeWindow(prev, { scope, ox, oy, w, h, unit }) {
    if (prev && prev.scope === scope && prev.x <= -ox && prev.y <= -oy &&
        prev.x + prev.w >= w - ox && prev.y + prev.h >= h - oy) return prev;
    const step = Math.max(1, Math.round(unit));
    const mx = Math.max(step, Math.ceil(w * 0.15));
    const my = Math.max(step, Math.ceil(h * 0.15));
    return {
      scope,
      x: Math.floor((-ox - mx) / step) * step,
      y: Math.floor((-oy - my) / step) * step,
      w: w + 2 * mx + step,
      h: h + 2 * my + step,
    };
  },

  /* Tab: the next deck after the one showing. */
  next(decks, current) {
    if (!decks.length) return current;
    const index = decks.findIndex((d) => d.id === current);
    return decks[(index + 1) % decks.length].id;
  },
};

if (typeof module !== "undefined") module.exports = JanView;
