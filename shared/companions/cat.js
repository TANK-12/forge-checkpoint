/* companion: Cat | A small cat that wanders along the bottom of the window, sits, grooms and naps */
(function () {
  var U = ForgeLive.util;
  var S = 1.25; // drawing scale: the cat is about 58 px tall sitting
  var BW = 96, BH = 84; // the cat's own small canvas, CSS px
  var OX = 48, OY = 78; // where the cat's feet are inside it
  var FPS = 12;
  var POSES = { sit: 1, walk: 1, trot: 1, stand: 1, sleep: 1, groom: 1, yawn: 1 };

  /* ---------- drawing ---------- */
  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    if (o.mode === "light") {
      return { fur: [92, 90, 98], far: [70, 68, 76], line: "rgba(22,22,28,0.95)", eye: U.mix([150, 190, 60], accent, 0.3), shade: "rgba(0,0,0,0.16)" };
    }
    return {
      fur: U.mix([44, 46, 56], accent, 0.08), far: U.mix([30, 32, 40], accent, 0.06),
      line: U.rgba(U.mix([170, 180, 205], accent, 0.35), 0.85), eye: U.mix([190, 230, 90], accent, 0.35),
      shade: "rgba(0,0,0,0.3)",
    };
  }
  // A shape list is drawn twice: once thick in the outline colour, then in fur,
  // so overlapping parts read as one clean silhouette.
  function shapes(g, list, pass, pal) {
    for (var i = 0; i < list.length; i++) {
      var s = list[i];
      var fill = U.rgba(s.far ? pal.far : pal.fur);
      g.fillStyle = pass ? fill : pal.line;
      g.strokeStyle = pass ? fill : pal.line;
      var grow = pass ? 0 : 1.6;
      g.beginPath();
      if (s.e) {
        g.ellipse(s.e[0], s.e[1], s.e[2] + grow, s.e[3] + grow, s.e[4] || 0, 0, 6.2832);
        g.fill();
      } else if (s.p) {
        g.moveTo(s.p[0], s.p[1]);
        for (var k = 2; k < s.p.length; k += 2) g.lineTo(s.p[k], s.p[k + 1]);
        g.closePath();
        g.lineJoin = "round";
        g.lineWidth = grow * 2 || 0.01;
        g.fill();
        if (grow) g.stroke();
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
  function head(list, x, y, tilt, ears) {
    var c = Math.cos(tilt), s = Math.sin(tilt);
    function at(dx, dy) {
      return [x + dx * c - dy * s, y + dx * s + dy * c];
    }
    var e = ears || 1;
    var a = at(-7, -4), b = at(-5, -4 - 10 * e), d = at(-1, -8);
    var f = at(1, -8), g2 = at(6, -4 - 10 * e), h = at(8, -3);
    list.push({ p: [a[0], a[1], b[0], b[1], d[0], d[1]] });
    list.push({ p: [f[0], f[1], g2[0], g2[1], h[0], h[1]] });
    list.push({ e: [x, y, 9, 8, tilt] });
    var m = at(6, 3);
    list.push({ e: [m[0], m[1], 4.2, 3.2, tilt] });
    return at;
  }
  function face(g, at, pal, eyes, mouth) {
    var eye = at(3.5, -1.5);
    if (eyes === "open") {
      g.fillStyle = U.rgba(pal.eye);
      g.beginPath();
      g.ellipse(eye[0], eye[1], 1.7, 2.1, 0, 0, 6.2832);
      g.fill();
      g.fillStyle = "rgba(10,10,12,0.95)";
      g.fillRect(eye[0] - 0.35, eye[1] - 1.5, 0.7, 3);
    } else {
      g.strokeStyle = pal.line;
      g.lineWidth = 0.9;
      g.beginPath();
      g.moveTo(eye[0] - 1.8, eye[1]);
      g.quadraticCurveTo(eye[0], eye[1] + 1.4, eye[0] + 1.8, eye[1]);
      g.stroke();
    }
    var nose = at(9.6, 1.6);
    g.fillStyle = "rgba(230,150,160,0.9)";
    g.fillRect(nose[0] - 0.8, nose[1] - 0.6, 1.6, 1.2);
    if (mouth) {
      var mo = at(7.5, 5);
      g.fillStyle = "rgba(60,20,30,0.95)";
      g.beginPath();
      g.ellipse(mo[0], mo[1], 2.2, 2.6, 0, 0, 6.2832);
      g.fill();
    }
  }
  // Build the pose's shapes; returns {list, face: fn} for the details pass.
  function pose(name, f) {
    var list = [], at, eyes = "open", mouth = false;
    if (name === "walk" || name === "trot" || name === "stand") {
      var trot = name === "trot";
      var ph = name === "stand" ? 0 : (f / 8) * 6.2832;
      var swing = name === "stand" ? 0 : trot ? 6 : 4.5;
      var bob = name === "stand" ? 0 : Math.sin(ph * 2) * (trot ? 1.2 : 0.6);
      var legs = [
        [-12, 0, true], [12, Math.PI / 2, true], [-9, Math.PI, false], [15, Math.PI * 1.5, false],
      ];
      if (trot) legs = [[-12, 0, true], [12, Math.PI, true], [-9, Math.PI, false], [15, 0, false]];
      for (var i = 0; i < legs.length; i++) {
        var L = legs[i], q = ph + L[1];
        var fx = L[0] + Math.sin(q) * swing, lift = Math.max(0, Math.cos(q)) * (trot ? 3.5 : 2.5);
        if (name === "stand") lift = 0;
        var knee = L[0] + Math.sin(q) * swing * 0.4 + (L[0] < 0 ? -1.5 : 1);
        list.push({ l: [L[0], -15 + bob, knee, -7 - lift * 0.5, fx, -1.5 - lift], w: 4.2, far: L[2] });
      }
      var tw = name === "stand" ? 0 : Math.sin(ph) * 2;
      list.push({ l: [-18, -22 + bob, -30, -26 + tw, -27, -38 + tw, trot ? -24 : -31, trot ? -46 : -43 + tw], w: 4 });
      list.push({ e: [0, -20 + bob, 20, 9.5, 0] });
      list.push({ e: [13, -22 + bob, 8, 8.5, 0] });
      at = head(list, 22, -31 + bob * 1.3, 0.05);
    } else if (name === "sit" || name === "groom" || name === "yawn") {
      var bobG = name === "groom" ? (f % 4 < 2 ? 0 : 1.2) : 0;
      list.push({ l: [-15, -5, -14, 3, 4, 1, 12, -1], w: 4 }); // tail wrapped in front
      list.push({ e: [-5, -12, 14, 12, 0] });
      list.push({ l: [9, -16, 10, -1.5], w: 4.2 });
      if (name !== "groom") list.push({ l: [13, -16, 14, -1.5], w: 4.2 });
      list.push({ e: [6, -22, 9, 13, -0.35] });
      if (name === "groom") list.push({ l: [11, -16, 18, -24, 18, -30 + bobG], w: 4, top: true }); // paw up to the mouth
      if (name === "groom") at = head(list, 13, -33 + bobG, 0.45);
      else if (name === "yawn") at = head(list, 9, -41, -0.35);
      else at = head(list, 9, -40, 0);
      if (name === "groom") eyes = "closed";
      if (name === "yawn") {
        eyes = "closed";
        mouth = true;
      }
      if (name === "sit" && f === -1) eyes = "closed"; // a blink
    } else {
      // asleep: a loaf with the tail round the front
      list.push({ e: [-2, -11, 21, 11, 0] });
      list.push({ e: [-12, -13, 10, 9, 0] });
      list.push({ l: [-21, -5, -12, 4, 8, 3, 20, -1], w: 4.5 });
      at = head(list, 15, -14, 0.25, 0.75);
      eyes = "closed";
    }
    return { list: list, at: at, eyes: eyes, mouth: mouth };
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
    g.fillRect(-26, -24, 52, 48);
    g.restore();
    var p = pose(name, f);
    // parts marked top (a raised paw) get their own outline over the body
    var body = p.list.filter(function (s) { return !s.top; });
    var top = p.list.filter(function (s) { return s.top; });
    shapes(g, body, 0, pal);
    shapes(g, body, 1, pal);
    shapes(g, top, 0, pal);
    shapes(g, top, 1, pal);
    face(g, p.at, pal, p.eyes, p.mouth);
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

  ForgeLive.companion("cat", {
    lighter: { balanced: "", light: "still" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.round(BW * dpr);
      cv.height = Math.round(BH * dpr);
      cv.className = "forge-cat";
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
        var key = act + ":" + frame + ":" + dir;
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
        var choice =
          from === "walk" || from === "trot"
            ? pick({ stand: 0.3, sit: 0.25, turn: 0.15, trot: 0.1, walk: 0.2 })
            : from === "stand"
              ? pick({ walk: 0.6, sit: 0.25, turn: 0.15 })
              : from === "sleep"
                ? "wake"
                : pick({ walk: 0.5, stand: 0.2, turn: 0.3 });
        if (choice === "walk") begin("walk", rand(3, 9));
        else if (choice === "trot") begin("trot", rand(1.2, 2.6));
        else if (choice === "stand") begin("stand", rand(1, 2.5));
        else if (choice === "turn") {
          dir = -dir;
          begin("stand", rand(0.6, 1.4));
        } else if (choice === "wake") {
          begin("yawn", 1.4);
          queue.push(["sit", rand(1.5, 3)], ["stand", 0.8]);
        } else {
          // sit, and maybe groom, yawn or curl up for a nap
          begin("sit", rand(2, 5));
          var r = Math.random();
          if (r < 0.35) queue.push(["groom", rand(2, 4)], ["sit", rand(1, 3)]);
          else if (r < 0.5) queue.push(["yawn", 1.3], ["sit", rand(1, 2)]);
          if (Math.random() < 0.4) queue.push(["sleep", rand(20, 60)]);
        }
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode()) return;
        if (document.hidden) return; // resumes on visibilitychange
        var now = performance.now();
        if (now >= until) next();
        var moving = act === "walk" || act === "trot";
        if (moving) {
          var sp = act === "trot" ? 95 : 36;
          x += (dir * sp) / FPS;
          var max = width() - BW;
          if (x < 0 || x > max) {
            x = Math.max(0, Math.min(max, x));
            dir = -dir;
            begin("stand", rand(0.5, 1.2));
          }
        }
        if (moving || act === "groom") frame = (frame + 1) % 8;
        place();
        paint(false);
        // still poses wait for their end (with a blink now and then); nothing
        // is redrawn while it naps
        var wait = 1000 / FPS;
        if (!moving && act !== "groom") {
          wait = Math.max(wait, until - performance.now());
          if (act === "sit" && wait > 1800 && Math.random() < 0.7) {
            wait = rand(1200, 2400);
            blink();
          }
        }
        timer = setTimeout(tick, wait);
      }
      function blink() {
        draw(cv, "sit", -1, pal);
        drawn = "";
        setTimeout(function () {
          if (!stopped && act === "sit") paint(true);
        }, 140);
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / FPS);
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "sit";
        act = p === "walk" ? "walk" : p;
        frame = p === "walk" ? 2 : 0;
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
        update: function (next) {
          var was = staticMode();
          o = next || {};
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
