/* live: Starfield | Deep space: stars drifting in slow parallax past a faint nebula, the odd shooting star */
(function () {
  var U = ForgeLive.util;
  var bg, glow, layers, accent, W, H;
  var STAR_COLS = [[255, 255, 255], [200, 220, 255], [255, 236, 200], [220, 210, 255]];

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function radial(size, col, soft) {
    var c = U.layer(size, size), g = c.getContext("2d"), r = size / 2;
    var gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, U.rgba(col, 1));
    gr.addColorStop(soft, U.rgba(col, 0.25));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, size, size);
    return c;
  }
  function blob(g, x, y, r, col, a) {
    var gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, U.rgba(col, a));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var base = g.createRadialGradient(w * 0.5, h * 0.45, 0, w * 0.5, h * 0.45, w * 0.7);
    base.addColorStop(0, U.rgba(U.mix([14, 16, 34], accent, 0.06)));
    base.addColorStop(1, "rgb(3,4,10)");
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    // a nebula along a soft diagonal band, then darker dust lanes through it
    var rnd = U.rng(503);
    var tints = [accent, [130, 70, 190], [40, 120, 170], U.mix(accent, [255, 120, 160], 0.5)];
    g.globalCompositeOperation = "lighter";
    for (var i = 0; i < 70; i++) {
      var u = rnd();
      var x = (0.05 + u * 0.9) * w + (rnd() - 0.5) * w * 0.15;
      var y = (0.85 - u * 0.65 + 0.08 * Math.sin(u * 6)) * h + (rnd() - 0.5) * h * 0.2;
      blob(g, x, y, w * (0.04 + rnd() * 0.12), tints[i % tints.length], 0.025 + rnd() * 0.04);
    }
    g.globalCompositeOperation = "source-over";
    for (var j = 0; j < 30; j++) {
      var v = rnd();
      blob(g, (0.1 + v * 0.8) * w, (0.8 - v * 0.6) * h + (rnd() - 0.5) * h * 0.12, w * (0.02 + rnd() * 0.05), [3, 4, 10], 0.25);
    }
    for (var k = 0; k < 900; k++) {
      g.fillStyle = U.rgba(STAR_COLS[k % 4], 0.08 + rnd() * 0.3);
      g.fillRect(rnd() * w, rnd() * h, 1, 1);
    }
    var vg = g.createRadialGradient(w / 2, h / 2, h * 0.4, w / 2, h / 2, w * 0.75);
    vg.addColorStop(0, "rgba(0,0,0,0)");
    vg.addColorStop(1, "rgba(0,0,0,0.45)");
    g.fillStyle = vg;
    g.fillRect(0, 0, w, h);
    glow = radial(32, [255, 255, 255], 0.15);
  }
  function build(w, h, o) {
    var rnd = U.rng(509);
    var spec = [
      { n: o.lite ? 80 : 170, v: 0.003, r: [0.6, 1.1], g: 0 },
      { n: o.lite ? 35 : 70, v: 0.008, r: [1, 1.7], g: 0.25 },
      { n: o.lite ? 10 : 20, v: 0.02, r: [1.6, 2.6], g: 0.5 },
    ];
    layers = spec.map(function (s) {
      var st = [];
      for (var i = 0; i < s.n; i++) {
        st.push({
          x: rnd(), y: rnd(), r: s.r[0] + rnd() * (s.r[1] - s.r[0]), a: 0.45 + rnd() * 0.55,
          tw: 0.5 + rnd() * 2, p: rnd() * 6.28, c: Math.floor(rnd() * 4),
        });
      }
      return { v: s.v, g: s.g, st: st };
    });
    paint(w, h);
  }
  // shooting star k starts at k*9 + 2.6 s and lasts 1.2 s; its path comes from its own seed
  function meteor(ctx, t, w, h) {
    var k = Math.floor((t - 2.6) / 9);
    var u = (t - 2.6 - k * 9) / 1.2;
    if (k < 0 || u > 1) return;
    var r = U.rng(9001 + k * 131);
    var x0 = (0.35 + r() * 0.6) * w, y0 = (0.05 + r() * 0.3) * h;
    var ang = 2.6 + r() * 0.3, len = w * (0.25 + r() * 0.15);
    var hx = x0 + Math.cos(ang) * len * u, hy = y0 + Math.sin(ang) * len * u;
    var tail = w * 0.08 * Math.min(1, u * 4);
    var tx = hx - Math.cos(ang) * tail, ty = hy - Math.sin(ang) * tail;
    var a = Math.sin(u * Math.PI);
    var gr = ctx.createLinearGradient(tx, ty, hx, hy);
    gr.addColorStop(0, "rgba(255,255,255,0)");
    gr.addColorStop(1, U.rgba(U.mix([255, 255, 255], accent, 0.2), 0.85 * a));
    ctx.strokeStyle = gr;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(tx, ty);
    ctx.lineTo(hx, hy);
    ctx.stroke();
    ctx.globalAlpha = a;
    ctx.drawImage(glow, hx - 6, hy - 6, 12, 12);
    ctx.globalAlpha = 1;
  }

  ForgeLive.scene("starfield", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 24,
    res: 0.65,
    start: function (ctx, w, h, o) {
      colours(o);
      build(w, h, o);
    },
    resize: function (ctx, w, h) {
      paint(w, h);
    },
    update: function (o) {
      colours(o);
      paint(W, H);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      for (var l = 0; l < layers.length; l++) {
        var L = layers[l];
        for (var i = 0; i < L.st.length; i++) {
          var s = L.st[i];
          var x = (s.x - L.v * t) % 1;
          if (x < 0) x += 1;
          x *= w;
          var y = s.y * h;
          var a = s.a * (0.7 + 0.3 * Math.sin(t * s.tw + s.p));
          if (L.g) {
            ctx.globalAlpha = a * L.g;
            ctx.drawImage(glow, x - s.r * 4, y - s.r * 4, s.r * 8, s.r * 8);
          }
          ctx.globalAlpha = a;
          ctx.fillStyle = U.rgba(STAR_COLS[s.c]);
          ctx.fillRect(x - s.r / 2, y - s.r / 2, s.r, s.r);
        }
      }
      ctx.globalAlpha = 1;
      meteor(ctx, t, w, h);
      ctx.globalCompositeOperation = "source-over";
    },
    stop: function () {
      bg = glow = layers = null;
    },
  });
})();
