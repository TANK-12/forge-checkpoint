/* live: Embers | Warm embers and soft bokeh rising slowly from a fire below */
(function () {
  var U = ForgeLive.util;
  var bg, glow, bokehSpr, embers, bokeh, accent;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function radial(size, col, soft) {
    var c = U.layer(size, size), g = c.getContext("2d"), r = size / 2;
    var gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, U.rgba(col, 1));
    gr.addColorStop(soft, U.rgba(col, 0.55));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, size, size);
    return c;
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    lin.addColorStop(0, U.rgba(U.mix([10, 6, 8], accent, 0.06)));
    lin.addColorStop(0.55, "rgb(22,9,8)");
    lin.addColorStop(0.85, "rgb(70,22,10)");
    lin.addColorStop(1, "rgb(120,40,12)");
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    // the fire's glow, wide and low
    var r = g.createRadialGradient(w * 0.5, h * 1.08, 0, w * 0.5, h * 1.08, h * 0.9);
    r.addColorStop(0, "rgba(255,140,50,0.55)");
    r.addColorStop(0.45, "rgba(200,70,20,0.18)");
    r.addColorStop(1, "rgba(120,30,10,0)");
    g.fillStyle = r;
    g.fillRect(0, 0, w, h);
    // a faint accent haze up high keeps it in the theme
    var a = g.createRadialGradient(w * 0.2, h * 0.1, 0, w * 0.2, h * 0.1, w * 0.5);
    a.addColorStop(0, U.rgba(accent, 0.07));
    a.addColorStop(1, U.rgba(accent, 0));
    g.fillStyle = a;
    g.fillRect(0, 0, w, h);
    var v = g.createRadialGradient(w / 2, h * 0.6, h * 0.35, w / 2, h * 0.6, w * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, "rgba(0,0,0,0.5)");
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
    glow = radial(32, [255, 170, 80], 0.25);
    bokehSpr = [
      radial(128, [255, 150, 70], 0.7),
      radial(128, [255, 200, 120], 0.7),
      radial(128, U.mix([255, 150, 90], accent, 0.45), 0.7),
    ];
  }
  function build(w, h, o) {
    var rnd = U.rng(41);
    embers = [];
    var n = o.lite ? 50 : 100;
    for (var i = 0; i < n; i++) {
      embers.push({
        x: 0.1 + rnd() * 0.8, life: 6 + rnd() * 9, ph: rnd() * 20, rise: 0.6 + rnd() * 0.5,
        wa: 0.01 + rnd() * 0.03, wf: 0.6 + rnd() * 1.4, wp: rnd() * 6.28, lean: (rnd() - 0.5) * 0.12,
        r: 0.8 + rnd() * 1.6, fl: 4 + rnd() * 8,
      });
    }
    bokeh = [];
    var nb = o.lite ? 9 : 18;
    for (var j = 0; j < nb; j++) {
      bokeh.push({
        x: rnd(), y: rnd(), v: 0.006 + rnd() * 0.01, r: 30 + rnd() * 70, a: 0.05 + rnd() * 0.08,
        sw: 0.02 + rnd() * 0.03, sp: rnd() * 6.28, spr: j % 3,
      });
    }
    paint(w, h);
  }

  ForgeLive.scene("embers", {
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
      paint(bg.width, bg.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      for (var j = 0; j < bokeh.length; j++) {
        var b = bokeh[j];
        var by = (1.2 - ((b.y + t * b.v) % 1.4)) * h;
        var bx = (b.x + b.sw * Math.sin(t * 0.2 + b.sp)) * w;
        // brighter low down, fading as it rises
        ctx.globalAlpha = b.a * Math.max(0, Math.min(1, by / h + 0.2));
        ctx.drawImage(bokehSpr[b.spr], bx - b.r, by - b.r, b.r * 2, b.r * 2);
      }
      for (var i = 0; i < embers.length; i++) {
        var e = embers[i];
        var u = ((t + e.ph) % e.life) / e.life; // 0 born, 1 gone
        var y = h * (1.02 - u * e.rise);
        var x = (e.x + e.lean * u + e.wa * Math.sin(t * e.wf + e.wp) * u) * w;
        var fade = Math.min(1, u * 8) * (1 - u) * (1 - u);
        var flick = 0.7 + 0.3 * Math.sin(t * e.fl + e.wp * 3);
        var a = fade * flick;
        if (a < 0.02) continue;
        var s = e.r * (1 - u * 0.5);
        ctx.globalAlpha = a * 0.5;
        ctx.drawImage(glow, x - s * 6, y - s * 6, s * 12, s * 12);
        // hot core: white-yellow when young, red as it cools
        var col = u < 0.3 ? [255, 236, 170] : u < 0.6 ? [255, 170, 80] : [230, 90, 40];
        ctx.globalAlpha = a;
        ctx.fillStyle = U.rgba(col);
        ctx.fillRect(x - s * 0.6, y - s * 0.6, s * 1.2, s * 1.2);
      }
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    },
    stop: function () {
      bg = glow = bokehSpr = embers = bokeh = null;
    },
  });
})();
