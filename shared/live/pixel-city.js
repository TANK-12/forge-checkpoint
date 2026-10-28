/* live: Pixel City | A pixel-art night skyline with blinking windows and faint scanlines */
(function () {
  var U = ForgeLive.util;
  var PX = 4; // one art pixel is this many CSS pixels
  var cv, low, lowCtx, base, scan, windows, clouds, beacons, accent, lw, lh;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function hash(a, b) {
    var s = Math.sin(a * 91.17 + b * 47.53) * 24634.6345;
    return s - Math.floor(s);
  }
  function build(w, h) {
    lw = Math.max(80, Math.ceil(w / PX));
    lh = Math.max(45, Math.ceil(h / PX));
    low = U.layer(lw, lh);
    lowCtx = low.getContext("2d");
    base = U.layer(lw, lh);
    var g = base.getContext("2d");
    // sky in flat bands, the way old games did gradients
    var top = U.mix([8, 8, 28], accent, 0.18), bot = U.mix([60, 30, 80], accent, 0.25);
    var bands = 9;
    for (var b = 0; b < bands; b++) {
      g.fillStyle = U.rgba(U.mix(top, bot, b / (bands - 1)));
      var y0 = Math.floor((b / bands) * lh * 0.8);
      g.fillRect(0, y0, lw, Math.ceil(lh * 0.8 / bands) + 1);
    }
    g.fillStyle = U.rgba(bot);
    g.fillRect(0, Math.floor(lh * 0.8), lw, lh);
    var rnd = U.rng(51);
    for (var s = 0; s < lw * 0.35; s++) {
      g.fillStyle = rnd() < 0.2 ? "rgb(255,240,200)" : "rgb(170,180,230)";
      g.fillRect(Math.floor(rnd() * lw), Math.floor(rnd() * lh * 0.45), 1, 1);
    }
    // the moon: a pixel disc with a bite out of it
    var mx = Math.floor(lw * 0.78), my = Math.floor(lh * 0.16), mr = Math.max(4, Math.floor(lh * 0.06));
    for (var yy = -mr; yy <= mr; yy++) {
      for (var xx = -mr; xx <= mr; xx++) {
        if (xx * xx + yy * yy > mr * mr) continue;
        var bite = (xx + mr * 0.5) * (xx + mr * 0.5) + (yy - mr * 0.3) * (yy - mr * 0.3) < mr * mr * 0.7;
        if (bite) continue;
        g.fillStyle = xx + yy > mr * 0.6 ? "rgb(220,214,190)" : "rgb(250,244,215)";
        g.fillRect(mx + xx, my + yy, 1, 1);
      }
    }
    windows = [];
    beacons = [];
    var layers = [
      { base: 0.62, hmin: 0.08, hmax: 0.3, wmin: 6, wmax: 14, col: U.mix([30, 26, 60], accent, 0.18), win: 0 },
      { base: 0.78, hmin: 0.12, hmax: 0.42, wmin: 8, wmax: 18, col: U.mix([18, 16, 38], accent, 0.1), win: 0.25 },
      { base: 1.0, hmin: 0.16, hmax: 0.5, wmin: 10, wmax: 24, col: [8, 8, 18], win: 0.45 },
    ];
    var wid = 0;
    for (var L = 0; L < layers.length; L++) {
      var ly = layers[L];
      var x = -Math.floor(rnd() * 6);
      while (x < lw) {
        var bw = ly.wmin + Math.floor(rnd() * (ly.wmax - ly.wmin));
        var bh = Math.floor(lh * (ly.hmin + rnd() * (ly.hmax - ly.hmin)));
        var by = Math.floor(lh * ly.base) - bh;
        g.fillStyle = U.rgba(ly.col);
        g.fillRect(x, by, bw, lh - by);
        // a stepped roof or an antenna on some
        if (rnd() < 0.35) g.fillRect(x + 2, by - 2, bw - 4, 2);
        if (rnd() < 0.25) {
          var ax = x + Math.floor(bw / 2);
          var ah = 3 + Math.floor(rnd() * 6);
          g.fillRect(ax, by - ah, 1, ah);
          if (L > 0) beacons.push({ x: ax, y: by - ah - 1, p: rnd() * 6.28, f: 0.5 + rnd() * 0.6 });
        }
        if (ly.win) {
          var tint = rnd() < 0.2 ? U.mix([255, 220, 140], accent, 0.6) : [255, 214, 130];
          for (var wy = by + 2; wy < lh - 2; wy += 3) {
            for (var wx = x + 2; wx < x + bw - 2; wx += 2) {
              var r = rnd();
              if (r > ly.win + 0.25) continue;
              // a few windows change state now and then; most stay as they are
              windows.push({
                x: wx, y: wy, id: wid++, col: U.rgba(U.mix(tint, [255, 255, 255], r * 0.3)),
                on: r < ly.win, blink: rnd() < 0.18, per: 4 + rnd() * 14,
              });
            }
          }
        }
        x += bw + (rnd() < 0.3 ? 1 + Math.floor(rnd() * 3) : 0);
      }
    }
    clouds = [];
    for (var c = 0; c < 4; c++) {
      clouds.push({ x: rnd(), y: 0.08 + rnd() * 0.25, v: 0.003 + rnd() * 0.004, wid: 14 + Math.floor(rnd() * 20) });
    }
  }
  function scanlines(cw, ch) {
    scan = U.layer(cw, ch);
    var g = scan.getContext("2d");
    g.fillStyle = "rgba(0,0,0,0.16)";
    for (var y = 0; y < ch; y += 3) g.fillRect(0, y, cw, 1);
  }

  ForgeLive.scene("pixel-city", {
    lighter: { balanced: "", light: "still" },
    fps: 12,
    res: 1,
    start: function (ctx, w, h, o) {
      colours(o);
      build(w, h);
      scanlines(ctx.canvas.width, ctx.canvas.height);
      cv = ctx.canvas;
      cv.style.imageRendering = "pixelated";
    },
    resize: function (ctx, w, h) {
      build(w, h);
      scanlines(ctx.canvas.width, ctx.canvas.height);
    },
    update: function (o) {
      colours(o);
      build(lw * PX, lh * PX); // same art size; only the colours change
    },
    frame: function (ctx, t, dt, w, h) {
      var g = lowCtx;
      g.drawImage(base, 0, 0);
      for (var c = 0; c < clouds.length; c++) {
        var cl = clouds[c];
        var cx = Math.floor((((cl.x + t * cl.v) % 1.3) - 0.15) * lw);
        var cy = Math.floor(cl.y * lh);
        g.fillStyle = "rgba(120,110,170,0.35)";
        g.fillRect(cx, cy, cl.wid, 2);
        g.fillRect(cx + 3, cy - 1, cl.wid - 7, 1);
      }
      for (var i = 0; i < windows.length; i++) {
        var wn = windows[i];
        var on = wn.on;
        if (wn.blink) on = hash(wn.id, Math.floor(t / wn.per + wn.id * 0.37)) < 0.6;
        if (!on) continue;
        g.fillStyle = wn.col;
        g.fillRect(wn.x, wn.y, 1, 1);
      }
      for (var b = 0; b < beacons.length; b++) {
        var be = beacons[b];
        if (Math.sin(t * be.f * 3.14 + be.p) > 0.6) {
          g.fillStyle = "rgb(255,70,70)";
          g.fillRect(be.x, be.y, 1, 1);
        }
      }
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(low, 0, 0, lw, lh, 0, 0, lw * PX, lh * PX);
      ctx.save();
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.drawImage(scan, 0, 0);
      ctx.restore();
    },
    stop: function () {
      low = lowCtx = base = scan = windows = clouds = beacons = null;
      if (cv) cv.style.imageRendering = "";
      cv = null;
    },
  });
})();
