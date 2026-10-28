/* live: Paper | Cream paper with a faint grain and slow, soft washes of ink (for light themes) */
(function () {
  var U = ForgeLive.util;
  var bg, grain, washes, inks, dark, accent;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    dark = o.mode === "dark";
    // muted inks: the accent, an indigo and a warm sepia, all softened toward grey
    var grey = dark ? [200, 200, 210] : [150, 146, 140];
    inks = [
      U.mix(accent, grey, 0.35),
      U.mix([60, 70, 130], grey, 0.25),
      U.mix([150, 100, 70], grey, 0.3),
      U.mix(accent, [200, 120, 140], 0.5),
    ];
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var paperTop = dark ? [34, 36, 42] : [246, 241, 230];
    var paperBot = dark ? [26, 27, 32] : [238, 231, 216];
    var lin = g.createLinearGradient(0, 0, w * 0.3, h);
    lin.addColorStop(0, U.rgba(paperTop));
    lin.addColorStop(1, U.rgba(paperBot));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    // a few long paper fibres
    var rnd = U.rng(83);
    g.lineWidth = 0.6;
    for (var f = 0; f < 140; f++) {
      var x = rnd() * w, y = rnd() * h, a = rnd() * 6.28, l = 8 + rnd() * 30;
      g.strokeStyle = dark ? "rgba(255,255,255,0.035)" : "rgba(120,100,70,0.06)";
      g.beginPath();
      g.moveTo(x, y);
      g.quadraticCurveTo(x + Math.cos(a) * l * 0.5 + 4, y + Math.sin(a) * l * 0.5, x + Math.cos(a) * l, y + Math.sin(a) * l);
      g.stroke();
    }
    var v = g.createRadialGradient(w / 2, h / 2, Math.min(w, h) * 0.4, w / 2, h / 2, Math.max(w, h) * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, dark ? "rgba(0,0,0,0.35)" : "rgba(110,90,60,0.12)");
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
    // grain: one noise tile, repeated
    var tile = U.layer(160, 160), tg = tile.getContext("2d");
    var img = tg.createImageData(160, 160), nr = U.rng(89);
    for (var i = 0; i < img.data.length; i += 4) {
      var n = nr();
      var c = dark ? 255 : 60;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = c;
      img.data[i + 3] = Math.floor(n * n * (dark ? 18 : 30));
    }
    tg.putImageData(img, 0, 0);
    grain = U.layer(w, h);
    var gg = grain.getContext("2d");
    gg.fillStyle = gg.createPattern(tile, "repeat");
    gg.fillRect(0, 0, w, h);
  }
  function build(w, h, o) {
    var rnd = U.rng(97);
    washes = [];
    var n = o.lite ? 3 : 6;
    for (var i = 0; i < n; i++) {
      var lobes = [];
      for (var k = 0; k < 4; k++) {
        lobes.push({ n: 2 + k * 2 + Math.floor(rnd() * 2), amp: 0.16 / (k + 1), f: 0.03 + rnd() * 0.05, p: rnd() * 6.28 });
      }
      washes.push({
        x: 0.1 + rnd() * 0.8, y: 0.1 + rnd() * 0.8, r: 0.12 + rnd() * 0.16, ax: 0.08 + rnd() * 0.1,
        ay: 0.06 + rnd() * 0.08, fx: 0.012 + rnd() * 0.02, fy: 0.01 + rnd() * 0.018, p: rnd() * 6.28,
        ink: i % inks.length, a: 0.1 + rnd() * 0.08, bf: 0.03 + rnd() * 0.03,
        lobes: lobes,
      });
    }
    paint(w, h);
  }

  ForgeLive.scene("paper", {
    lighter: { balanced: "", light: "still" },
    fps: 15,
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
      paint(bg.width, bg.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      // multiply darkens paper like ink; on dark paper the washes glow instead
      ctx.globalCompositeOperation = dark ? "screen" : "multiply";
      var m = Math.max(w, h);
      for (var i = 0; i < washes.length; i++) {
        var ws = washes[i];
        var cx = (ws.x + ws.ax * Math.sin(t * ws.fx + ws.p)) * w;
        var cy = (ws.y + ws.ay * Math.sin(t * ws.fy + ws.p * 1.7)) * h;
        var R = ws.r * m * (0.92 + 0.08 * Math.sin(t * ws.bf + ws.p));
        var col = inks[ws.ink];
        // two passes: the wash, then a smaller, darker pool inside it
        for (var pass = 0; pass < 2; pass++) {
          var rr = pass ? R * 0.55 : R;
          var ox = pass ? Math.cos(ws.p) * R * 0.2 : 0, oy = pass ? Math.sin(ws.p) * R * 0.2 : 0;
          ctx.beginPath();
          for (var k = 0; k <= 48; k++) {
            var th = (k / 48) * 6.2832;
            var wob = 1;
            for (var l = 0; l < ws.lobes.length; l++) {
              var lb = ws.lobes[l];
              wob += lb.amp * Math.sin(th * lb.n + lb.p + t * lb.f * (pass ? -1 : 1));
            }
            var px = cx + ox + Math.cos(th) * rr * wob, py = cy + oy + Math.sin(th) * rr * wob * 0.8;
            if (k) ctx.lineTo(px, py);
            else ctx.moveTo(px, py);
          }
          ctx.closePath();
          var gr = ctx.createRadialGradient(cx + ox, cy + oy, 0, cx + ox, cy + oy, rr * 1.2);
          gr.addColorStop(0, U.rgba(col, ws.a * 0.45));
          gr.addColorStop(0.75, U.rgba(col, ws.a * 0.7));
          gr.addColorStop(1, U.rgba(col, ws.a));
          ctx.fillStyle = gr;
          ctx.fill();
          // pigment pools at the drying edge
          ctx.strokeStyle = U.rgba(col, ws.a * 0.9);
          ctx.lineWidth = 1.2;
          ctx.stroke();
        }
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(grain, 0, 0, w, h);
    },
    stop: function () {
      bg = grain = washes = null;
    },
  });
})();
