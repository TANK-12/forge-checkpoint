/* live: Code rain | Slow columns of glyphs falling in the accent colour, a calm terminal look */
(function () {
  var U = ForgeLive.util;
  var bg, overlay, tailAtlas, headAtlas, cols, fs, accent, light, lite, W, H;
  var GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜｦﾝ0123456789:=+<>*";

  function colours(o) {
    accent = U.hex(o.accent, "#5bd67a");
    light = o.mode === "light";
    lite = !!o.lite;
  }
  function hash(a, b, c) {
    var x = (Math.imul(a, 374761393) + Math.imul(b, 668265263) + Math.imul(c, 362437)) | 0;
    x = Math.imul(x ^ (x >>> 13), 1274126177);
    return (x ^ (x >>> 16)) >>> 0;
  }
  function atlas(col, glowA) {
    var n = GLYPHS.length, c = U.layer(fs * n, fs), g = c.getContext("2d");
    g.font = Math.round(fs * 0.86) + "px 'Noto Sans Mono CJK JP','Noto Sans CJK JP','DejaVu Sans Mono',monospace";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillStyle = U.rgba(col);
    if (glowA) {
      g.shadowColor = U.rgba(col, glowA);
      g.shadowBlur = fs * 0.5;
    }
    for (var i = 0; i < n; i++) {
      g.save();
      // katakana are mirrored, the way the classic rain draws them
      g.translate(i * fs + fs / 2, fs / 2);
      if (i < 46) g.scale(-1, 1);
      g.fillText(GLYPHS[i], 0, 0);
      g.restore();
    }
    return c;
  }
  function paint(w, h) {
    W = w;
    H = h;
    fs = Math.max(12, Math.round(h / 44));
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    g.fillStyle = light ? U.rgba(U.mix([236, 240, 234], accent, 0.06)) : U.rgba(U.mix([2, 5, 4], accent, 0.03));
    g.fillRect(0, 0, w, h);
    var r = g.createRadialGradient(w / 2, h * 0.45, 0, w / 2, h * 0.45, w * 0.6);
    r.addColorStop(0, U.rgba(accent, light ? 0.06 : 0.07));
    r.addColorStop(1, U.rgba(accent, 0));
    g.fillStyle = r;
    g.fillRect(0, 0, w, h);
    overlay = U.layer(w, h);
    var o = overlay.getContext("2d");
    o.fillStyle = light ? "rgba(0,0,0,0.025)" : "rgba(0,0,0,0.22)";
    for (var y = 0; y < h; y += 3) o.fillRect(0, y, w, 1);
    var v = o.createRadialGradient(w / 2, h / 2, h * 0.35, w / 2, h / 2, w * 0.72);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, light ? "rgba(40,50,40,0.12)" : "rgba(0,0,0,0.6)");
    o.fillStyle = v;
    o.fillRect(0, 0, w, h);
    var tail = light ? U.mix(accent, [0, 0, 0], 0.35) : accent;
    var head = light ? U.mix(accent, [0, 0, 0], 0.7) : U.mix(accent, [255, 255, 255], 0.75);
    tailAtlas = atlas(tail, 0);
    headAtlas = atlas(head, light ? 0 : 0.9);
  }
  function build(w, h) {
    paint(w, h);
    var rnd = U.rng(601);
    cols = [];
    var n = Math.ceil(w / fs), rows = Math.ceil(h / fs) + 1;
    var share = lite ? 0.32 : 0.55;
    for (var i = 0; i < n; i++) {
      if (rnd() > share) continue;
      var len = 8 + Math.floor(rnd() * 20);
      cols.push({ c: i, v: 1.2 + rnd() * 2.2, len: len, off: rnd() * (rows + len), d: 0.35 + rnd() * 0.65, span: rows + len + Math.floor(rnd() * 12) });
    }
  }

  ForgeLive.scene("code-rain", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 20,
    res: 0.6,
    start: function (ctx, w, h, o) {
      colours(o);
      build(w, h);
    },
    resize: function (ctx, w, h) {
      build(w, h);
    },
    update: function (o) {
      colours(o);
      paint(W, H);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      var n = GLYPHS.length, rows = Math.ceil(h / fs) + 1;
      for (var i = 0; i < cols.length; i++) {
        var C = cols[i];
        var head = Math.floor((t * C.v + C.off) % C.span);
        for (var k = 0; k < C.len; k++) {
          var row = head - k;
          if (row < 0 || row > rows) continue;
          // each cell swaps its glyph now and then; the head flickers faster
          var tick = Math.floor(t * (k ? 0.4 : 3) + (hash(C.c, row, 7) % 100) / 100);
          var gi = hash(C.c, row, tick) % n;
          var a = C.d * Math.pow(1 - k / C.len, 1.4);
          if (a < 0.03) continue;
          ctx.globalAlpha = k ? a * 0.85 : C.d;
          ctx.drawImage(k ? tailAtlas : headAtlas, gi * fs, 0, fs, fs, C.c * fs, row * fs, fs, fs);
        }
      }
      ctx.globalAlpha = 1;
      ctx.drawImage(overlay, 0, 0, w, h);
    },
    stop: function () {
      bg = overlay = tailAtlas = headAtlas = cols = null;
    },
  });
})();
