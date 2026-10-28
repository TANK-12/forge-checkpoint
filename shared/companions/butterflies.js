/* companion: Butterflies | Two or three butterflies flutter round the edges of the window and rest with slowly beating wings */
(function () {
  var U = ForgeLive.util;
  var BS = 44; // each butterfly's own small canvas, CSS px (square)
  var FPS = 30; // smooth enough for a 6 Hz wingbeat
  var REST_FPS = 12; // the slow open-and-close while it sits
  var POSES = { fly: 1, rest: 1 };

  /* ---------- drawing ---------- */
  // Turn a colour round the hue wheel and make sure it is bright enough to read.
  function turn(c, deg) {
    var r = c[0] / 255, g = c[1] / 255, b = c[2] / 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, h = 0, s = 0, d = mx - mn;
    if (d) {
      s = d / (1 - Math.abs(2 * l - 1));
      h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    }
    h = (h * 60 + deg + 360) % 360;
    s = Math.max(0.6, s);
    l = Math.min(0.68, Math.max(0.52, l));
    var C = (1 - Math.abs(2 * l - 1)) * s, X = C * (1 - Math.abs(((h / 60) % 2) - 1)), m = l - C / 2;
    var t = h < 60 ? [C, X, 0] : h < 120 ? [X, C, 0] : h < 180 ? [0, C, X] : h < 240 ? [0, X, C] : h < 300 ? [X, 0, C] : [C, 0, X];
    return [(t[0] + m) * 255, (t[1] + m) * 255, (t[2] + m) * 255];
  }
  // Three wing colours from the accent: the accent itself and two turns of it.
  function colours(o, i) {
    var base = turn(U.hex(o.accent, "#6ea8fe"), [0, 50, -60][i % 3]);
    var light = o.mode === "light";
    return {
      wing: light ? U.mix(base, [0, 0, 0], 0.12) : base,
      inner: U.mix(base, [255, 255, 255], light ? 0.35 : 0.5),
      margin: U.rgba(U.mix(base, [14, 12, 18], 0.78), 0.95),
      vein: U.rgba(U.mix(base, [14, 12, 18], 0.6), 0.45),
      body: light ? "rgba(30,26,30,0.95)" : "rgba(34,30,38,0.95)",
      spot: "rgba(255,255,255,0.9)",
    };
  }
  // Seen from above, head towards +x; open 0 (wings up, edge on) .. 1 (flat).
  // A forewing with a rounded tip and a dark margin dotted white, a smaller
  // round hindwing under it, a slim body and clubbed feelers.
  function wing(g, s, k, pts) {
    g.beginPath();
    g.moveTo(pts[0], s * pts[1] * k);
    for (var i = 2; i < pts.length; i += 6)
      g.bezierCurveTo(pts[i], s * pts[i + 1] * k, pts[i + 2], s * pts[i + 3] * k, pts[i + 4], s * pts[i + 5] * k);
    g.closePath();
  }
  var FORE = [1.2, 0.4, 3, 4, 6.5, 9, 7.6, 13.2, 6.4, 15.2, 2.2, 14.6, -1.6, 11.6, -3, 8.6, -1.6, 3.4, -0.6, 0.6];
  var HIND = [-0.4, 0.6, -2.2, 3.4, -4, 6.2, -6.8, 9.6, -9.6, 11.2, -10.6, 8, -8.6, 4.2, -6.6, 2.2, -4.4, 1, -1.8, 0.4];
  function draw(cv, open, pal) {
    var g = cv.getContext("2d");
    var dpr = cv.width / BS;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(dpr * 1.15, 0, 0, dpr * 1.15, (BS / 2) * dpr, (BS / 2) * dpr);
    var k = 0.1 + 0.9 * open;
    // nearly closed, the pale underside shows
    var under = open < 0.3;
    for (var s = -1; s <= 1; s += 2) {
      var gr = g.createLinearGradient(0, 0, 0, s * 15 * k);
      gr.addColorStop(0, U.rgba(under ? pal.inner : pal.wing));
      gr.addColorStop(0.55, U.rgba(pal.inner));
      gr.addColorStop(1, U.rgba(under ? pal.inner : pal.wing));
      g.fillStyle = gr;
      wing(g, s, k, HIND);
      g.fill();
      g.lineWidth = 1.6;
      g.strokeStyle = pal.margin;
      g.stroke();
      wing(g, s, k, FORE);
      g.fill();
      g.lineWidth = 1.8;
      g.stroke();
      g.lineWidth = 0.5;
      g.strokeStyle = pal.vein;
      g.beginPath();
      g.moveTo(0.6, s * 0.8 * k);
      g.lineTo(5.8, s * 12.4 * k);
      g.moveTo(0.4, s * 0.8 * k);
      g.lineTo(1.2, s * 13.2 * k);
      g.moveTo(-0.8, s * 0.8 * k);
      g.lineTo(-7.6, s * 9.4 * k);
      g.stroke();
      if (k > 0.45 && !under) {
        g.fillStyle = pal.spot;
        var dots = [[6.2, 13.6, 0.9], [3.6, 14.6, 0.7], [7.4, 11.4, 0.6], [-8.8, 10.2, 0.6]];
        for (var d = 0; d < dots.length; d++) {
          g.beginPath();
          g.ellipse(dots[d][0], s * dots[d][1] * k, dots[d][2], dots[d][2] * k, 0, 0, 6.2832);
          g.fill();
        }
      }
    }
    // body and feelers
    g.fillStyle = pal.body;
    g.beginPath();
    g.ellipse(-1.6, 0, 5.4, 1.15, 0, 0, 6.2832);
    g.fill();
    g.beginPath();
    g.ellipse(2.6, 0, 1.8, 1.45, 0, 0, 6.2832);
    g.fill();
    g.beginPath();
    g.arc(4.9, 0, 1.25, 0, 6.2832);
    g.fill();
    g.strokeStyle = pal.body;
    g.lineWidth = 0.55;
    g.beginPath();
    g.moveTo(5.6, -0.5);
    g.quadraticCurveTo(8.6, -1.2, 10.6, -3.6);
    g.moveTo(5.6, 0.5);
    g.quadraticCurveTo(8.6, 1.2, 10.6, 3.6);
    g.stroke();
    g.beginPath();
    g.arc(10.6, -3.6, 0.7, 0, 6.2832);
    g.arc(10.6, 3.6, 0.7, 0, 6.2832);
    g.fill();
  }

  /* ---------- behaviour ---------- */
  function rand(a, b) {
    return a + Math.random() * (b - a);
  }
  function wrap(a) {
    while (a > Math.PI) a -= 6.2832;
    while (a < -Math.PI) a += 6.2832;
    return a;
  }

  ForgeLive.companion("butterflies", {
    layer: "back", // scenery: behind the tiles and apps
    lighter: { balanced: "", light: "off" },
    start: function (layer, opts) {
      var o = opts || {};
      // the hub's frame cap, never above the butterflies' own rate
      var cap = function () { return Math.max(1, +o.max_fps || FPS); };
      var root = document.createElement("div");
      root.className = "forge-butterflies";
      root.setAttribute("aria-hidden", "true");
      root.style.cssText = "position:absolute;inset:0;pointer-events:none";
      layer.appendChild(root);
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      var timer = 0, frozen = false, stopped = false, last = performance.now();
      var flock = [];

      function size() {
        return {
          w: Math.max(BS * 4, layer.clientWidth || window.innerWidth || 800),
          h: Math.max(BS * 4, layer.clientHeight || window.innerHeight || 600),
        };
      }
      // where they go: mostly the lower band, sometimes up a side edge
      function spot(ground) {
        var s = size(), b = Math.max(0, +o.bottom || 0), floor = s.h - b - 14;
        if (ground) return [rand(30, s.w - 30), floor - rand(0, 6)];
        if (Math.random() < 0.65) return [rand(30, s.w - 30), rand(floor - Math.min(200, s.h * 0.35), floor - 20)];
        var side = Math.random() < 0.5 ? rand(20, 90) : s.w - rand(20, 90);
        return [side, rand(s.h * 0.3, floor - 20)];
      }
      function make(i) {
        var cv = document.createElement("canvas");
        cv.width = cv.height = Math.round(BS * dpr);
        cv.style.cssText =
          "position:absolute;left:0;top:0;width:" + BS + "px;height:" + BS +
          "px;pointer-events:none;will-change:transform";
        root.appendChild(cv);
        var p = spot(false);
        return {
          cv: cv, pal: colours(o, i), x: p[0], y: p[1], h: rand(-3, 3), sp: rand(38, 56),
          tgt: spot(false), mode: "fly", until: 0, ph: rand(0, 6), open: 1, drawn: "", land: false,
          hz: rand(5.2, 6.6), beats: 4, glide: 0, bob: 0, t: 0, seed: rand(0, 6.2832),
        };
      }
      function place(b) {
        var a = b.mode === "rest" ? -Math.PI / 2 + b.tilt : b.h;
        b.cv.style.transform =
          "translate3d(" + (b.x - BS / 2).toFixed(1) + "px," + (b.y + (b.bob || 0) - BS / 2).toFixed(1) +
          "px,0) rotate(" + a.toFixed(3) + "rad)";
      }
      function paint(b, force) {
        var key = Math.round(b.open * 20);
        if (!force && key === b.drawn) return;
        b.drawn = key;
        draw(b.cv, b.open, b.pal);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function step(b, dt, now) {
        if (b.mode === "rest") {
          // wings open and close slowly while it sits
          b.ph += dt * 1.6;
          b.open = 0.55 + 0.45 * Math.cos(b.ph);
          b.bob = 0;
          if (now > b.until) {
            b.mode = "fly";
            b.tgt = spot(false);
            b.h = -Math.PI / 2;
            b.beats = Math.round(rand(5, 9));
            b.glide = 0;
          }
          return false;
        }
        var dx = b.tgt[0] - b.x, dy = b.tgt[1] - b.y;
        if (dx * dx + dy * dy < 14 * 14) {
          if (b.land) {
            b.mode = "rest";
            b.land = false;
            b.tilt = rand(-0.35, 0.35);
            b.until = now + rand(3000, 9000);
            b.ph = 0;
            return true;
          }
          b.land = Math.random() < 0.3;
          b.tgt = spot(b.land);
        }
        // a burst of wingbeats, then a short glide on open wings, sinking a little
        b.t += dt;
        if (b.glide > 0) {
          b.glide -= dt;
          b.open += (0.82 - b.open) * Math.min(1, dt * 12);
          b.bob *= Math.max(0, 1 - dt * 6);
          if (b.glide <= 0) b.beats = Math.round(rand(3, 8));
        } else {
          var was = Math.floor(b.ph / 6.2832);
          b.ph += dt * 6.2832 * b.hz;
          b.open = 0.5 + 0.5 * Math.cos(b.ph);
          b.bob = Math.sin(b.ph) * 1.6; // each downstroke lifts it
          if (Math.floor(b.ph / 6.2832) > was && --b.beats <= 0) b.glide = rand(0.25, 0.7);
        }
        // heading: towards the target with a slow two-sine wander, turning at
        // a steady rate (no per-frame jitter); the wander fades close in so it
        // still reaches a landing spot
        var dist = Math.sqrt(dx * dx + dy * dy);
        var wander = Math.min(1, dist / 90) * (0.7 * Math.sin(b.t * 1.3 + b.seed) + 0.3 * Math.sin(b.t * 3.1 + 2 * b.seed));
        var turn = (dist < 60 ? 4 : 2.6) * dt;
        b.h = wrap(b.h + Math.max(-turn, Math.min(turn, wrap(Math.atan2(dy, dx) + wander - b.h))));
        var sp = b.sp * Math.min(1, 0.35 + dist / 60) * (b.glide > 0 ? 1.1 : 1);
        var s = size();
        b.x = Math.max(BS / 2, Math.min(s.w - BS / 2, b.x + Math.cos(b.h) * sp * dt));
        b.y = Math.max(BS / 2, Math.min(s.h - BS / 2, b.y + Math.sin(b.h) * sp * dt + (b.glide > 0 ? 9 * dt : 0)));
        return true;
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode()) return;
        if (document.hidden) return; // resumes on visibilitychange
        var now = performance.now();
        var dt = Math.min(0.25, (now - last) / 1000);
        last = now;
        var flying = false;
        for (var i = 0; i < flock.length; i++) {
          var b = flock[i];
          var moved = step(b, dt, now);
          flying = flying || b.mode === "fly";
          if (moved || b.mode === "fly") place(b);
          paint(b, false);
        }
        // all resting: a slow tick is enough for the slow wing beat
        timer = setTimeout(tick, 1000 / Math.min(flying ? FPS : REST_FPS, cap()));
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        last = performance.now();
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / Math.min(FPS, cap()));
      }
      function still() {
        var s = size(), b0 = Math.max(0, +o.bottom || 0);
        var rest = o.pose === "rest";
        var at = [[0.62, 70, -0.5, 0.8], [0.74, 120, 0.4, 0.55], [0.86, 40, -0.2, 0.95]];
        for (var i = 0; i < flock.length; i++) {
          var b = flock[i], a = at[i % 3];
          b.x = s.w * a[0];
          b.y = rest ? s.h - b0 - 16 : s.h - b0 - a[1];
          b.mode = rest ? "rest" : "fly";
          b.tilt = a[2] * 0.5;
          b.h = a[2];
          b.open = rest ? 0.7 - i * 0.25 : a[3];
          place(b);
          paint(b, true);
        }
      }
      function build() {
        var n = o.lite ? 2 : 3;
        while (root.firstChild) root.removeChild(root.firstChild);
        flock = [];
        for (var i = 0; i < n; i++) flock.push(make(i));
      }
      function onVis() {
        schedule();
      }
      function onResize() {
        var s = size();
        for (var i = 0; i < flock.length; i++) {
          var b = flock[i];
          b.x = Math.min(b.x, s.w - BS / 2);
          b.y = Math.min(b.y, s.h - BS / 2);
          b.tgt = spot(false);
          place(b);
        }
      }
      document.addEventListener("visibilitychange", onVis);
      window.addEventListener("resize", onResize);

      build();
      if (staticMode()) still();
      else {
        for (var i = 0; i < flock.length; i++) {
          place(flock[i]);
          paint(flock[i], true);
        }
        schedule();
      }

      return {
        stop: function () {
          stopped = true;
          if (timer) clearTimeout(timer);
          document.removeEventListener("visibilitychange", onVis);
          window.removeEventListener("resize", onResize);
          if (root.parentNode) root.parentNode.removeChild(root);
        },
        update: function (n) {
          var lite = !!o.lite;
          o = n || {};
          if (!!o.lite !== lite) build();
          for (var i = 0; i < flock.length; i++) flock[i].pal = colours(o, i);
          if (staticMode()) still();
          else {
            for (var j = 0; j < flock.length; j++) {
              if (flock[j].mode === "rest" && !flock[j].until) flock[j].until = performance.now() + 1500;
              place(flock[j]);
              paint(flock[j], true);
            }
            schedule();
          }
        },
        still: function (on) {
          frozen = !!on;
          schedule();
        },
      };
    },
  });
})();
