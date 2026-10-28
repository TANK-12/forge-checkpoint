/* live: Clouds | Soft clouds drifting over a pastel day sky (a warm sunset sky in dark mode) */
(function () {
  var U = ForgeLive.util;
  var bg, sprites, clouds, accent, light, W, H;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
  }
  function puff(g, x, y, r, col, a) {
    var gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, U.rgba(col, a));
    gr.addColorStop(0.6, U.rgba(col, a * 0.75));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }
  // one cloud: a dome of puffs, shaded, with a flattened base
  function cloud(seed) {
    var SW = 512, SH = 220, c = U.layer(SW, SH), g = c.getContext("2d"), rnd = U.rng(seed);
    var base = SH * 0.72, n = 16, ps = [];
    for (var i = 0; i < n; i++) {
      var u = 0.12 + rnd() * 0.76;
      var dome = Math.sin(((u - 0.12) / 0.76) * Math.PI);
      ps.push({ x: u * SW, y: base - dome * SH * (0.25 + rnd() * 0.2), r: SH * (0.12 + dome * 0.16 + rnd() * 0.06) });
    }
    var lit = light ? [255, 255, 255] : [255, 178, 150];
    var shade = light ? U.mix([196, 206, 232], accent, 0.12) : U.mix([96, 70, 124], accent, 0.1);
    var off = light ? -1 : 1; // by day lit from above, at sunset from below
    for (var a = 0; a < n; a++) puff(g, ps[a].x, ps[a].y - off * 8, ps[a].r, shade, 0.95);
    for (var b = 0; b < n; b++) puff(g, ps[b].x, ps[b].y + off * 9, ps[b].r * 0.82, lit, light ? 0.95 : 0.75);
    if (!light) for (var d = 0; d < n; d++) puff(g, ps[d].x, ps[d].y - 14, ps[d].r * 0.6, shade, 0.5);
    g.globalCompositeOperation = "destination-out";
    var cut = g.createLinearGradient(0, base, 0, base + SH * 0.18);
    cut.addColorStop(0, "rgba(0,0,0,0)");
    cut.addColorStop(1, "rgba(0,0,0,1)");
    g.fillStyle = cut;
    g.fillRect(0, base, SW, SH - base);
    return c;
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    if (light) {
      lin.addColorStop(0, U.rgba(U.mix([128, 176, 232], accent, 0.15)));
      lin.addColorStop(0.55, U.rgba(U.mix([196, 218, 242], accent, 0.08)));
      lin.addColorStop(0.85, "rgb(250,224,230)");
      lin.addColorStop(1, "rgb(255,234,216)");
    } else {
      lin.addColorStop(0, U.rgba(U.mix([26, 24, 60], accent, 0.08)));
      lin.addColorStop(0.45, "rgb(86,56,108)");
      lin.addColorStop(0.75, "rgb(214,112,104)");
      lin.addColorStop(0.9, "rgb(246,166,112)");
      lin.addColorStop(1, "rgb(255,198,140)");
    }
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var sx = light ? w * 0.2 : w * 0.62, sy = light ? h * 0.12 : h * 0.95;
    var s = g.createRadialGradient(sx, sy, 0, sx, sy, h * (light ? 0.6 : 0.8));
    s.addColorStop(0, light ? "rgba(255,255,245,0.7)" : "rgba(255,226,170,0.75)");
    s.addColorStop(0.3, light ? "rgba(255,255,240,0.2)" : "rgba(255,170,110,0.25)");
    s.addColorStop(1, "rgba(255,200,150,0)");
    g.fillStyle = s;
    g.fillRect(0, 0, w, h);
    if (!light) {
      g.fillStyle = "rgba(255,236,200,0.9)";
      g.beginPath();
      g.arc(sx, sy, h * 0.05, 0, 6.2832);
      g.fill();
    }
    // a low, hazy line of hills at the bottom
    var rnd = U.rng(707), p = rnd() * 6;
    g.fillStyle = light ? U.rgba(U.mix([176, 196, 226], accent, 0.1)) : "rgb(52,30,58)";
    g.beginPath();
    g.moveTo(0, h);
    for (var x = 0; x <= w + 4; x += 4) {
      var u = x / w;
      g.lineTo(x, h * (0.93 - 0.025 * Math.sin(u * 4 + p) - 0.012 * Math.sin(u * 11 + p * 2)));
    }
    g.lineTo(w, h);
    g.closePath();
    g.fill();
    sprites = [];
    for (var k = 0; k < 6; k++) sprites.push(cloud(711 + k * 17));
  }
  function build(w, h, o) {
    var rnd = U.rng(719);
    clouds = [];
    var n = o.lite ? 6 : 11;
    for (var i = 0; i < n; i++) {
      var z = i / (n - 1);
      clouds.push({
        x: rnd(), y: 0.62 - z * 0.5 + (rnd() - 0.5) * 0.1, s: 0.18 + z * 0.3 + rnd() * 0.08,
        v: 0.003 + z * 0.008, a: 0.55 + z * 0.4, spr: Math.floor(rnd() * 6), flip: rnd() < 0.5,
      });
    }
    paint(w, h);
  }

  ForgeLive.scene("clouds", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 20,
    res: 0.5,
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
      for (var i = 0; i < clouds.length; i++) {
        var C = clouds[i];
        var cw = C.s * w, ch = cw * (220 / 512);
        var span = 1 + C.s + 0.1;
        var x = ((C.x * span + C.v * t) % span) - C.s - 0.05;
        ctx.globalAlpha = C.a;
        if (C.flip) {
          ctx.setTransform(-1, 0, 0, 1, x * w + cw, 0);
          ctx.drawImage(sprites[C.spr], 0, C.y * h - ch / 2, cw, ch);
          ctx.setTransform(1, 0, 0, 1, 0, 0);
        } else {
          ctx.drawImage(sprites[C.spr], x * w, C.y * h - ch / 2, cw, ch);
        }
      }
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = sprites = clouds = null;
    },
  });
})();
