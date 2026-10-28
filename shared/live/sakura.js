/* live: Sakura | Cherry blossom petals drifting over a dusk sky and distant hills */
(function () {
  var U = ForgeLive.util;
  var bg, petalSprites, petals, accent, light;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
  }
  function hills(g, w, h, base, amp, seed, col) {
    var rnd = U.rng(seed);
    var k1 = 1 + rnd() * 1.5, k2 = 3 + rnd() * 3, p1 = rnd() * 6.28, p2 = rnd() * 6.28;
    g.beginPath();
    g.moveTo(0, h);
    for (var i = 0; i <= 64; i++) {
      var u = i / 64;
      var y = base - amp * (0.6 * Math.sin(u * k1 * 3.14 + p1) + 0.4 * Math.sin(u * k2 * 3.14 + p2));
      g.lineTo(u * w, y * h);
    }
    g.lineTo(w, h);
    g.closePath();
    g.fillStyle = col;
    g.fill();
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var top = light ? U.mix([150, 175, 215], accent, 0.2) : U.mix([18, 16, 42], accent, 0.18);
    var mid = light ? [236, 200, 214] : U.mix([108, 62, 112], accent, 0.15);
    var low = light ? [252, 226, 206] : [236, 146, 118];
    var sky = g.createLinearGradient(0, 0, 0, h * 0.72);
    sky.addColorStop(0, U.rgba(top));
    sky.addColorStop(0.55, U.rgba(mid));
    sky.addColorStop(1, U.rgba(low));
    g.fillStyle = sky;
    g.fillRect(0, 0, w, h);
    // low sun glow behind the hills
    var sun = g.createRadialGradient(w * 0.3, h * 0.66, 0, w * 0.3, h * 0.66, w * 0.45);
    sun.addColorStop(0, light ? "rgba(255,240,220,0.7)" : "rgba(255,196,150,0.55)");
    sun.addColorStop(1, "rgba(255,196,150,0)");
    g.fillStyle = sun;
    g.fillRect(0, 0, w, h);
    if (!light) {
      var rnd = U.rng(3);
      for (var s = 0; s < 120; s++) {
        var sy = rnd() * h * 0.35;
        g.fillStyle = "rgba(255,240,250," + (0.15 + rnd() * 0.5) * (1 - sy / (h * 0.35)) + ")";
        g.fillRect(rnd() * w, sy, 1.2, 1.2);
      }
    }
    // three hill ranges, hazier with distance
    var far = light ? U.mix([170, 150, 190], accent, 0.15) : U.mix([92, 60, 104], accent, 0.12);
    var near = light ? [96, 80, 112] : [22, 16, 34];
    hills(g, w, h, 0.66, 0.05, 11, U.rgba(U.mix(far, low, 0.35)));
    hills(g, w, h, 0.74, 0.06, 23, U.rgba(U.mix(far, near, 0.45)));
    hills(g, w, h, 0.86, 0.07, 37, U.rgba(near));
    // mist lying in the valley
    var mist = g.createLinearGradient(0, h * 0.62, 0, h * 0.8);
    mist.addColorStop(0, "rgba(255,220,220,0)");
    mist.addColorStop(0.5, light ? "rgba(255,240,240,0.35)" : "rgba(255,200,200,0.12)");
    mist.addColorStop(1, "rgba(255,220,220,0)");
    g.fillStyle = mist;
    g.fillRect(0, h * 0.6, w, h * 0.22);
  }
  function sprite(col) {
    var c = U.layer(32, 32), g = c.getContext("2d");
    g.translate(16, 16);
    var gr = g.createLinearGradient(-12, 0, 12, 0);
    gr.addColorStop(0, U.rgba(U.mix(col, [255, 255, 255], 0.55)));
    gr.addColorStop(1, U.rgba(col));
    g.fillStyle = gr;
    g.beginPath();
    // a petal: rounded with a small notch at the tip
    g.moveTo(-12, 0);
    g.bezierCurveTo(-8, -9, 6, -9, 12, -2);
    g.lineTo(9, 0);
    g.lineTo(12, 2);
    g.bezierCurveTo(6, 9, -8, 9, -12, 0);
    g.fill();
    return c;
  }
  function build(w, h, o) {
    var rnd = U.rng(19);
    var pinks = [[255, 183, 205], [250, 160, 190], [255, 208, 222], U.mix([255, 170, 200], accent, 0.3)];
    petalSprites = pinks.map(sprite);
    petals = [];
    var n = o.lite ? 45 : 90;
    for (var i = 0; i < n; i++) {
      var d = 0.35 + rnd() * 0.65; // depth: near petals are bigger and faster
      petals.push({
        x: rnd(), y: rnd(), d: d, v: 0.018 + d * 0.035, drift: 0.01 + rnd() * 0.02,
        sw: 0.01 + rnd() * 0.025, sf: 0.3 + rnd() * 0.5, sp: rnd() * 6.28,
        rot: rnd() * 6.28, spin: (rnd() - 0.5) * 1.6, flip: 0.6 + rnd() * 1.4,
        size: (7 + rnd() * 8) * d, spr: Math.floor(rnd() * pinks.length), a: 0.55 + d * 0.45,
      });
    }
    petals.sort(function (a, b) { return a.d - b.d; });
    paint(w, h);
  }

  ForgeLive.scene("sakura", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 24,
    res: 0.75,
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
      var pinks = [[255, 183, 205], [250, 160, 190], [255, 208, 222], U.mix([255, 170, 200], accent, 0.3)];
      petalSprites = pinks.map(sprite);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.setTransform(ctx.canvas.width / w, 0, 0, ctx.canvas.height / h, 0, 0);
      ctx.drawImage(bg, 0, 0, w, h);
      var sx = ctx.canvas.width / w, sy = ctx.canvas.height / h;
      for (var i = 0; i < petals.length; i++) {
        var p = petals[i];
        var y = ((p.y + t * p.v) % 1.1) - 0.05;
        var x = (((p.x + t * p.drift + p.sw * Math.sin(t * p.sf + p.sp)) % 1) + 1) % 1;
        x = x * (w + 40) - 20;
        y *= h;
        var r = p.rot + t * p.spin;
        var f = Math.cos(t * p.flip + p.sp); // tumbling: the petal turns edge-on
        var s = p.size / 12;
        var c = Math.cos(r), sn = Math.sin(r);
        ctx.globalAlpha = p.a * (0.55 + 0.45 * Math.abs(f));
        ctx.setTransform(c * s * f * sx, sn * s * f * sy, -sn * s * sx, c * s * sy, x * sx, y * sy);
        ctx.drawImage(petalSprites[p.spr], -16, -16);
      }
      ctx.globalAlpha = 1;
      ctx.setTransform(sx, 0, 0, sy, 0, 0);
    },
    stop: function () {
      bg = petalSprites = petals = null;
    },
  });
})();
