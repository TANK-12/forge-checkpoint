/* companion: Ghost | A little friendly ghost that floats about the lower part of the window, bobs, blinks and loops */
(function () {
  var U = ForgeLive.util;
  var BW = 76, BH = 84; // the ghost's own small canvas, CSS px
  var CX = 38, CY = 38; // the ghost's middle inside it
  var FPS = 12;
  var POSES = { float: 1, blink: 1, happy: 1, whee: 1 };

  /* ---------- drawing ---------- */
  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    if (o.mode === "light") {
      return {
        top: [255, 255, 255], bottom: U.mix([226, 232, 246], accent, 0.18), line: "rgba(70,80,110,0.6)",
        glow: "rgba(0,0,0,0)", eye: "rgba(34,34,52,0.95)", cheek: "rgba(240,130,150,0.5)",
      };
    }
    return {
      top: U.mix([246, 248, 255], accent, 0.04), bottom: U.mix([206, 214, 240], accent, 0.3),
      line: U.rgba(U.mix([255, 255, 255], accent, 0.3), 0.55), glow: U.rgba(accent, 0.45),
      eye: "rgba(26,26,44,0.95)", cheek: "rgba(250,140,170,0.45)",
    };
  }
  // f: hem wave frame 0..11; eyes: open | closed | happy; look: -1..1; mouth: smile | o
  function draw(cv, f, eyes, look, mouth, pal) {
    var g = cv.getContext("2d");
    var dpr = cv.width / BW;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(dpr, 0, 0, dpr, CX * dpr, CY * dpr);
    var ph = (f / 12) * 6.2832;
    var R = 17, hem = 17;
    function body() {
      g.beginPath();
      // little arms, then the dome and a wavy hem
      g.moveTo(-R, hem);
      g.lineTo(-R, -3);
      g.arc(0, -3, R, Math.PI, 0);
      g.lineTo(R, hem);
      for (var i = 0; i < 4; i++) {
        var x0 = R - i * 8.5, x1 = x0 - 8.5;
        var dip = hem + 6 + Math.sin(ph + i * 1.7) * 2.4;
        g.quadraticCurveTo(x0 - 4.25, dip, x1, hem + Math.sin(ph + i * 1.7 + 1) * 1.2);
      }
      g.closePath();
    }
    var sway = Math.sin(ph) * 0.25;
    function arms() {
      g.beginPath();
      g.ellipse(-R - 1, 5, 3.6, 6, 0.7 + sway, 0, 6.2832);
      g.moveTo(R + 4.6, 5);
      g.ellipse(R + 1, 5, 3.6, 6, -0.7 - sway, 0, 6.2832);
    }
    var grad = g.createLinearGradient(0, -R - 3, 0, hem + 8);
    grad.addColorStop(0, U.rgba(pal.top, 0.96));
    grad.addColorStop(1, U.rgba(pal.bottom, 0.82));
    g.lineJoin = "round";
    g.shadowColor = pal.glow;
    g.shadowBlur = 10 * dpr;
    g.fillStyle = grad;
    arms();
    g.fill();
    body();
    g.fill();
    g.shadowBlur = 0;
    g.strokeStyle = pal.line;
    g.lineWidth = 1.3;
    arms();
    g.stroke();
    g.fillStyle = grad;
    body();
    g.fill();
    g.stroke();
    // face
    var lx = look * 2.2;
    g.fillStyle = pal.cheek;
    g.beginPath();
    g.ellipse(-9 + lx, 3, 3, 1.8, 0, 0, 6.2832);
    g.ellipse(9 + lx, 3, 3, 1.8, 0, 0, 6.2832);
    g.fill();
    g.fillStyle = pal.eye;
    g.strokeStyle = pal.eye;
    g.lineWidth = 1.4;
    g.lineCap = "round";
    for (var s = -1; s <= 1; s += 2) {
      var ex = s * 5.8 + lx, ey = -3;
      g.beginPath();
      if (eyes === "open") {
        g.ellipse(ex, ey, 2.4, 3.3, 0, 0, 6.2832);
        g.fill();
        g.fillStyle = "rgba(255,255,255,0.95)";
        g.beginPath();
        g.arc(ex + 0.8, ey - 1.2, 0.9, 0, 6.2832);
        g.fill();
        g.fillStyle = pal.eye;
      } else if (eyes === "happy") {
        g.moveTo(ex - 2.3, ey + 0.8);
        g.quadraticCurveTo(ex, ey - 2.6, ex + 2.3, ey + 0.8);
        g.stroke();
      } else {
        g.moveTo(ex - 2.3, ey);
        g.quadraticCurveTo(ex, ey + 1.8, ex + 2.3, ey);
        g.stroke();
      }
    }
    g.beginPath();
    if (mouth === "o") {
      g.ellipse(lx, 4.5, 1.8, 2.3, 0, 0, 6.2832);
      g.fill();
    } else {
      g.lineWidth = 1.1;
      g.moveTo(lx - 2, 3.4);
      g.quadraticCurveTo(lx, 5.4, lx + 2, 3.4);
      g.stroke();
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

  ForgeLive.companion("ghost", {
    lighter: { balanced: "", light: "still" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.round(BW * dpr);
      cv.height = Math.round(BH * dpr);
      cv.className = "forge-ghost";
      cv.setAttribute("aria-hidden", "true");
      cv.style.cssText =
        "position:absolute;left:0;top:0;width:" + BW + "px;height:" + BH +
        "px;pointer-events:none;will-change:transform,opacity;transition:opacity 1.2s ease";
      layer.appendChild(cv);

      var pal = palette(o);
      var x = 0, y = 0, tx = 0, ty = 0, look = 0;
      var act = "hover", until = 0, timer = 0, frozen = false, stopped = false;
      var frame = 0, eyes = "open", mouth = "smile", loopT = 0, fadeAt = 0;
      var drawn = "", t0 = performance.now();

      function size() {
        return {
          w: Math.max(BW * 2, layer.clientWidth || window.innerWidth || 800),
          h: Math.max(BH * 2, layer.clientHeight || window.innerHeight || 600),
        };
      }
      // the band the ghost keeps to: the lower part of the window
      function band() {
        var s = size(), b = Math.max(0, +o.bottom || 0);
        var lo = s.h - b - BH - 4, hi = Math.max(0, s.h - b - BH - Math.min(220, s.h * 0.4));
        return { x0: 0, x1: s.w - BW, y0: hi, y1: lo };
      }
      function clampIn() {
        var B = band();
        x = Math.max(B.x0, Math.min(B.x1, x));
        y = Math.max(B.y0, Math.min(B.y1, y));
      }
      function place(now) {
        var bob = Math.sin((now - t0) / 700) * 4;
        var lx = 0, ly = 0, rot = 0;
        if (act === "loop") {
          var a = loopT * 6.2832;
          lx = Math.sin(a) * 16 * (look < 0 ? -1 : 1);
          ly = -(1 - Math.cos(a)) * 16;
          rot = a * (look < 0 ? -1 : 1);
        } else rot = look * 0.08;
        cv.style.transform =
          "translate3d(" + Math.round(x + lx) + "px," + Math.round(y + ly + bob) + "px,0) rotate(" + rot.toFixed(3) + "rad)";
      }
      function paint(force) {
        var key = frame + ":" + eyes + ":" + look.toFixed(1) + ":" + mouth;
        if (!force && key === drawn) return;
        drawn = key;
        draw(cv, frame, eyes, look, mouth, pal);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function begin(name, secs) {
        act = name;
        until = performance.now() + secs * 1000;
        eyes = name === "rest" ? "happy" : "open";
        mouth = name === "loop" ? "o" : "smile";
        if (name === "drift") {
          var B = band();
          tx = rand(B.x0, B.x1);
          ty = rand(B.y0, B.y1);
        }
        if (name === "loop") loopT = 0;
        cv.style.opacity = name === "rest" ? "0.62" : "0.88";
      }
      function next() {
        var choice = act === "drift"
          ? pick({ hover: 0.45, loop: 0.15, rest: 0.15, drift: 0.25 })
          : act === "rest"
            ? "drift"
            : pick({ drift: 0.7, loop: 0.1, rest: 0.2 });
        if (choice === "drift") begin("drift", rand(4, 9));
        else if (choice === "hover") begin("hover", rand(2, 5));
        else if (choice === "loop") begin("loop", 1.8);
        else begin("rest", rand(6, 16));
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode()) return;
        if (document.hidden) return; // resumes on visibilitychange
        var now = performance.now();
        if (now >= until) next();
        if (act === "drift") {
          var dx = tx - x, dy = ty - y, d = Math.sqrt(dx * dx + dy * dy);
          if (d < 3) begin("hover", rand(1.5, 4));
          else {
            var sp = Math.min(28, d * 1.5) / FPS;
            x += (dx / d) * sp;
            y += (dy / d) * sp;
            var want = Math.max(-1, Math.min(1, dx / 40));
            look += (want - look) * 0.25;
          }
        } else if (act === "loop") {
          loopT = Math.min(1, loopT + 1 / (1.6 * FPS));
        } else if (act === "hover") {
          look *= 0.9;
          // now and then it fades a little, then comes back
          if (now > fadeAt) {
            fadeAt = now + rand(8000, 20000);
            if (Math.random() < 0.5) {
              cv.style.opacity = "0.4";
              setTimeout(function () {
                if (!stopped && act !== "rest") cv.style.opacity = "0.88";
              }, 1600);
            }
          }
        }
        if (act === "rest") {
          // resting: one still picture, nothing redrawn until it wakes
          place(t0);
          paint(false);
          timer = setTimeout(tick, Math.max(1000 / FPS, until - performance.now()));
          return;
        }
        frame = (frame + 1) % 12;
        if (act !== "loop" && eyes === "open" && Math.random() < 0.02) {
          eyes = "closed";
          setTimeout(function () {
            if (eyes === "closed" && act !== "rest") eyes = "open";
          }, 150);
        }
        place(now);
        paint(false);
        timer = setTimeout(tick, 1000 / FPS);
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / FPS);
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "float";
        var s = size(), B = band();
        x = Math.round((s.w - BW) * 0.7);
        y = Math.round((B.y0 + B.y1) / 2);
        act = "hover";
        look = p === "whee" ? 1 : 0;
        frame = 3;
        eyes = p === "blink" ? "closed" : p === "happy" ? "happy" : "open";
        mouth = p === "whee" ? "o" : "smile";
        cv.style.transition = "none";
        cv.style.opacity = "0.88";
        place(t0);
        paint(true);
      }
      function onVis() {
        schedule();
      }
      function onResize() {
        clampIn();
        place(performance.now());
      }
      document.addEventListener("visibilitychange", onVis);
      window.addEventListener("resize", onResize);

      if (staticMode()) still();
      else {
        var B0 = band();
        x = rand(0.15, 0.8) * B0.x1;
        y = rand(B0.y0, B0.y1);
        fadeAt = performance.now() + rand(6000, 14000);
        begin("hover", rand(1, 2.5));
        place(performance.now());
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
            if (was) {
              cv.style.transition = "opacity 1.2s ease";
              begin("hover", 1);
            }
            clampIn();
            place(performance.now());
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
