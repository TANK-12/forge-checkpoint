/* live: Aurora | Northern lights waving slowly over a starry sky, dark mountains and a still lake */
(function () {
  var U = ForgeLive.util;
  var bg, mtn, shore, aur, aurG, strips, ribbons, starTw, accent, W, H;
  var HOR = 0.68, SHORE = 0.92, DOWN = 4;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
  }
  // a vertical curtain strip: bright low edge, fading up into violet
  function strip(lowCol, highCol) {
    var c = U.layer(1, 128), g = c.getContext("2d");
    var gr = g.createLinearGradient(0, 0, 0, 128);
    gr.addColorStop(0, U.rgba(highCol, 0));
    gr.addColorStop(0.45, U.rgba(highCol, 0.35));
    gr.addColorStop(0.8, U.rgba(lowCol, 0.9));
    gr.addColorStop(0.9, U.rgba(U.mix(lowCol, [255, 255, 255], 0.3), 1));
    gr.addColorStop(1, U.rgba(lowCol, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, 1, 128);
    return c;
  }
  function peaks(seed, base, amp) {
    var r = U.rng(seed), p = [r() * 6, r() * 6, r() * 6, r() * 6];
    return function (u) {
      var a = 1 - Math.abs(Math.sin(u * 2.2 + p[0]));
      var b = 1 - Math.abs(Math.sin(u * 5.1 + p[1]));
      var c = 1 - Math.abs(Math.sin(u * 13 + p[2]));
      return base - amp * (0.55 * a * a + 0.3 * b * b + 0.08 * c + 0.07 * Math.sin(u * 31 + p[3]));
    };
  }
  function shape(g, w, h, fy, col, mirror) {
    g.fillStyle = U.rgba(col);
    g.beginPath();
    g.moveTo(0, HOR * h);
    for (var x = 0; x <= w + 4; x += 3) {
      var y = fy(x / w);
      g.lineTo(x, (mirror ? 2 * HOR - y : y) * h);
    }
    g.lineTo(w, HOR * h);
    g.closePath();
    g.fill();
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, HOR * h);
    lin.addColorStop(0, U.rgba(U.mix([3, 6, 16], accent, 0.04)));
    lin.addColorStop(0.6, U.rgba(U.mix([8, 18, 36], accent, 0.08)));
    lin.addColorStop(1, U.rgba(U.mix([18, 36, 56], accent, 0.12)));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var rnd = U.rng(401);
    for (var i = 0; i < 320; i++) {
      var r = rnd() < 0.9 ? 0.6 + rnd() * 0.6 : 1.3 + rnd() * 0.8;
      g.fillStyle = "rgba(225,235,255," + (0.15 + rnd() * 0.6).toFixed(2) + ")";
      g.fillRect(rnd() * w, rnd() * HOR * h, r, r);
    }
    starTw = [];
    for (var k = 0; k < 40; k++) starTw.push({ x: rnd(), y: rnd() * HOR * 0.9, p: rnd() * 6.28, f: 0.5 + rnd() * 1.5 });
    mtn = U.layer(w, h);
    var m = mtn.getContext("2d");
    var far = peaks(11, HOR - 0.02, 0.17), near = peaks(17, HOR + 0.005, 0.09);
    shape(m, w, h, far, U.mix([18, 28, 46], accent, 0.06));
    shape(m, w, h, near, [7, 11, 20]);
    var lake = m.createLinearGradient(0, HOR * h, 0, h);
    lake.addColorStop(0, U.rgba(U.mix([14, 26, 42], accent, 0.08)));
    lake.addColorStop(1, "rgb(4,7,14)");
    m.fillStyle = lake;
    m.fillRect(0, HOR * h, w, h);
    m.globalAlpha = 0.85;
    shape(m, w, h, far, [12, 18, 30], true);
    shape(m, w, h, near, [5, 8, 15], true);
    m.globalAlpha = 1;
    shore = U.layer(w, h);
    var s = shore.getContext("2d");
    s.fillStyle = "rgb(3,5,10)";
    s.beginPath();
    s.moveTo(0, h);
    for (var x = 0; x <= w + 4; x += 4) {
      var u = x / w;
      s.lineTo(x, (SHORE + 0.015 * Math.sin(u * 9 + 1) + 0.03 * Math.pow(Math.abs(u - 0.5) * 2, 3) * -1) * h);
    }
    s.lineTo(w, h);
    s.closePath();
    s.fill();
    for (var q = 0; q < 26; q++) {
      var side = q % 2 ? rnd() * 0.18 : 1 - rnd() * 0.18;
      var ph = h * (0.05 + rnd() * 0.09), px = side * w, py = h * (SHORE - 0.01);
      s.beginPath();
      s.moveTo(px, py - ph);
      s.lineTo(px + ph * 0.18, py);
      s.lineTo(px - ph * 0.18, py);
      s.closePath();
      s.fill();
    }
    aur = U.layer(Math.ceil(w / DOWN), Math.ceil(h / DOWN));
    aurG = aur.getContext("2d");
    var green = U.mix([90, 255, 170], accent, 0.35), violet = U.mix([170, 80, 255], accent, 0.25);
    strips = [strip(green, violet), strip(U.mix(green, [120, 220, 255], 0.4), violet)];
  }
  function build(w, h, o) {
    var rnd = U.rng(409);
    ribbons = [];
    var n = o.lite ? 2 : 3;
    for (var i = 0; i < n; i++) {
      ribbons.push({
        base: 0.32 + i * 0.08 + rnd() * 0.05, ht: 0.2 + rnd() * 0.12, p: rnd() * 6.28, s: 0.7 + rnd() * 0.6,
        c: 0.3 + rnd() * 0.4, wd: 0.35 + rnd() * 0.25, a: 0.55 - i * 0.1, strip: i % 2,
      });
    }
    paint(w, h);
  }

  ForgeLive.scene("aurora", {
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
      paint(W, H);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      ctx.drawImage(bg, 0, 0, w, h);
      for (var k = 0; k < starTw.length; k++) {
        var st = starTw[k];
        ctx.fillStyle = "rgba(235,242,255," + (0.35 + 0.35 * Math.sin(t * st.f + st.p)).toFixed(3) + ")";
        ctx.fillRect(st.x * w, st.y * h, 1.6, 1.6);
      }
      // the curtains, drawn small and scaled up so they come out soft
      var aw = aur.width, ah = aur.height;
      aurG.globalCompositeOperation = "source-over";
      aurG.clearRect(0, 0, aw, ah);
      aurG.globalCompositeOperation = "lighter";
      for (var r = 0; r < ribbons.length; r++) {
        var R = ribbons[r], spr = strips[R.strip];
        for (var i = 0; i < aw; i++) {
          var u = i / aw;
          var env = Math.exp(-Math.pow((u - R.c - 0.08 * Math.sin(t * 0.02 + R.p)) / R.wd, 2));
          if (env < 0.02) continue;
          var yb = ah * (R.base + 0.07 * Math.sin(u * 2.3 + t * 0.05 * R.s + R.p) + 0.03 * Math.sin(u * 5.1 - t * 0.08 + R.p * 2));
          var hh = ah * R.ht * (0.65 + 0.35 * Math.sin(u * 3.7 + t * 0.07 + R.p));
          var fold = 0.5 + 0.5 * Math.sin(u * 9 + t * 0.12 * R.s + R.p + 1.5 * Math.sin(u * 2 + t * 0.03));
          var rays = 0.85 + 0.15 * Math.sin(u * 70 + t * 0.3 + R.p);
          aurG.globalAlpha = Math.min(1, R.a * env * (0.3 + 0.7 * fold * fold) * rays);
          aurG.drawImage(spr, 0, 0, 1, 128, i, yb - hh, 1, hh * 1.15);
        }
      }
      ctx.globalCompositeOperation = "lighter";
      ctx.drawImage(aur, 0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(mtn, 0, 0, w, h);
      // its reflection in the lake
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, HOR * h, w, (SHORE - HOR) * h);
      ctx.clip();
      ctx.translate(0, 2 * HOR * h);
      ctx.scale(1, -1);
      ctx.globalCompositeOperation = "lighter";
      ctx.globalAlpha = 0.28;
      ctx.drawImage(aur, 0, 0, w, h);
      ctx.restore();
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
      ctx.drawImage(shore, 0, 0, w, h);
    },
    stop: function () {
      bg = mtn = shore = aur = aurG = strips = ribbons = null;
    },
  });
})();
