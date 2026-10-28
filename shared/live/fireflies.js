/* live: Fireflies | Layered forest silhouettes at night with fireflies drifting between the trees */
(function () {
  var U = ForgeLive.util;
  var bg, fg, glowSpr, flies, accent;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function treeline(g, w, h, baseY, scale, seed, col, pines) {
    var rnd = U.rng(seed);
    g.fillStyle = col;
    g.fillRect(0, baseY, w, h - baseY);
    var x = -20;
    while (x < w + 20) {
      var th = (0.6 + rnd() * 0.8) * scale;
      var tw = th * (0.28 + rnd() * 0.12);
      if (pines || rnd() < 0.75) {
        // a pine: stacked jagged tiers
        g.beginPath();
        g.moveTo(x, baseY - th);
        var tiers = 5;
        for (var i = 1; i <= tiers; i++) {
          var yy = baseY - th + (th * i) / tiers;
          var half = (tw * i) / tiers;
          g.lineTo(x + half, yy);
          g.lineTo(x + half * 0.45, yy - (th / tiers) * 0.15);
        }
        g.lineTo(x + tw * 0.1, baseY + 2);
        g.lineTo(x - tw * 0.1, baseY + 2);
        for (var j = tiers; j >= 1; j--) {
          var y2 = baseY - th + (th * j) / tiers;
          var h2 = (tw * j) / tiers;
          g.lineTo(x - h2 * 0.45, y2 - (th / tiers) * 0.15);
          g.lineTo(x - h2, y2);
        }
        g.closePath();
        g.fill();
      } else {
        // a round broadleaf crown
        var r = tw * 0.9;
        g.beginPath();
        g.arc(x, baseY - th + r, r, 0, 6.2832);
        g.arc(x - r * 0.6, baseY - th + r * 1.5, r * 0.8, 0, 6.2832);
        g.arc(x + r * 0.6, baseY - th + r * 1.4, r * 0.85, 0, 6.2832);
        g.fill();
        g.fillRect(x - r * 0.12, baseY - th + r * 1.8, r * 0.24, th);
      }
      x += tw * (0.7 + rnd() * 0.9);
    }
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var sky = g.createLinearGradient(0, 0, 0, h);
    sky.addColorStop(0, U.rgba(U.mix([6, 12, 22], accent, 0.12)));
    sky.addColorStop(0.6, U.rgba(U.mix([18, 36, 48], accent, 0.12)));
    sky.addColorStop(1, "rgb(10,20,24)");
    g.fillStyle = sky;
    g.fillRect(0, 0, w, h);
    var moon = g.createRadialGradient(w * 0.68, h * 0.2, 0, w * 0.68, h * 0.2, h * 0.5);
    moon.addColorStop(0, "rgba(210,230,240,0.22)");
    moon.addColorStop(1, "rgba(210,230,240,0)");
    g.fillStyle = moon;
    g.fillRect(0, 0, w, h);
    g.fillStyle = "rgba(235,245,250,0.9)";
    g.beginPath();
    g.arc(w * 0.68, h * 0.2, Math.min(w, h) * 0.035, 0, 6.2832);
    g.fill();
    var rnd = U.rng(61);
    for (var s = 0; s < 90; s++) {
      g.fillStyle = "rgba(220,235,255," + (0.15 + rnd() * 0.45) + ")";
      g.fillRect(rnd() * w, rnd() * h * 0.4, 1.1, 1.1);
    }
    var far = U.mix([30, 52, 62], accent, 0.1);
    var ranks = [
      { y: 0.6, s: 0.22, c: U.mix(far, [60, 80, 90], 0.3) },
      { y: 0.68, s: 0.3, c: U.mix(far, [8, 14, 18], 0.35) },
      { y: 0.78, s: 0.42, c: U.mix(far, [4, 8, 10], 0.7) },
    ];
    for (var i = 0; i < ranks.length; i++) {
      var rk = ranks[i];
      treeline(g, w, h, h * rk.y, h * rk.s, 100 + i, U.rgba(rk.c));
      // mist lying in front of each rank
      var m = g.createLinearGradient(0, h * (rk.y - 0.08), 0, h * (rk.y + 0.04));
      m.addColorStop(0, "rgba(160,200,210,0)");
      m.addColorStop(0.7, "rgba(160,200,210," + (0.1 - i * 0.025) + ")");
      m.addColorStop(1, "rgba(160,200,210,0)");
      g.fillStyle = m;
      g.fillRect(0, h * (rk.y - 0.08), w, h * 0.12);
    }
    // the nearest trees only frame the edges, so the clearing stays open
    fg = U.layer(w, h);
    var fgc = fg.getContext("2d");
    fgc.fillStyle = "rgb(2,4,6)";
    fgc.beginPath();
    fgc.moveTo(0, h);
    for (var gx = 0; gx <= 32; gx++) fgc.lineTo((gx / 32) * w, h * (0.94 + 0.02 * Math.sin(gx * 1.7)));
    fgc.lineTo(w, h);
    fgc.fill();
    fgc.save();
    fgc.beginPath();
    fgc.rect(0, 0, w * 0.16, h);
    fgc.rect(w * 0.86, 0, w * 0.14, h);
    fgc.clip();
    treeline(fgc, w, h, h * 0.97, h * 0.6, 200, "rgb(2,4,6)", true);
    fgc.restore();
    var col = U.mix([220, 255, 120], accent, 0.2);
    glowSpr = U.layer(48, 48);
    var gg = glowSpr.getContext("2d");
    var gr = gg.createRadialGradient(24, 24, 0, 24, 24, 24);
    gr.addColorStop(0, "rgba(255,255,230,1)");
    gr.addColorStop(0.12, U.rgba(col, 0.9));
    gr.addColorStop(0.4, U.rgba(col, 0.25));
    gr.addColorStop(1, U.rgba(col, 0));
    gg.fillStyle = gr;
    gg.fillRect(0, 0, 48, 48);
  }
  function build(w, h, o) {
    var rnd = U.rng(67);
    flies = [];
    var n = o.lite ? 28 : 56;
    for (var i = 0; i < n; i++) {
      var near = i % 3 === 0;
      flies.push({
        x: rnd(), y: 0.45 + rnd() * 0.5, near: near, s: near ? 14 + rnd() * 8 : 6 + rnd() * 6,
        ax: 0.02 + rnd() * 0.05, ay: 0.01 + rnd() * 0.03, fx: 0.05 + rnd() * 0.12, fy: 0.07 + rnd() * 0.15,
        px: rnd() * 6.28, py: rnd() * 6.28, per: 3 + rnd() * 5, ph: rnd() * 8, on: 0.3 + rnd() * 0.3,
      });
    }
    paint(w, h);
  }
  function drawFlies(ctx, t, w, h, near) {
    for (var i = 0; i < flies.length; i++) {
      var f = flies[i];
      if (f.near !== near) continue;
      // blink: a soft rise and fall once per period
      var u = ((t + f.ph) % f.per) / f.per;
      var b = u < f.on ? Math.sin((u / f.on) * Math.PI) : 0;
      var a = 0.08 + 0.92 * b;
      var x = (f.x + f.ax * Math.sin(t * f.fx + f.px) + 0.5 * f.ax * Math.sin(t * f.fx * 2.3 + f.py)) * w;
      var y = (f.y + f.ay * Math.sin(t * f.fy + f.py)) * h;
      ctx.globalAlpha = a;
      ctx.drawImage(glowSpr, x - f.s, y - f.s, f.s * 2, f.s * 2);
    }
  }

  ForgeLive.scene("fireflies", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 24,
    res: 0.6,
    start: function (ctx, w, h, o) {
      colours(o);
      build(w, h, o);
    },
    resize: function (ctx, w, h) {
      paint(w, h);
    },
    update: function (o) {
      colours(o);
      paint(bg.width, bg.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(bg, 0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      drawFlies(ctx, t, w, h, false);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(fg, 0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      drawFlies(ctx, t, w, h, true);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = fg = glowSpr = flies = null;
    },
  });
})();
