/* companion: Fish | A few little fish that swim to and fro along the bottom of the window, turn about and blow the odd bubble */
(function () {
  var U = ForgeLive.util;
  var BAND = 170; // CSS px of the window's bottom the fish keep to
  var POSES = { swim: 1, bubble: 1 };

  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    var light = o.mode === "light";
    return {
      fish: [[255, 150, 70], accent, [255, 214, 90], U.mix([120, 220, 200], accent, 0.3)],
      line: light ? "rgba(40,50,70,0.55)" : "rgba(8,14,26,0.6)",
      eye: "rgba(16,20,30,0.95)",
      bubble: light ? "rgba(60,90,130,0.5)" : "rgba(220,240,255,0.55)",
      alpha: light ? 0.95 : 0.9,
    };
  }
  function drawFish(g, f, c, line, eye, alpha) {
    var s = f.s, wag = Math.sin(f.ph) * 0.35;
    g.save();
    g.translate(f.x, f.y);
    g.scale(f.dir * s, s);
    g.lineWidth = 1.3 / s;
    g.strokeStyle = line;
    g.fillStyle = U.rgba(c, alpha);
    // tail, swung by wag
    g.save();
    g.translate(-12, 0);
    g.rotate(wag);
    g.beginPath();
    g.moveTo(2, 0);
    g.lineTo(-9, -7);
    g.quadraticCurveTo(-6, 0, -9, 7);
    g.closePath();
    g.fill();
    g.stroke();
    g.restore();
    // body and a fin
    g.beginPath();
    g.ellipse(0, 0, 14, 8, 0, 0, 6.2832);
    g.fill();
    g.stroke();
    g.fillStyle = U.rgba(U.mix(c, [255, 255, 255], 0.35), alpha);
    g.beginPath();
    g.moveTo(-3, -7);
    g.quadraticCurveTo(2, -13 - wag * 4, 6, -7);
    g.closePath();
    g.fill();
    g.fillStyle = eye;
    g.beginPath();
    g.arc(8, -2, 1.7, 0, 6.2832);
    g.fill();
    g.restore();
  }
  var R = Math.random; // a seeded generator while drawing a still, so a still repeats
  function rand(a, b) {
    return a + R() * (b - a);
  }

  ForgeLive.companion("fish", {
    layer: "back", // scenery: behind the tiles and apps
    lighter: { balanced: "", light: "off" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      cv.className = "forge-fish";
      cv.setAttribute("aria-hidden", "true");
      cv.style.cssText = "position:absolute;left:0;width:100%;pointer-events:none";
      layer.appendChild(cv);
      var pal = palette(o);
      var W = 0, dpr = 1, fish = [], bubbles = [], timer = 0, frozen = false, stopped = false;

      function fps() {
        return o.lite ? 8 : 15;
      }
      function size() {
        dpr = Math.min(2, window.devicePixelRatio || 1);
        W = Math.max(320, layer.clientWidth || window.innerWidth || 800);
        cv.style.height = BAND + "px";
        cv.style.bottom = Math.max(0, +o.bottom || 0) + "px";
        cv.width = Math.round(W * dpr);
        cv.height = Math.round(BAND * dpr);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function school() {
        fish = [];
        var n = W < 700 ? 3 : 4;
        for (var i = 0; i < n; i++) {
          fish.push({
            x: ((i + 0.5) / n) * W + rand(-40, 40), y: rand(40, BAND - 26), dir: i % 2 ? -1 : 1,
            s: rand(0.75, 1.15), v: rand(18, 34), ph: rand(0, 6.28), ty: rand(40, BAND - 26), c: i % 4,
          });
        }
      }
      function paint() {
        var g = cv.getContext("2d");
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.clearRect(0, 0, cv.width, cv.height);
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.strokeStyle = pal.bubble;
        g.lineWidth = 1.2;
        for (var j = 0; j < bubbles.length; j++) {
          var b = bubbles[j];
          g.globalAlpha = Math.max(0, Math.min(1, b.life));
          g.beginPath();
          g.arc(b.x, b.y, b.r, 0, 6.2832);
          g.stroke();
        }
        g.globalAlpha = 1;
        for (var i = 0; i < fish.length; i++) drawFish(g, fish[i], pal.fish[fish[i].c], pal.line, pal.eye, pal.alpha);
      }
      function blow(f) {
        for (var k = 0; k < 3; k++)
          bubbles.push({ x: f.x + f.dir * 15 * f.s, y: f.y - 2 - k * 7, r: 1.6 + k * 0.9, life: 1.6 + k * 0.2 });
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode() || document.hidden) return;
        var dt = 1 / fps();
        for (var i = 0; i < fish.length; i++) {
          var f = fish[i];
          f.x += f.dir * f.v * dt;
          f.ph += dt * (6 + f.v / 6);
          f.y += (f.ty - f.y) * dt * 0.6;
          if (Math.random() < dt * 0.25) f.ty = rand(40, BAND - 26);
          var turn = (f.dir > 0 && f.x > W - 30) || (f.dir < 0 && f.x < 30) || Math.random() < dt * 0.04;
          if (turn) f.dir = -f.dir;
          if (Math.random() < dt * 0.05) blow(f);
        }
        for (var j = bubbles.length - 1; j >= 0; j--) {
          var b = bubbles[j];
          b.y -= 26 * dt;
          b.x += Math.sin(b.y / 9) * 0.3;
          b.life -= dt * 0.7;
          if (b.life <= 0 || b.y < 0) bubbles.splice(j, 1);
        }
        paint();
        timer = setTimeout(tick, 1000 / fps());
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / fps());
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "swim";
        R = U.rng(4027);
        school();
        R = Math.random;
        bubbles = [];
        if (p === "bubble") blow(fish[0]);
        paint();
      }
      function onResize() {
        size();
        if (staticMode()) return still();
        school();
        paint();
      }
      document.addEventListener("visibilitychange", schedule);
      window.addEventListener("resize", onResize);
      size();
      school();
      if (staticMode()) still();
      else {
        paint();
        schedule();
      }
      return {
        stop: function () {
          stopped = true;
          if (timer) clearTimeout(timer);
          document.removeEventListener("visibilitychange", schedule);
          window.removeEventListener("resize", onResize);
          if (cv.parentNode) cv.parentNode.removeChild(cv);
        },
        update: function (n) {
          o = n || {};
          pal = palette(o);
          size();
          if (staticMode()) still();
          else {
            paint();
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
