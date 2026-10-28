/* live: Snow | Soft snowfall at several depths over pines and hills on a winter night (a pale morning in light mode) */
(function () {
  var U = ForgeLive.util;
  var bg, flakeSpr, layers, accent, light, W, H;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
  }
  function radial(size, col, soft) {
    var c = U.layer(size, size), g = c.getContext("2d"), r = size / 2;
    var gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, U.rgba(col, 1));
    gr.addColorStop(soft, U.rgba(col, 0.6));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, size, size);
    return c;
  }
  function ridge(seed, base, amp, rough) {
    var r = U.rng(seed), p0 = r() * 6.28, p1 = r() * 6.28, p2 = r() * 6.28;
    return function (u) {
      return base - amp * (0.55 * Math.sin(u * 3.1 + p0) + 0.3 * Math.sin(u * 7.3 + p1) + rough * 0.15 * Math.sin(u * 23 + p2));
    };
  }
  function fillRidge(g, w, h, fy, col) {
    g.fillStyle = U.rgba(col);
    g.beginPath();
    g.moveTo(0, h);
    for (var x = 0; x <= w + 4; x += 4) g.lineTo(x, fy(x / w) * h);
    g.lineTo(w, h);
    g.closePath();
    g.fill();
  }
  function pine(g, x, y, ht, col, snowCol) {
    g.fillStyle = U.rgba(col);
    g.fillRect(x - ht * 0.025, y - ht * 0.08, ht * 0.05, ht * 0.1);
    for (var i = 0; i < 4; i++) {
      var ty = y - ht + i * ht * 0.22, by = ty + ht * 0.34, hw = ht * 0.42 * (0.35 + i * 0.22);
      g.fillStyle = U.rgba(col);
      g.beginPath();
      g.moveTo(x, ty);
      g.lineTo(x + hw, by);
      g.lineTo(x, by - ht * 0.04);
      g.lineTo(x - hw, by);
      g.closePath();
      g.fill();
      // a little snow resting on each tier
      g.fillStyle = U.rgba(snowCol, 0.55);
      g.beginPath();
      g.moveTo(x, ty);
      g.lineTo(x + hw * 0.4, ty + ht * 0.13);
      g.lineTo(x - hw * 0.15, ty + ht * 0.1);
      g.lineTo(x - hw * 0.45, ty + ht * 0.14);
      g.closePath();
      g.fill();
    }
  }
  function mist(g, w, h, y, col, a) {
    var m = g.createLinearGradient(0, (y - 0.08) * h, 0, (y + 0.04) * h);
    m.addColorStop(0, U.rgba(col, 0));
    m.addColorStop(0.7, U.rgba(col, a));
    m.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = m;
    g.fillRect(0, (y - 0.08) * h, w, 0.12 * h);
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var top = light ? [164, 186, 214] : U.mix([6, 10, 24], accent, 0.05);
    var mid = light ? [204, 218, 234] : U.mix([16, 28, 54], accent, 0.08);
    var hor = light ? [244, 234, 228] : U.mix([40, 58, 92], accent, 0.12);
    var lin = g.createLinearGradient(0, 0, 0, h * 0.75);
    lin.addColorStop(0, U.rgba(top));
    lin.addColorStop(0.55, U.rgba(mid));
    lin.addColorStop(1, U.rgba(hor));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var rnd = U.rng(211);
    if (light) {
      var s = g.createRadialGradient(w * 0.3, h * 0.6, 0, w * 0.3, h * 0.6, h * 0.7);
      s.addColorStop(0, "rgba(255,238,214,0.6)");
      s.addColorStop(1, "rgba(255,238,214,0)");
      g.fillStyle = s;
      g.fillRect(0, 0, w, h);
    } else {
      for (var i = 0; i < 170; i++) {
        g.fillStyle = "rgba(220,230,255," + (0.15 + rnd() * 0.5).toFixed(2) + ")";
        var r = 0.5 + rnd() * 1.1;
        g.fillRect(rnd() * w, rnd() * h * 0.55, r, r);
      }
      var mx = w * 0.78, my = h * 0.2;
      var mg = g.createRadialGradient(mx, my, 0, mx, my, h * 0.4);
      mg.addColorStop(0, "rgba(210,225,255,0.22)");
      mg.addColorStop(1, "rgba(210,225,255,0)");
      g.fillStyle = mg;
      g.fillRect(0, 0, w, h);
      g.fillStyle = "rgba(236,242,252,0.92)";
      g.beginPath();
      g.arc(mx, my, h * 0.035, 0, 6.2832);
      g.fill();
    }
    var snowCol = light ? [250, 252, 255] : [150, 168, 204];
    fillRidge(g, w, h, ridge(5, 0.58, 0.1, 1), light ? [190, 204, 224] : [40, 54, 88]);
    mist(g, w, h, 0.6, hor, 0.5);
    var midR = ridge(9, 0.7, 0.05, 0.6);
    fillRidge(g, w, h, midR, light ? [214, 222, 236] : [34, 46, 76]);
    for (var p = 0; p < 60; p++) {
      var u = rnd();
      pine(g, u * w, midR(u) * h + h * 0.01, h * (0.03 + rnd() * 0.03), light ? [104, 122, 148] : [14, 22, 40], snowCol);
    }
    mist(g, w, h, 0.76, hor, 0.35);
    var nearR = ridge(13, 0.86, 0.04, 0.3);
    var near = light ? [240, 244, 250] : [58, 72, 106];
    var gl = g.createLinearGradient(0, h * 0.78, 0, h);
    gl.addColorStop(0, U.rgba(near));
    gl.addColorStop(1, U.rgba(U.mix(near, light ? [200, 210, 228] : [20, 26, 44], 0.6)));
    g.fillStyle = gl;
    g.beginPath();
    g.moveTo(0, h);
    for (var x = 0; x <= w + 4; x += 4) g.lineTo(x, nearR(x / w) * h);
    g.lineTo(w, h);
    g.closePath();
    g.fill();
    // big pines gather at the edges and leave the middle open
    var spots = [0.03, 0.08, 0.12, 0.17, 0.82, 0.87, 0.91, 0.96, 0.4, 0.62];
    for (var q = 0; q < spots.length; q++) {
      var su = spots[q] + (rnd() - 0.5) * 0.02;
      var big = q < 8 ? 0.2 + rnd() * 0.14 : 0.08 + rnd() * 0.05;
      pine(g, su * w, nearR(su) * h + h * 0.02, h * big, light ? [52, 66, 88] : [6, 10, 22], snowCol);
    }
    var v = g.createRadialGradient(w / 2, h * 0.55, h * 0.3, w / 2, h * 0.55, w * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, light ? "rgba(60,80,110,0.12)" : "rgba(0,0,0,0.45)");
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
    flakeSpr = radial(32, light ? [255, 255, 255] : U.mix([255, 255, 255], accent, 0.08), 0.35);
  }
  function build(w, h, o) {
    var rnd = U.rng(223);
    var spec = [
      { n: o.lite ? 70 : 150, r: 0.0022, v: 0.028, a: 0.55, sw: 0.006 },
      { n: o.lite ? 35 : 75, r: 0.004, v: 0.05, a: 0.75, sw: 0.012 },
      { n: o.lite ? 8 : 16, r: 0.009, v: 0.085, a: 0.5, sw: 0.02 },
    ];
    layers = spec.map(function (s) {
      var f = [];
      for (var i = 0; i < s.n; i++) {
        f.push({
          x: rnd(), y: rnd() * 1.1, v: s.v * (0.8 + rnd() * 0.4), d: (rnd() - 0.35) * 0.008,
          sw: s.sw * (0.5 + rnd()), sf: 0.3 + rnd() * 0.5, sp: rnd() * 6.28, r: s.r * (0.7 + rnd() * 0.6),
        });
      }
      return { a: s.a, f: f };
    });
    paint(w, h);
  }

  ForgeLive.scene("snow", {
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
      paint(W, H);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      for (var l = 0; l < layers.length; l++) {
        var L = layers[l];
        ctx.globalAlpha = L.a;
        for (var i = 0; i < L.f.length; i++) {
          var f = L.f[i];
          var y = (((f.y + f.v * t) % 1.1) - 0.05) * h;
          var x = (f.x + f.d * t + f.sw * Math.sin(t * f.sf + f.sp)) % 1;
          if (x < 0) x += 1;
          x *= w;
          var r = f.r * h * 2;
          ctx.drawImage(flakeSpr, x - r, y - r, r * 2, r * 2);
        }
      }
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = flakeSpr = layers = null;
    },
  });
})();
