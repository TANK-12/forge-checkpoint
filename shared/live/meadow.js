/* live: Meadow | A sunny meadow, grass swaying in waves of wind, drifting seeds and pollen (dusk in dark mode) */
(function () {
  var U = ForgeLive.util;
  var bg, seedSpr, glowSpr, rows, seeds, accent, light, W, H;
  var TOP = 0.63;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
  }
  function radial(size, col, soft) {
    var c = U.layer(size, size), g = c.getContext("2d"), r = size / 2;
    var gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, U.rgba(col, 1));
    gr.addColorStop(soft, U.rgba(col, 0.4));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, size, size);
    return c;
  }
  function ridge(g, w, h, base, amp, seed, col) {
    var r = U.rng(seed), p0 = r() * 6, p1 = r() * 6;
    g.fillStyle = U.rgba(col);
    g.beginPath();
    g.moveTo(0, h);
    var ys = [];
    for (var x = 0; x <= w + 4; x += 4) {
      var u = x / w, y = h * (base - amp * (0.6 * Math.sin(u * 3 + p0) + 0.4 * Math.sin(u * 7 + p1)));
      ys.push(y);
      g.lineTo(x, y);
    }
    g.lineTo(w, h);
    g.closePath();
    g.fill();
    return ys;
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h * TOP);
    if (light) {
      lin.addColorStop(0, U.rgba(U.mix([142, 192, 236], accent, 0.12)));
      lin.addColorStop(0.6, "rgb(212,230,242)");
      lin.addColorStop(1, "rgb(250,242,222)");
    } else {
      lin.addColorStop(0, U.rgba(U.mix([32, 30, 72], accent, 0.08)));
      lin.addColorStop(0.55, "rgb(116,78,118)");
      lin.addColorStop(1, "rgb(244,160,112)");
    }
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var sx = w * (light ? 0.78 : 0.7), sy = h * (light ? 0.16 : 0.55);
    var s = g.createRadialGradient(sx, sy, 0, sx, sy, h * 0.7);
    s.addColorStop(0, light ? "rgba(255,250,225,0.85)" : "rgba(255,210,150,0.8)");
    s.addColorStop(0.2, light ? "rgba(255,245,210,0.3)" : "rgba(255,150,90,0.3)");
    s.addColorStop(1, "rgba(255,220,170,0)");
    g.fillStyle = s;
    g.fillRect(0, 0, w, h);
    var rnd = U.rng(901);
    for (var c = 0; c < 7; c++) {
      var cx = rnd() * w, cy = h * (0.08 + rnd() * 0.3), cw = w * (0.1 + rnd() * 0.15);
      g.save();
      g.translate(cx, cy);
      g.scale(1, 0.18);
      var cg = g.createRadialGradient(0, 0, 0, 0, 0, cw);
      cg.addColorStop(0, light ? "rgba(255,255,255,0.45)" : "rgba(255,180,160,0.25)");
      cg.addColorStop(1, "rgba(255,255,255,0)");
      g.fillStyle = cg;
      g.fillRect(-cw, -cw, cw * 2, cw * 2);
      g.restore();
    }
    var far = ridge(g, w, h, TOP - 0.03, 0.03, 907, light ? [168, 196, 176] : [104, 76, 108]);
    for (var tr = 0; tr < 14; tr++) {
      var tx = rnd() * w, ty = far[Math.min(far.length - 1, Math.floor(tx / 4))], tr2 = h * (0.01 + rnd() * 0.018);
      g.fillStyle = light ? "rgb(140,174,146)" : "rgb(82,60,90)";
      g.beginPath();
      g.arc(tx, ty - tr2 * 0.6, tr2, 0, 6.2832);
      g.arc(tx + tr2 * 0.8, ty - tr2 * 0.3, tr2 * 0.7, 0, 6.2832);
      g.fill();
    }
    ridge(g, w, h, TOP, 0.015, 911, light ? [146, 186, 120] : [70, 58, 78]);
    var fg = g.createLinearGradient(0, h * TOP, 0, h);
    fg.addColorStop(0, light ? "rgb(140,182,96)" : "rgb(60,56,66)");
    fg.addColorStop(1, light ? "rgb(66,116,48)" : "rgb(18,22,26)");
    g.fillStyle = fg;
    g.fillRect(0, h * (TOP + 0.01), w, h);
    seedSpr = U.layer(48, 48);
    var d = seedSpr.getContext("2d");
    d.strokeStyle = light ? "rgba(255,255,255,0.9)" : "rgba(255,236,210,0.85)";
    d.lineWidth = 1;
    for (var k = 0; k < 16; k++) {
      var a = Math.PI + (k / 15) * Math.PI;
      d.beginPath();
      d.moveTo(24, 26);
      d.lineTo(24 + Math.cos(a) * 18, 26 + Math.sin(a) * 18);
      d.stroke();
    }
    d.beginPath();
    d.moveTo(24, 26);
    d.lineTo(24, 44);
    d.stroke();
    glowSpr = radial(32, light ? [255, 252, 230] : [255, 214, 150], 0.3);
  }
  function build(w, h, o) {
    var rnd = U.rng(919);
    var R = o.lite ? 6 : 9;
    var flowerCols = light ? [[255, 255, 255], [255, 220, 90], U.mix(accent, [255, 255, 255], 0.3), [240, 150, 180]] : [[230, 220, 230], [230, 180, 90], U.mix(accent, [200, 200, 200], 0.3), [200, 120, 150]];
    rows = [];
    for (var j = 0; j < R; j++) {
      var z = j / (R - 1);
      var spacing = w * (0.0035 + 0.011 * z) * (o.lite ? 1.4 : 1);
      var n = Math.ceil(w / spacing) + 4, bl = [];
      for (var i = 0; i < n; i++) {
        bl.push({ x: ((i - 2 + rnd()) * spacing) / w, hf: 0.6 + rnd() * 0.6, lean: (rnd() - 0.5) * 0.4, f: rnd() < 0.05 + z * 0.06 ? 1 + Math.floor(rnd() * 4) : 0 });
      }
      var far = light ? [150, 190, 110] : [92, 86, 96], near = light ? [56, 112, 40] : [22, 32, 32];
      var col = U.mix(far, near, z);
      rows.push({ y: TOP + 0.015 + Math.pow(z, 1.4) * (1.03 - TOP), bh: 0.025 + 0.17 * Math.pow(z, 1.6), lw: 0.8 + z * 2.4, z: z, bl: bl, c0: col, c1: U.mix(col, light ? [200, 220, 120] : [140, 100, 90], 0.25), fc: flowerCols });
    }
    seeds = [];
    for (var s = 0; s < (o.lite ? 14 : 28); s++) {
      seeds.push({ x: rnd(), y: 0.2 + rnd() * 0.6, v: 0.01 + rnd() * 0.02, a: 0.03 + rnd() * 0.05, f: 0.2 + rnd() * 0.3, p: rnd() * 6.28, big: rnd() < 0.35, r: 1 + rnd() * 2 });
    }
    paint(w, h);
  }
  function wind(u, t, j) {
    var wave = 0.5 + 0.5 * Math.sin(u * 5 - t * 0.8 + j * 0.35);
    return 0.5 * wave * wave + 0.12 * Math.sin(u * 17 - t * 1.6 + j) + 0.1;
  }

  ForgeLive.scene("meadow", {
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
      ctx.lineCap = "round";
      for (var j = 0; j < rows.length; j++) {
        var Rw = rows[j], by = Rw.y * h, rbh = Rw.bh * h;
        for (var pass = 0; pass < 2; pass++) {
          ctx.strokeStyle = U.rgba(pass ? Rw.c1 : Rw.c0);
          ctx.lineWidth = Rw.lw;
          ctx.beginPath();
          for (var i = pass; i < Rw.bl.length; i += 2) {
            var b = Rw.bl[i], x = b.x * w, bh = rbh * b.hf;
            var bend = b.lean + wind(b.x, t, j);
            ctx.moveTo(x, by);
            ctx.quadraticCurveTo(x + bend * bh * 0.15, by - bh * 0.6, x + bend * bh * 0.55, by - bh * (1 - 0.2 * bend * bend));
          }
          ctx.stroke();
        }
        if (Rw.z > 0.3) {
          for (var k = 0; k < Rw.bl.length; k++) {
            var B = Rw.bl[k];
            if (!B.f) continue;
            var bh2 = rbh * B.hf, bd = B.lean + wind(B.x, t, j);
            ctx.fillStyle = U.rgba(Rw.fc[B.f - 1], 0.9);
            ctx.beginPath();
            ctx.arc(B.x * w + bd * bh2 * 0.55, by - bh2 * (1 - 0.2 * bd * bd), Rw.lw * 1.2, 0, 6.2832);
            ctx.fill();
          }
        }
      }
      for (var s = 0; s < seeds.length; s++) {
        var S = seeds[s];
        var x2 = (S.x + S.v * t + 0.02 * Math.sin(t * S.f + S.p)) % 1;
        var y2 = (S.y + S.a * Math.sin(t * S.f * 0.7 + S.p * 2)) * h;
        x2 *= w;
        if (S.big) {
          var sz = h * 0.022;
          ctx.globalAlpha = 0.8;
          ctx.setTransform(1, 0, 0, 1, x2, y2);
          ctx.rotate(0.3 * Math.sin(t * S.f + S.p));
          ctx.drawImage(seedSpr, -sz / 2, -sz / 2, sz, sz);
          ctx.setTransform(1, 0, 0, 1, 0, 0);
        } else {
          ctx.globalCompositeOperation = "lighter";
          ctx.globalAlpha = 0.45 + 0.25 * Math.sin(t * 0.9 + S.p);
          ctx.drawImage(glowSpr, x2 - S.r * 3, y2 - S.r * 3, S.r * 6, S.r * 6);
          ctx.globalCompositeOperation = "source-over";
        }
      }
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = seedSpr = glowSpr = rows = seeds = null;
    },
  });
})();
