/* live: Tide | Layered moonlit waves rolling slowly, with a path of moonlight on the water */
(function () {
  var U = ForgeLive.util;
  var sky, glints, bands, accent, hz, mx;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function paint(w, h) {
    hz = h * 0.5;
    mx = w * 0.62;
    sky = U.layer(w, h);
    var g = sky.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, hz);
    lin.addColorStop(0, U.rgba(U.mix([4, 8, 22], accent, 0.12)));
    lin.addColorStop(1, U.rgba(U.mix([34, 48, 78], accent, 0.22)));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, hz + 2);
    var rnd = U.rng(71);
    for (var s = 0; s < 150; s++) {
      var y = rnd() * hz * 0.85;
      g.fillStyle = "rgba(230,238,255," + (0.15 + rnd() * 0.55) * (1 - y / hz) + ")";
      g.fillRect(rnd() * w, y, 1.2, 1.2);
    }
    var my = h * 0.2, mr = Math.min(w, h) * 0.05;
    var halo = g.createRadialGradient(mx, my, mr, mx, my, mr * 7);
    halo.addColorStop(0, "rgba(220,230,255,0.28)");
    halo.addColorStop(1, "rgba(220,230,255,0)");
    g.fillStyle = halo;
    g.fillRect(0, 0, w, hz);
    g.fillStyle = "rgb(244,246,255)";
    g.beginPath();
    g.arc(mx, my, mr, 0, 6.2832);
    g.fill();
    g.fillStyle = "rgba(180,190,215,0.35)";
    var cr = U.rng(73);
    for (var c = 0; c < 6; c++) {
      g.beginPath();
      g.arc(mx + (cr() - 0.5) * mr, my + (cr() - 0.5) * mr, mr * (0.08 + cr() * 0.15), 0, 6.2832);
      g.fill();
    }
    // the sea under everything, and a soft column of light below the moon
    var sea = g.createLinearGradient(0, hz, 0, h);
    sea.addColorStop(0, U.rgba(U.mix([30, 44, 70], accent, 0.18)));
    sea.addColorStop(1, "rgb(4,8,16)");
    g.fillStyle = sea;
    g.fillRect(0, hz, w, h - hz);
    var col = g.createLinearGradient(mx - w * 0.12, 0, mx + w * 0.12, 0);
    col.addColorStop(0, "rgba(200,215,255,0)");
    col.addColorStop(0.5, "rgba(200,215,255,0.12)");
    col.addColorStop(1, "rgba(200,215,255,0)");
    g.fillStyle = col;
    g.fillRect(mx - w * 0.12, hz, w * 0.24, h - hz);
  }
  function build(w, h, o) {
    var rnd = U.rng(79);
    bands = [];
    var n = 8;
    for (var i = 0; i < n; i++) {
      var d = i / (n - 1); // 0 far, 1 near
      bands.push({
        y: 0.5 + 0.03 + Math.pow(d, 1.6) * 0.42, a: 0.003 + d * d * 0.028,
        k: 2 + (1 - d) * 7 + rnd() * 2, v: 0.08 + d * 0.12, p: rnd() * 6.28, k2: 5 + rnd() * 8, d: d,
      });
    }
    glints = [];
    var ng = o.lite ? 80 : 160;
    for (var j = 0; j < ng; j++) {
      var u = Math.pow(rnd(), 0.8);
      glints.push({ u: u, x: (rnd() - 0.5) * 2, l: 0.6 + rnd(), f: 0.5 + rnd() * 1.5, p: rnd() * 6.28 });
    }
    paint(w, h);
  }

  ForgeLive.scene("tide", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 20,
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
      paint(sky.width, sky.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(sky, 0, 0, w, h);
      var deep = U.mix([20, 32, 56], accent, 0.15);
      for (var i = 0; i < bands.length; i++) {
        var b = bands[i];
        var steps = 48, pts = [];
        for (var s = 0; s <= steps; s++) {
          var u = s / steps;
          var y = b.y + b.a * Math.sin(u * b.k * 6.28 - t * b.v + b.p) + b.a * 0.35 * Math.sin(u * b.k2 * 6.28 + t * b.v * 0.7);
          pts.push(u * w, y * h);
        }
        ctx.beginPath();
        ctx.moveTo(0, h);
        for (var q = 0; q < pts.length; q += 2) ctx.lineTo(pts[q], pts[q + 1]);
        ctx.lineTo(w, h);
        ctx.closePath();
        var top = b.y * h - b.a * h;
        var fill = ctx.createLinearGradient(0, top, 0, top + h * 0.12);
        fill.addColorStop(0, U.rgba(U.mix(deep, [80, 100, 140], 0.35 * (1 - b.d)), 0.92));
        fill.addColorStop(1, U.rgba(U.mix(deep, [2, 4, 10], 0.4 + b.d * 0.5), 0.96));
        ctx.fillStyle = fill;
        ctx.fill();
        // moonlit crest, brightest near the moon's column
        var crest = ctx.createLinearGradient(0, 0, w, 0);
        crest.addColorStop(0, "rgba(190,205,240,0.04)");
        crest.addColorStop(mx / w, "rgba(220,230,255," + (0.25 + b.d * 0.25) + ")");
        crest.addColorStop(1, "rgba(190,205,240,0.04)");
        ctx.strokeStyle = crest;
        ctx.lineWidth = 0.6 + b.d * 1.4;
        ctx.beginPath();
        for (var r = 0; r < pts.length; r += 2) ctx[r ? "lineTo" : "moveTo"](pts[r], pts[r + 1]);
        ctx.stroke();
      }
      // glints on the moon path: short dashes that sparkle and widen nearer the shore
      ctx.globalCompositeOperation = "lighter";
      ctx.fillStyle = "rgb(235,240,255)";
      for (var j = 0; j < glints.length; j++) {
        var gl = glints[j];
        var gy = hz + 4 + gl.u * (h - hz);
        var spread = w * (0.015 + gl.u * 0.11);
        var gx = mx + gl.x * spread + Math.sin(t * 0.4 + gl.p) * spread * 0.15;
        var a = Math.max(0, Math.sin(t * gl.f + gl.p)) * (0.75 - Math.abs(gl.x) * 0.5);
        if (a < 0.03) continue;
        ctx.globalAlpha = a;
        var len = (2 + gl.u * 14) * gl.l;
        ctx.fillRect(gx - len / 2, gy, len, 1 + gl.u * 1.2);
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    },
    stop: function () {
      sky = glints = bands = null;
    },
  });
})();
