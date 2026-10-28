/* companion: Dog | A small dog that trots along the bottom of the window, sniffs, sits, wags, scratches and naps */
(function () {
  var U = ForgeLive.util;
  var S = 1.2; // drawing scale: the dog is about 55 px tall sitting
  var BW = 100, BH = 84; // the dog's own small canvas, CSS px
  var OX = 46, OY = 78; // where the dog's feet are inside it
  var FPS = 12;
  var POSES = { stand: 1, walk: 1, trot: 1, sniff: 1, sit: 1, wag: 1, scratch: 1, lie: 1, sleep: 1 };

  /* ---------- drawing ---------- */
  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    if (o.mode === "light") {
      return {
        fur: [182, 132, 88], far: [150, 106, 70], ear: [112, 74, 48], light: [232, 204, 168],
        line: "rgba(48,32,22,0.92)", collar: U.rgba(U.mix(accent, [0, 0, 0], 0.15)), shade: "rgba(0,0,0,0.16)",
      };
    }
    return {
      fur: U.mix([150, 108, 74], accent, 0.06), far: U.mix([112, 80, 56], accent, 0.05),
      ear: U.mix([92, 62, 42], accent, 0.05), light: U.mix([214, 182, 146], accent, 0.05),
      line: U.rgba(U.mix([232, 206, 176], accent, 0.25), 0.8), collar: U.rgba(accent), shade: "rgba(0,0,0,0.3)",
    };
  }
  // Each shape list is drawn as one outline pass in the line colour, then a
  // fill pass, so touching parts read as one clean silhouette.
  function fillOf(s, pal) {
    return U.rgba(s.k === "far" ? pal.far : s.k === "ear" ? pal.ear : s.k === "light" ? pal.light : pal.fur);
  }
  function shapes(g, list, pass, pal) {
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      var fill = fillOf(s, pal);
      g.fillStyle = pass ? fill : pal.line;
      g.strokeStyle = pass ? fill : pal.line;
      var grow = pass ? 0 : 1.5;
      g.beginPath();
      if (s.e) {
        g.ellipse(s.e[0], s.e[1], s.e[2] + grow, s.e[3] + grow, s.e[4] || 0, 0, 6.2832);
        g.fill();
      } else if (s.l) {
        g.lineCap = "round";
        g.lineJoin = "round";
        g.lineWidth = s.w + grow * 2;
        g.moveTo(s.l[0], s.l[1]);
        if (s.l.length === 6) g.quadraticCurveTo(s.l[2], s.l[3], s.l[4], s.l[5]);
        else if (s.l.length === 8) g.bezierCurveTo(s.l[2], s.l[3], s.l[4], s.l[5], s.l[6], s.l[7]);
        else g.lineTo(s.l[2], s.l[3]);
        g.stroke();
      }
    }
  }
  // Head at (x, y) facing right: round head, a light muzzle and a floppy ear
  // (the ear goes on the top list so it keeps its own outline over the head).
  function head(hl, top, x, y, tilt, perk) {
    var c = Math.cos(tilt), s = Math.sin(tilt);
    function at(dx, dy) {
      return [x + dx * c - dy * s, y + dx * s + dy * c];
    }
    hl.push({ e: [x, y, 8.5, 7.6, tilt] });
    var m = at(7.5, 2.6);
    hl.push({ e: [m[0], m[1], 6.2, 4.3, tilt], k: "light" });
    var ea = at(-3.2, perk ? -1 : 1.5);
    top.push({ e: [ea[0], ea[1], 3.4, 7, tilt + (perk ? 0.9 : 0.35)], k: "ear" });
    return at;
  }
  function face(g, at, pal, eyes, tongue) {
    var eye = at(2.6, -2.2);
    if (eyes === "open") {
      g.fillStyle = "rgba(24,16,12,0.96)";
      g.beginPath();
      g.ellipse(eye[0], eye[1], 1.7, 1.9, 0, 0, 6.2832);
      g.fill();
      g.fillStyle = "rgba(255,255,255,0.9)";
      g.fillRect(eye[0] - 0.2, eye[1] - 1.1, 0.8, 0.8);
    } else {
      g.strokeStyle = "rgba(30,20,14,0.9)";
      g.lineWidth = 0.9;
      g.beginPath();
      g.moveTo(eye[0] - 1.8, eye[1]);
      g.quadraticCurveTo(eye[0], eye[1] + 1.4, eye[0] + 1.8, eye[1]);
      g.stroke();
    }
    var nose = at(13.2, 1.2);
    g.fillStyle = "rgba(26,18,16,0.96)";
    g.beginPath();
    g.ellipse(nose[0], nose[1], 2.1, 1.6, 0, 0, 6.2832);
    g.fill();
    if (tongue) {
      var tg = at(9.6, 7);
      g.fillStyle = "rgba(236,110,130,0.95)";
      g.beginPath();
      g.ellipse(tg[0], tg[1], 1.5, 2.4, 0, 0, 6.2832);
      g.fill();
    }
  }
  // Build the pose's shapes: body, head, top (ear, raised leg) and the collar.
  function pose(name, f) {
    var body = [], hl = [], top = [], at, eyes = "open", tongue = false, collar, zz = false;
    if (name === "walk" || name === "trot" || name === "stand" || name === "sniff") {
      var trot = name === "trot";
      var still = name === "stand";
      var ph = still ? 0 : (f / 8) * 6.2832;
      var swing = still ? 0 : trot ? 6 : name === "sniff" ? 2.5 : 4.5;
      var bob = still ? 0 : Math.sin(ph * 2) * (trot ? 1.2 : 0.5);
      var legs = [[-12, 0, true], [12, Math.PI / 2, true], [-9, Math.PI, false], [15, Math.PI * 1.5, false]];
      if (trot) legs = [[-12, 0, true], [12, Math.PI, true], [-9, Math.PI, false], [15, 0, false]];
      for (var i = 0; i < legs.length; i++) {
        var L = legs[i], q = ph + L[1];
        var fx = L[0] + Math.sin(q) * swing, lift = still ? 0 : Math.max(0, Math.cos(q)) * (trot ? 3.5 : 2.2);
        var knee = L[0] + Math.sin(q) * swing * 0.4 + (L[0] < 0 ? -1.2 : 1);
        body.push({ l: [L[0], -15 + bob, knee, -7 - lift * 0.5, fx, -1.5 - lift], w: 4.4, k: L[2] ? "far" : "" });
      }
      var wag = name === "sniff" ? Math.sin(ph * 2) * 4 : still ? 0 : Math.sin(ph * 2) * 2.5;
      body.push({ l: [-16, -23 + bob, -22, -27, -25 + wag * 0.4, -33, -23 + wag, -39], w: 3.6 });
      body.push({ e: [0, -20 + bob, 17, 8.2, 0] });
      body.push({ e: [11, -21 + bob, 8.5, 9, 0] });
      if (name === "sniff") {
        var nod = f % 4 < 2 ? 0 : 1.2;
        body.push({ e: [17, -21 + bob, 5.5, 6, 0.6] });
        at = head(hl, top, 25, -16 + bob + nod, 0.6, true);
        collar = [15, -26 + bob, 21, -21 + bob];
      } else {
        body.push({ e: [16, -26 + bob, 5.5, 6.5, 0] });
        at = head(hl, top, 22, -33 + bob * 1.3, -0.05);
        collar = [13.5, -27 + bob, 19.5, -23 + bob];
      }
    } else if (name === "sit" || name === "wag" || name === "scratch") {
      var sweep = name === "wag" ? [0, 4, 7, 4][f % 4] : 0;
      body.push({ l: [-12, -3, -20, -2 - sweep * 0.3, -28 + sweep * 0.4, -4 - sweep], w: 3.6 });
      body.push({ e: [-5, -10, 11, 10, 0] });
      if (name !== "scratch") body.push({ e: [2, -2.2, 6, 2.4, 0] });
      body.push({ e: [2, -18, 9, 12.5, -0.45] });
      body.push({ l: [12, -17, 13, -1.5], w: 4.4, k: "far" });
      body.push({ l: [9, -17, 9.5, -1.5], w: 4.4 });
      body.push({ e: [8, -25, 7.5, 9, -0.3] });
      if (name === "scratch") {
        var kick = [0, -3, 0, -3][f % 4];
        top.push({ l: [-4, -12, 5, -16, 4, -27 + kick], w: 4.2 });
        at = head(hl, top, 12, -36, 0.3);
        eyes = "closed";
        tongue = true;
      } else {
        at = head(hl, top, 12, -37, name === "wag" ? -0.12 : 0);
        tongue = name === "wag";
        if (f === -1) eyes = "closed"; // a blink
      }
      collar = [7, -29, 13, -26];
    } else {
      // lying down, awake or asleep
      var asleep = name === "sleep";
      body.push({ l: [-19, -5, -26, -2, -31, -4], w: 3.6 });
      body.push({ e: [-11, -9, 9.5, 8.5, 0] });
      body.push({ e: [-1, -8, 18, 7.5, 0] });
      body.push({ l: [9, -4, 23, -2.5], w: 4.2, k: "far" });
      body.push({ l: [11, -3, 26, -1.8], w: 4.2 });
      if (asleep) {
        at = head(hl, top, 20, -11, 0.18);
        eyes = "closed";
        zz = true;
      } else {
        at = head(hl, top, 18, -17, 0.05);
        if (f === -1) eyes = "closed";
      }
      collar = null;
    }
    return { body: body, head: hl, top: top, at: at, eyes: eyes, tongue: tongue, collar: collar, zz: zz };
  }
  function draw(cv, name, f, pal) {
    var g = cv.getContext("2d");
    var dpr = cv.width / BW;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(dpr * S, 0, 0, dpr * S, OX * dpr, OY * dpr);
    var sh = g.createRadialGradient(0, 0, 0, 0, 0, 24);
    sh.addColorStop(0, pal.shade);
    sh.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = sh;
    g.save();
    g.scale(1, 0.18);
    g.fillRect(-28, -24, 56, 48);
    g.restore();
    var p = pose(name, f);
    shapes(g, p.body.concat(p.head), 0, pal);
    shapes(g, p.body, 1, pal);
    if (p.collar) {
      g.strokeStyle = pal.collar;
      g.lineCap = "round";
      g.lineWidth = 2.4;
      g.beginPath();
      g.moveTo(p.collar[0], p.collar[1]);
      g.lineTo(p.collar[2], p.collar[3]);
      g.stroke();
    }
    shapes(g, p.head, 1, pal);
    shapes(g, p.top, 0, pal);
    shapes(g, p.top, 1, pal);
    face(g, p.at, pal, p.eyes, p.tongue);
    if (p.zz) {
      g.fillStyle = pal.line;
      g.font = "600 7px sans-serif";
      g.fillText("z", 25, -24);
      g.font = "600 5px sans-serif";
      g.fillText("z", 31, -30);
    }
  }

  /* ---------- behaviour ---------- */
  function rand(a, b) {
    return a + Math.random() * (b - a);
  }
  function pick(table) {
    var r = Math.random(), acc = 0;
    for (var k in table) {
      acc += table[k];
      if (r < acc) return k;
    }
    return k;
  }
  var ANIMATED = { walk: 1, trot: 1, sniff: 1, wag: 1, scratch: 1 };
  var SPEED = { walk: 34, trot: 92, sniff: 12 };

  ForgeLive.companion("dog", {
    lighter: { balanced: "", light: "still" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.round(BW * dpr);
      cv.height = Math.round(BH * dpr);
      cv.className = "forge-dog";
      cv.setAttribute("aria-hidden", "true");
      cv.style.cssText =
        "position:absolute;left:0;width:" + BW + "px;height:" + BH +
        "px;pointer-events:none;will-change:transform;transform-origin:50% 100%";
      layer.appendChild(cv);

      var pal = palette(o);
      var x = 0, dir = Math.random() < 0.5 ? 1 : -1;
      var act = "stand", frame = 0, until = 0, timer = 0, frozen = false, stopped = false;
      var queue = [];
      var drawn = "";

      function width() {
        return Math.max(BW * 2, layer.clientWidth || window.innerWidth || 800);
      }
      function place() {
        cv.style.bottom = Math.max(0, +o.bottom || 0) + "px";
        cv.style.transform = "translate3d(" + Math.round(x) + "px,0,0) scaleX(" + dir + ")";
      }
      function paint(force) {
        var key = act + ":" + frame;
        if (!force && key === drawn) return;
        drawn = key;
        draw(cv, act, frame, pal);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function begin(name, secs) {
        act = name;
        frame = 0;
        until = performance.now() + secs * 1000;
      }
      function next() {
        if (queue.length) {
          var n = queue.shift();
          begin(n[0], n[1]);
          return;
        }
        var from = act;
        var choice = SPEED[from]
          ? pick({ stand: 0.25, sit: 0.2, turn: 0.15, trot: 0.1, sniff: 0.1, walk: 0.2 })
          : from === "stand"
            ? pick({ walk: 0.5, sniff: 0.15, sit: 0.2, turn: 0.15 })
            : from === "sleep"
              ? "wake"
              : pick({ walk: 0.5, stand: 0.2, turn: 0.3 });
        if (choice === "walk") begin("walk", rand(3, 8));
        else if (choice === "trot") begin("trot", rand(1.2, 2.8));
        else if (choice === "sniff") begin("sniff", rand(2, 4.5));
        else if (choice === "stand") begin("stand", rand(1, 2.5));
        else if (choice === "turn") {
          dir = -dir;
          begin("stand", rand(0.6, 1.4));
        } else if (choice === "wake") {
          begin("lie", rand(1.2, 2.5));
          queue.push(["sit", rand(1, 2)], ["wag", rand(1, 2)], ["stand", 0.8]);
        } else {
          // sit, then maybe wag, scratch, or lie down for a nap
          begin("sit", rand(1.5, 4));
          var r = Math.random();
          if (r < 0.35) queue.push(["wag", rand(1.5, 3)], ["sit", rand(1, 2.5)]);
          else if (r < 0.6) queue.push(["scratch", rand(1.2, 2.2)], ["sit", rand(1, 2)]);
          if (Math.random() < 0.4) queue.push(["lie", rand(2, 5)], ["sleep", rand(20, 60)]);
        }
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode()) return;
        if (document.hidden) return; // resumes on visibilitychange
        var now = performance.now();
        if (now >= until) next();
        var sp = SPEED[act] || 0;
        if (sp) {
          x += (dir * sp) / FPS;
          var max = width() - BW;
          if (x < 0 || x > max) {
            x = Math.max(0, Math.min(max, x));
            dir = -dir;
            begin("stand", rand(0.5, 1.2));
          }
        }
        var anim = !!ANIMATED[act];
        if (anim) frame = (frame + 1) % 8;
        place();
        paint(false);
        // still poses wait for their end (with a blink now and then); nothing
        // is redrawn while it naps
        var wait = 1000 / FPS;
        if (!anim) {
          wait = Math.max(wait, until - performance.now());
          if ((act === "sit" || act === "lie") && wait > 1800 && Math.random() < 0.7) {
            wait = rand(1200, 2400);
            blink();
          }
        }
        timer = setTimeout(tick, wait);
      }
      function blink() {
        var was = act;
        draw(cv, act, -1, pal);
        drawn = "";
        setTimeout(function () {
          if (!stopped && act === was) paint(true);
        }, 140);
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / FPS);
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "sit";
        act = p;
        frame = ANIMATED[p] ? 2 : 0;
        x = Math.round((width() - BW) * 0.72);
        dir = 1;
        place();
        paint(true);
      }
      function onVis() {
        schedule();
      }
      function onResize() {
        x = Math.max(0, Math.min(width() - BW, x));
        place();
      }
      document.addEventListener("visibilitychange", onVis);
      window.addEventListener("resize", onResize);

      if (staticMode()) still();
      else {
        x = rand(0.1, 0.8) * (width() - BW);
        begin("sit", rand(1, 3));
        place();
        paint(true);
        schedule();
      }

      return {
        stop: function () {
          stopped = true;
          if (timer) clearTimeout(timer);
          document.removeEventListener("visibilitychange", onVis);
          window.removeEventListener("resize", onResize);
          if (cv.parentNode) cv.parentNode.removeChild(cv);
        },
        update: function (n) {
          var was = staticMode();
          o = n || {};
          pal = palette(o);
          if (staticMode()) still();
          else {
            if (was) begin("stand", 1);
            place();
            paint(true);
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
