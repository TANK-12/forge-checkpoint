/* live: Rain | Rain running down a window over the blurred warm lights of a city at night */
(function () {
  var U = ForgeLive.util;
  var bg, beads, drops, streaks, accent;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  function hash(a, b) {
    var s = Math.sin(a * 127.1 + b * 311.7) * 43758.5453;
    return s - Math.floor(s);
  }
  function blob(g, x, y, r, col, a) {
    var gr = g.createRadialGradient(x, y, 0, x, y, r);
    gr.addColorStop(0, U.rgba(col, a));
    gr.addColorStop(0.55, U.rgba(col, a * 0.6));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(x - r, y - r, r * 2, r * 2);
  }
  function paint(w, h) {
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    lin.addColorStop(0, U.rgba(U.mix([14, 16, 26], accent, 0.12)));
    lin.addColorStop(0.6, "rgb(26,22,30)");
    lin.addColorStop(1, "rgb(40,26,24)");
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    // out-of-focus city: warm street lights low, cooler windows higher up
    var rnd = U.rng(5);
    var warm = [[255, 176, 90], [255, 210, 140], [255, 140, 80], [250, 230, 190]];
    var cool = U.mix([140, 170, 255], accent, 0.6);
    g.globalCompositeOperation = "lighter";
    for (var i = 0; i < 140; i++) {
      var low = rnd() < 0.7;
      var y = low ? h * (0.55 + rnd() * 0.4) : h * (0.15 + rnd() * 0.45);
      var col = low || rnd() < 0.5 ? warm[Math.floor(rnd() * warm.length)] : cool;
      var r = (low ? 20 : 12) + rnd() * (low ? 70 : 40);
      blob(g, rnd() * w, y, r, col, 0.06 + rnd() * 0.16);
    }
    // a haze band where the street is
    var haze = g.createLinearGradient(0, h * 0.55, 0, h);
    haze.addColorStop(0, "rgba(255,150,80,0)");
    haze.addColorStop(1, "rgba(255,150,80,0.12)");
    g.fillStyle = haze;
    g.fillRect(0, h * 0.55, w, h * 0.45);
    g.globalCompositeOperation = "source-over";
    // fog on the glass
    g.fillStyle = "rgba(160,170,190,0.05)";
    g.fillRect(0, 0, w, h);
    // still beads on the glass: a dark rim and a bright lower edge
    beads = U.layer(w, h);
    var b = beads.getContext("2d");
    var rb = U.rng(9);
    for (var k = 0; k < 900; k++) {
      var bx = rb() * w, by = rb() * h, br = 0.6 + Math.pow(rb(), 3) * 3.5;
      b.fillStyle = "rgba(8,8,14,0.35)";
      b.beginPath();
      b.arc(bx, by, br, 0, 6.2832);
      b.fill();
      b.fillStyle = "rgba(255,225,190,0.45)";
      b.beginPath();
      b.arc(bx, by + br * 0.35, br * 0.55, 0, 6.2832);
      b.fill();
    }
  }
  function build(w, h, o) {
    var rnd = U.rng(77);
    drops = [];
    var n = o.lite ? 14 : 28;
    for (var i = 0; i < n; i++) {
      drops.push({
        v: 0.05 + rnd() * 0.07, ph: rnd() * 10, st: 0.3 + rnd() * 0.65, sf: 1 + rnd() * 1.5,
        r: 1.6 + rnd() * 2.2, trail: 0.08 + rnd() * 0.22, id: i,
      });
    }
    streaks = [];
    for (var j = 0; j < (o.lite ? 30 : 60); j++) {
      streaks.push({ x: rnd(), y: rnd(), v: 1.2 + rnd() * 0.8, l: 10 + rnd() * 18, a: 0.04 + rnd() * 0.06 });
    }
    paint(w, h);
  }

  ForgeLive.scene("rain", {
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
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      // rain falling outside, faint and slanted
      ctx.strokeStyle = "rgba(200,210,235,1)";
      ctx.lineWidth = 1;
      for (var s = 0; s < streaks.length; s++) {
        var st = streaks[s];
        var sy = ((st.y + t * st.v) % 1.1) * h - 20;
        var sx = ((st.x + sy / h * 0.05) % 1) * w;
        ctx.globalAlpha = st.a;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(sx - st.l * 0.12, sy + st.l);
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      ctx.drawImage(beads, 0, 0, w, h);
      // drops running down: they stall, then slide, then pick a new lane
      for (var i = 0; i < drops.length; i++) {
        var d = drops[i];
        var p = t * d.v + d.ph + (d.st / (6.28 * d.sf)) * Math.sin((t * d.v + d.ph) * 6.28 * d.sf);
        var lap = Math.floor(p);
        var u = p - lap; // 0 top, 1 bottom
        var x0 = hash(d.id, lap) * w;
        var y = (u * 1.2 - 0.1) * h;
        var wob = 3 * Math.sin(y * 0.03 + d.id);
        var x = x0 + wob;
        var tl = d.trail * h;
        var tr = ctx.createLinearGradient(0, y - tl, 0, y);
        tr.addColorStop(0, "rgba(220,225,240,0)");
        tr.addColorStop(1, "rgba(220,225,240,0.22)");
        ctx.strokeStyle = tr;
        ctx.lineWidth = d.r * 0.7;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(x0 + 3 * Math.sin((y - tl) * 0.03 + d.id), y - tl);
        ctx.lineTo(x, y);
        ctx.stroke();
        ctx.fillStyle = "rgba(10,10,18,0.45)";
        ctx.beginPath();
        ctx.ellipse(x, y, d.r, d.r * 1.25, 0, 0, 6.2832);
        ctx.fill();
        ctx.fillStyle = "rgba(255,230,200,0.6)";
        ctx.beginPath();
        ctx.ellipse(x, y + d.r * 0.4, d.r * 0.6, d.r * 0.7, 0, 0, 6.2832);
        ctx.fill();
        ctx.fillStyle = "rgba(255,255,255,0.7)";
        ctx.fillRect(x - d.r * 0.45, y - d.r * 0.6, d.r * 0.35, d.r * 0.35);
      }
    },
    stop: function () {
      bg = beads = drops = streaks = null;
    },
  });
})();
