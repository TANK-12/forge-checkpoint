/* live: Lava | Soft pastel lava-lamp blobs slowly rising, sinking and merging */
(function () {
  var U = ForgeLive.util;
  var bg, field, fctx, img, blobs, pal, accent, light, W, H;
  var GW = 176;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
    var base = [accent, [255, 160, 190], [255, 196, 140], [180, 160, 255], [130, 214, 200]];
    pal = base.map(function (c) {
      return light ? U.mix(c, [255, 255, 255], 0.3) : U.mix(c, [255, 255, 255], 0.08);
    });
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, w * 0.4, h);
    if (light) {
      lin.addColorStop(0, U.rgba(U.mix([250, 242, 246], accent, 0.05)));
      lin.addColorStop(1, U.rgba(U.mix([236, 230, 248], accent, 0.08)));
    } else {
      lin.addColorStop(0, U.rgba(U.mix([26, 14, 42], accent, 0.08)));
      lin.addColorStop(1, U.rgba(U.mix([8, 8, 22], accent, 0.05)));
    }
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var r = g.createRadialGradient(w * 0.5, h * 1.05, 0, w * 0.5, h * 1.05, h * 0.8);
    r.addColorStop(0, U.rgba(pal[0], light ? 0.18 : 0.14));
    r.addColorStop(1, U.rgba(pal[0], 0));
    g.fillStyle = r;
    g.fillRect(0, 0, w, h);
    var gh = Math.max(8, Math.round((GW * h) / w));
    field = U.layer(GW, gh);
    fctx = field.getContext("2d");
    img = fctx.createImageData(GW, gh);
  }
  function build(w, h, o) {
    var rnd = U.rng(1103);
    blobs = [];
    var n = o.lite ? 6 : 8;
    for (var i = 0; i < n; i++) {
      blobs.push({
        x: 0.1 + rnd() * 0.8, ax: 0.04 + rnd() * 0.08, fx: 0.02 + rnd() * 0.04, ay: 0.32 + rnd() * 0.12,
        fy: 0.035 + rnd() * 0.045, p: rnd() * 6.28, r: 0.07 + rnd() * 0.07, c: i % 5,
      });
    }
    paint(w, h);
  }

  ForgeLive.scene("lava", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 24,
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
      var gw = field.width, gh = field.height, m = Math.min(gw, gh), d = img.data;
      var n = blobs.length, bx = [], by = [], br = [];
      for (var i = 0; i < n; i++) {
        var B = blobs[i];
        bx.push((B.x + B.ax * Math.sin(t * B.fx + B.p)) * gw);
        by.push((0.5 + B.ay * Math.sin(t * B.fy + B.p * 1.7)) * gh);
        var rr = B.r * m * 1.6 * (0.9 + 0.1 * Math.sin(t * 0.13 + B.p));
        br.push(rr * rr);
      }
      var p = 0;
      for (var y = 0; y < gh; y++) {
        for (var x = 0; x < gw; x++) {
          var f = 0, cr = 0, cg = 0, cb = 0;
          for (var k = 0; k < n; k++) {
            var dx = x - bx[k], dy = y - by[k];
            var v = br[k] / (dx * dx + dy * dy + 1);
            f += v;
            var c = pal[blobs[k].c];
            cr += c[0] * v;
            cg += c[1] * v;
            cb += c[2] * v;
          }
          var a = 0;
          if (f > 0.3) {
            var e = Math.min(1, Math.max(0, (f - 0.85) / 0.3));
            e = e * e * (3 - 2 * e);
            var halo = Math.min(1, (f - 0.3) / 0.55) * (light ? 0.12 : 0.22);
            a = Math.max(e * (light ? 0.88 : 0.82), halo);
            var core = 1 + Math.min(0.18, (f - 1) * 0.06);
            cr = Math.min(255, (cr / f) * core);
            cg = Math.min(255, (cg / f) * core);
            cb = Math.min(255, (cb / f) * core);
          }
          d[p] = cr;
          d[p + 1] = cg;
          d[p + 2] = cb;
          d[p + 3] = a * 255;
          p += 4;
        }
      }
      fctx.putImageData(img, 0, 0);
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      ctx.drawImage(field, 0, 0, w, h);
    },
    stop: function () {
      bg = field = fctx = img = blobs = null;
    },
  });
})();
