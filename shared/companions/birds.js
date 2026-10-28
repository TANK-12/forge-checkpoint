/* companion: Birds | A small flock that flaps and glides across the top of the window now and then, then leaves the sky quiet for a while */
(function () {
  var U = ForgeLive.util;
  var FPS = 20;
  var POSES = { fly: 1, glide: 1 };

  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    return o.mode === "light"
      ? { ink: U.rgba(U.mix([46, 52, 70], accent, 0.15), 0.8) }
      : { ink: U.rgba(U.mix([226, 232, 244], accent, 0.2), 0.78) };
  }
  // one bird: an "m" of two curved wings; flap -1 (down) .. 1 (up)
  function bird(g, x, y, s, flap) {
    var up = flap * 7 * s;
    g.beginPath();
    g.moveTo(x - 11 * s, y - up * 0.4);
    g.quadraticCurveTo(x - 5 * s, y - up - 3 * s, x, y + 1.5 * s);
    g.quadraticCurveTo(x + 5 * s, y - up - 3 * s, x + 11 * s, y - up * 0.4);
    g.stroke();
  }
  var R = Math.random; // a seeded generator while drawing a still, so a still repeats
  function rand(a, b) {
    return a + R() * (b - a);
  }

  ForgeLive.companion("birds", {
    layer: "back", // scenery: behind the tiles and apps
    lighter: { balanced: "", light: "off" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      cv.className = "forge-birds";
      cv.setAttribute("aria-hidden", "true");
      cv.style.cssText = "position:absolute;left:0;top:0;width:100%;pointer-events:none";
      layer.appendChild(cv);
      var pal = palette(o);
      var W = 0, H = 0, dpr = 1;
      var flock = null, timer = 0, frozen = false, stopped = false;

      function size() {
        dpr = Math.min(2, window.devicePixelRatio || 1);
        W = Math.max(320, layer.clientWidth || window.innerWidth || 800);
        H = Math.round(Math.max(160, (layer.clientHeight || window.innerHeight || 600) * 0.45));
        cv.style.height = H + "px";
        cv.width = Math.round(W * dpr);
        cv.height = Math.round(H * dpr);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function newFlock(midway) {
        var n = 3 + Math.floor(R() * 4), dir = R() < 0.5 ? 1 : -1, birds = [];
        for (var i = 0; i < n; i++) {
          // a loose V behind the leader
          var row = Math.ceil(i / 2), side = i % 2 ? 1 : -1;
          birds.push({ dx: -row * rand(20, 30), dy: side * row * rand(9, 14), s: rand(0.75, 1.05), ph: rand(0, 6.28) });
        }
        return {
          dir: dir, birds: birds, speed: rand(60, 100), y: rand(0.2, 0.7) * H,
          x: midway ? W * 0.45 : dir > 0 ? -60 : W + 60, t0: performance.now(), glide: 0,
        };
      }
      function paint(now, flapOverride) {
        var g = cv.getContext("2d");
        g.setTransform(1, 0, 0, 1, 0, 0);
        g.clearRect(0, 0, cv.width, cv.height);
        if (!flock) return;
        g.setTransform(dpr, 0, 0, dpr, 0, 0);
        g.strokeStyle = pal.ink;
        g.lineWidth = 1.8;
        g.lineCap = "round";
        var t = (now - flock.t0) / 1000;
        for (var i = 0; i < flock.birds.length; i++) {
          var b = flock.birds[i];
          var flap = flapOverride !== undefined ? flapOverride : flock.glide > 0 ? 0.25 : Math.sin(t * 9 + b.ph);
          var bob = Math.sin(t * 1.3 + b.ph) * 4;
          bird(g, flock.x + b.dx * flock.dir, flock.y + b.dy + bob, b.s, flap);
        }
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode() || document.hidden) return;
        var now = performance.now();
        if (!flock) {
          flock = newFlock(false);
        }
        flock.x += (flock.dir * flock.speed) / FPS;
        flock.y += Math.sin((now - flock.t0) / 2400) * 0.25;
        // now and then the flock stops flapping and glides
        if (flock.glide > 0) flock.glide--;
        else if (Math.random() < 0.01) flock.glide = Math.round(FPS * rand(0.8, 1.8));
        paint(now);
        var gone = flock.dir > 0 ? flock.x > W + 140 : flock.x < -140;
        if (gone) {
          flock = null;
          paint(now);
          timer = setTimeout(tick, rand(9, 25) * 1000); // a quiet sky until the next flock
          return;
        }
        timer = setTimeout(tick, 1000 / FPS);
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, flock ? 1000 / FPS : 2500);
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "fly";
        R = U.rng(4021);
        flock = newFlock(true);
        R = Math.random;
        flock.t0 = 0;
        paint(0, p === "glide" ? 0.25 : 0.8);
      }
      function onResize() {
        size();
        if (staticMode()) still();
        else paint(performance.now());
      }
      document.addEventListener("visibilitychange", schedule);
      window.addEventListener("resize", onResize);
      size();
      if (staticMode()) still();
      else {
        flock = newFlock(false);
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
          var was = staticMode();
          o = n || {};
          pal = palette(o);
          if (staticMode()) still();
          else {
            if (was) flock = null;
            paint(performance.now());
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
