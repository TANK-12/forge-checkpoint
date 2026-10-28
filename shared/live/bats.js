/* live: Bats | Halloween night: a big moon, drifting fog, bare trees, a pumpkin glow and the odd bat */
(function () {
  var U = ForgeLive.util;
  var bg, front, fogSpr, fogs, bats, accent, W, H;

  function colours(o) {
    accent = U.hex(o.accent, "#ff9440");
  }
  function ridgeFn(seed, base, amp) {
    var r = U.rng(seed), p0 = r() * 6, p1 = r() * 6;
    return function (u) {
      return base - amp * (0.6 * Math.sin(u * 2.6 + p0) + 0.4 * Math.sin(u * 6.5 + p1));
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
  function tree(g, rnd, x, y, len, ang, depth, wd) {
    var x2 = x + Math.cos(ang) * len, y2 = y + Math.sin(ang) * len;
    g.lineWidth = wd;
    g.beginPath();
    g.moveTo(x, y);
    g.quadraticCurveTo(x + Math.cos(ang + 0.3) * len * 0.5, y + Math.sin(ang + 0.3) * len * 0.5, x2, y2);
    g.stroke();
    if (depth <= 0) return;
    var n = rnd() < 0.3 ? 3 : 2;
    for (var i = 0; i < n; i++) {
      var spread = (i - (n - 1) / 2) * (0.5 + rnd() * 0.35) + (rnd() - 0.5) * 0.3;
      tree(g, rnd, x2, y2, len * (0.62 + rnd() * 0.18), ang + spread, depth - 1, wd * 0.66);
    }
  }
  function pumpkin(g, x, y, r) {
    var gl = g.createRadialGradient(x, y, 0, x, y, r * 6);
    gl.addColorStop(0, "rgba(255,150,50,0.45)");
    gl.addColorStop(1, "rgba(255,120,30,0)");
    g.fillStyle = gl;
    g.fillRect(x - r * 6, y - r * 6, r * 12, r * 12);
    g.fillStyle = "rgb(214,96,24)";
    g.beginPath();
    g.ellipse(x, y, r * 1.25, r, 0, 0, 6.2832);
    g.fill();
    g.fillStyle = "rgb(255,214,110)";
    g.beginPath();
    g.moveTo(x - r * 0.6, y - r * 0.15);
    g.lineTo(x - r * 0.3, y - r * 0.5);
    g.lineTo(x - r * 0.15, y - r * 0.1);
    g.moveTo(x + r * 0.6, y - r * 0.15);
    g.lineTo(x + r * 0.3, y - r * 0.5);
    g.lineTo(x + r * 0.15, y - r * 0.1);
    g.fill();
    g.fillRect(x - r * 0.55, y + r * 0.25, r * 1.1, r * 0.22);
    g.fillStyle = "rgb(40,30,20)";
    g.fillRect(x - r * 0.08, y - r * 1.25, r * 0.16, r * 0.35);
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    lin.addColorStop(0, U.rgba(U.mix([10, 8, 24], accent, 0.04)));
    lin.addColorStop(0.5, "rgb(30,18,46)");
    lin.addColorStop(0.8, "rgb(66,32,46)");
    lin.addColorStop(1, "rgb(110,48,28)");
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var rnd = U.rng(1001);
    for (var i = 0; i < 110; i++) {
      g.fillStyle = "rgba(240,230,255," + (0.1 + rnd() * 0.45).toFixed(2) + ")";
      g.fillRect(rnd() * w, rnd() * h * 0.6, 1.2, 1.2);
    }
    var mx = w * 0.7, my = h * 0.3, mr = h * 0.13;
    var mg = g.createRadialGradient(mx, my, mr * 0.8, mx, my, mr * 4.5);
    mg.addColorStop(0, U.rgba(U.mix([255, 236, 200], accent, 0.12), 0.3));
    mg.addColorStop(1, "rgba(255,220,180,0)");
    g.fillStyle = mg;
    g.fillRect(0, 0, w, h);
    var md = g.createRadialGradient(mx - mr * 0.3, my - mr * 0.3, 0, mx, my, mr);
    md.addColorStop(0, "rgb(255,248,226)");
    md.addColorStop(1, "rgb(236,214,170)");
    g.fillStyle = md;
    g.beginPath();
    g.arc(mx, my, mr, 0, 6.2832);
    g.fill();
    for (var c = 0; c < 9; c++) {
      var a = rnd() * 6.28, d = rnd() * mr * 0.7, cr = mr * (0.06 + rnd() * 0.14);
      g.fillStyle = "rgba(170,140,110,0.18)";
      g.beginPath();
      g.arc(mx + Math.cos(a) * d, my + Math.sin(a) * d, cr, 0, 6.2832);
      g.fill();
    }
    // thin clouds across the moon
    for (var s = 0; s < 4; s++) {
      g.save();
      g.translate(mx + (rnd() - 0.5) * mr * 3, my + (rnd() - 0.3) * mr * 1.6);
      g.scale(1, 0.12);
      var cw = mr * (1.5 + rnd() * 1.5);
      var cg = g.createRadialGradient(0, 0, 0, 0, 0, cw);
      cg.addColorStop(0, "rgba(34,22,48,0.7)");
      cg.addColorStop(1, "rgba(34,22,48,0)");
      g.fillStyle = cg;
      g.fillRect(-cw, -cw, cw * 2, cw * 2);
      g.restore();
    }
    var pg = g.createRadialGradient(w * 0.5, h * 1.1, 0, w * 0.5, h * 1.1, h * 0.8);
    pg.addColorStop(0, "rgba(255,130,40,0.4)");
    pg.addColorStop(1, "rgba(255,110,30,0)");
    g.fillStyle = pg;
    g.fillRect(0, 0, w, h);
    var farR = ridgeFn(1009, 0.76, 0.045);
    fillRidge(g, w, h, farR, [34, 18, 36]);
    g.strokeStyle = "rgb(34,18,36)";
    g.lineCap = "round";
    var spots = [0.3, 0.46, 0.58, 0.9];
    for (var t = 0; t < spots.length; t++) tree(g, rnd, spots[t] * w, farR(spots[t]) * h + 2, h * (0.03 + rnd() * 0.02), -Math.PI / 2, 5, h * 0.006);
    front = U.layer(w, h);
    var f = front.getContext("2d");
    var nearR = ridgeFn(1013, 0.88, 0.04);
    fillRidge(f, w, h, nearR, [12, 6, 14]);
    f.strokeStyle = "rgb(12,6,14)";
    f.lineCap = "round";
    var tr = U.rng(1019);
    tree(f, tr, w * 0.09, nearR(0.09) * h + 4, h * 0.17, -Math.PI / 2 + 0.08, 8, h * 0.028);
    tree(f, tr, w * 0.95, nearR(0.95) * h + 4, h * 0.1, -Math.PI / 2 - 0.1, 7, h * 0.016);
    pumpkin(f, w * 0.79, nearR(0.79) * h + h * 0.01, h * 0.016);
    pumpkin(f, w * 0.835, nearR(0.835) * h + h * 0.015, h * 0.012);
    pumpkin(f, w * 0.2, nearR(0.2) * h + h * 0.012, h * 0.013);
    var v = f.createRadialGradient(w / 2, h * 0.5, h * 0.4, w / 2, h * 0.5, w * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, "rgba(0,0,0,0.5)");
    f.fillStyle = v;
    f.fillRect(0, 0, w, h);
    fogSpr = U.layer(512, 96);
    var fg = fogSpr.getContext("2d"), fr = U.rng(1021);
    // puffs stay inside the sprite (2.4 x rr wide), so its edges never show as hard lines
    for (var k = 0; k < 18; k++) {
      var fx = 110 + fr() * 292, fy = 48 + (fr() - 0.5) * 30, rr = 22 + fr() * 18;
      fg.save();
      fg.translate(fx, fy);
      fg.scale(2.4, 0.5);
      var gr = fg.createRadialGradient(0, 0, 0, 0, 0, rr);
      gr.addColorStop(0, "rgba(190,170,210,0.35)");
      gr.addColorStop(1, "rgba(190,170,210,0)");
      fg.fillStyle = gr;
      fg.fillRect(-rr, -rr, rr * 2, rr * 2);
      fg.restore();
    }
  }
  function build(w, h, o) {
    var rnd = U.rng(1031);
    fogs = [];
    for (var i = 0; i < (o.lite ? 4 : 7); i++) {
      fogs.push({ x: rnd(), y: 0.72 + rnd() * 0.24, s: 0.4 + rnd() * 0.4, v: 0.004 + rnd() * 0.008, a: 0.35 + rnd() * 0.35, front: i % 3 === 2 });
    }
    bats = [];
    for (var j = 0; j < (o.lite ? 3 : 5); j++) {
      var P = 11 + rnd() * 9;
      bats.push({ P: P, D: 7 + rnd() * 3, o: rnd() * P, y: 0.12 + rnd() * 0.45, s: 0.012 + rnd() * 0.022, dir: rnd() < 0.5 ? 1 : -1, fr: 9 + rnd() * 4, p: rnd() * 6.28 });
    }
    paint(w, h);
  }
  function wing(ctx, side, f) {
    var cx = 1.0 * side, cy = -0.1 - 0.6 * f, dx = 0.15 * side, dy = 0.12;
    ctx.moveTo(0.1 * side, -0.06);
    ctx.lineTo(0.5 * side, -0.2 - 0.35 * f);
    ctx.lineTo(cx, cy);
    for (var k = 1; k <= 3; k++) {
      var px = cx + (dx - cx) * (k / 3), py = cy + (dy - cy) * (k / 3);
      var qx = cx + (dx - cx) * ((k - 0.5) / 3), qy = cy + (dy - cy) * ((k - 0.5) / 3) - 0.12;
      ctx.quadraticCurveTo(qx, qy, px, py);
    }
    ctx.closePath();
  }
  function drawBat(ctx, x, y, s, f) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(s, s);
    ctx.beginPath();
    wing(ctx, 1, f);
    wing(ctx, -1, f);
    ctx.ellipse(0, 0.02, 0.12, 0.17, 0, 0, 6.2832);
    ctx.moveTo(-0.1, -0.1);
    ctx.lineTo(-0.07, -0.27);
    ctx.lineTo(-0.02, -0.12);
    ctx.moveTo(0.1, -0.1);
    ctx.lineTo(0.07, -0.27);
    ctx.lineTo(0.02, -0.12);
    ctx.fill();
    ctx.restore();
  }
  function drawFog(ctx, t, w, h, front) {
    for (var i = 0; i < fogs.length; i++) {
      var F = fogs[i];
      if (F.front !== front) continue;
      var fw = F.s * w * 2, span = 1 + F.s * 2;
      var x = ((F.x * span + F.v * t) % span) - F.s * 2;
      ctx.globalAlpha = F.a;
      ctx.drawImage(fogSpr, x * w, F.y * h - fw * 0.09, fw, fw * 0.19);
    }
    ctx.globalAlpha = 1;
  }

  ForgeLive.scene("bats", {
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
      drawFog(ctx, t, w, h, false);
      ctx.fillStyle = "rgb(10,5,12)";
      for (var i = 0; i < bats.length; i++) {
        var B = bats[i];
        var u = ((t + B.o) % B.P) / B.D;
        if (u > 1) continue;
        var x = B.dir > 0 ? -0.08 + u * 1.16 : 1.08 - u * 1.16;
        var y = B.y + 0.05 * Math.sin(u * 6 + B.p) + 0.012 * Math.sin(t * 2.5 + B.p);
        drawBat(ctx, x * w, y * h, B.s * w, Math.sin(t * B.fr + B.p));
      }
      ctx.drawImage(front, 0, 0, w, h);
      drawFog(ctx, t, w, h, true);
    },
    stop: function () {
      bg = front = fogSpr = fogs = bats = null;
    },
  });
})();
