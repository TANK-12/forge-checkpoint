/* live: Forge Flow | Slow threads of accent-coloured light drifting over deep blue-black */
(function () {
  var U = ForgeLive.util;
  var bg, threads, motes, accent, deep;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    var s = (o.surfaces && o.surfaces.bg) || "";
    deep = s && U.lum(s) < 0.2 ? U.hex(s) : [8, 11, 20];
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    lin.addColorStop(0, U.rgba(U.mix(deep, accent, 0.1)));
    lin.addColorStop(0.55, U.rgba(deep));
    lin.addColorStop(1, U.rgba(U.mix(deep, [0, 0, 0], 0.45)));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var r = g.createRadialGradient(w * 0.72, h * 0.18, 0, w * 0.72, h * 0.18, w * 0.6);
    r.addColorStop(0, U.rgba(accent, 0.13));
    r.addColorStop(1, U.rgba(accent, 0));
    g.fillStyle = r;
    g.fillRect(0, 0, w, h);
    var v = g.createRadialGradient(w / 2, h * 0.45, h * 0.3, w / 2, h * 0.45, w * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, "rgba(0,0,0,0.45)");
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
  }
  function build(w, h) {
    var rnd = U.rng(7);
    // Two ribbons; each is a bundle of threads that fan out and pinch together.
    threads = [];
    var ribbons = [
      { y: 0.36, a1: 0.085, k1: 0.9, s1: 0.06, a2: 0.035, k2: 2.1, s2: -0.045, spread: 0.075, n: 16, alpha: 0.55 },
      { y: 0.22, a1: 0.06, k1: 1.3, s1: -0.04, a2: 0.025, k2: 2.7, s2: 0.05, spread: 0.05, n: 9, alpha: 0.3 },
    ];
    for (var r = 0; r < ribbons.length; r++) {
      var rb = ribbons[r];
      for (var i = 0; i < rb.n; i++) {
        threads.push({
          rb: rb, off: (i / (rb.n - 1) - 0.5) * 2, k3: 1 + rnd() * 0.6, p3: rnd() * 6.28,
          hue: rnd(), alpha: rb.alpha * (0.45 + rnd() * 0.55), width: 0.7 + rnd() * 0.9,
          pulse: 0.1 + rnd() * 0.15, pp: rnd() * 6.28,
        });
      }
    }
    motes = [];
    for (var j = 0; j < 60; j++) {
      motes.push({ x: rnd(), y: 0.08 + rnd() * 0.6, v: 0.002 + rnd() * 0.005, r: 0.7 + rnd() * 1.4, p: rnd() * 6.28, a: 0.25 + rnd() * 0.45 });
    }
    paint(w, h);
  }
  function threadPath(ctx, th, t, w, h) {
    var rb = th.rb, n = 90, px = 0, py = 0;
    ctx.beginPath();
    for (var i = 0; i <= n; i++) {
      var u = i / n;
      var y = rb.y +
        rb.a1 * Math.sin(u * rb.k1 * 6.28 + t * rb.s1) +
        rb.a2 * Math.sin(u * rb.k2 * 6.28 + t * rb.s2 + 1.7) +
        th.off * rb.spread * (0.15 + 0.85 * Math.pow(0.5 + 0.5 * Math.sin(u * th.k3 * 6.28 + t * 0.05 + th.p3 * 0.15), 2));
      var x = u * w;
      y *= h;
      if (!i) ctx.moveTo(x, y);
      else ctx.quadraticCurveTo(px, py, (px + x) / 2, (py + y) / 2);
      px = x;
      py = y;
    }
    ctx.lineTo(px, py);
  }

  ForgeLive.scene("forge-flow", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 24,
    res: 0.75,
    start: function (ctx, w, h, o) {
      colours(o);
      build(w, h);
    },
    resize: function (ctx, w, h) {
      paint(w, h);
    },
    update: function (o) {
      colours(o);
      paint(bg.width, bg.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(bg, 0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      ctx.lineCap = "round";
      var white = [235, 242, 255];
      for (var i = 0; i < threads.length; i++) {
        var th = threads[i];
        var col = U.mix(accent, th.hue > 0.6 ? white : U.mix(accent, [150, 110, 255], 0.5), th.hue * 0.35);
        var a = th.alpha * (0.75 + 0.25 * Math.sin(t * th.pulse + th.pp));
        var fade = ctx.createLinearGradient(0, 0, w, 0);
        fade.addColorStop(0, U.rgba(col, 0));
        fade.addColorStop(0.3, U.rgba(col, a));
        fade.addColorStop(0.75, U.rgba(col, a * 0.8));
        fade.addColorStop(1, U.rgba(col, 0));
        threadPath(ctx, th, t, w, h);
        ctx.strokeStyle = fade;
        ctx.globalAlpha = 0.16;
        ctx.lineWidth = th.width * 10;
        ctx.stroke();
        ctx.globalAlpha = 0.85;
        ctx.lineWidth = th.width;
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      for (var j = 0; j < motes.length; j++) {
        var m = motes[j];
        var x = ((m.x + t * m.v) % 1) * w;
        var y = (m.y + 0.02 * Math.sin(t * 0.3 + m.p)) * h;
        ctx.fillStyle = U.rgba(accent, m.a * (0.6 + 0.4 * Math.sin(t * 0.8 + m.p)));
        ctx.beginPath();
        ctx.arc(x, y, m.r, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";
    },
    stop: function () {
      bg = null;
    },
  });
})();
