/* live: Bubbles | Underwater: light rays from the surface, rising bubbles, slow fish far back and swaying weed */
(function () {
  var U = ForgeLive.util;
  var bg, bed, raySpr, bubSpr, rays, fish, weed, bubbles, accent, light, water, fishCol, weedCols, W, H;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
    water = light
      ? [U.mix([130, 214, 222], accent, 0.12), U.mix([40, 150, 182], accent, 0.15), U.mix([12, 70, 110], accent, 0.12)]
      : [U.mix([30, 92, 122], accent, 0.12), U.mix([10, 40, 70], accent, 0.12), [2, 10, 24]];
    fishCol = U.mix(water[1], [0, 10, 20], light ? 0.45 : 0.6);
    weedCols = light ? [[52, 120, 96], [24, 84, 66]] : [[16, 62, 58], [6, 30, 30]];
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    lin.addColorStop(0, U.rgba(water[0]));
    lin.addColorStop(0.4, U.rgba(water[1]));
    lin.addColorStop(1, U.rgba(water[2]));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    var s = g.createRadialGradient(w * 0.45, -h * 0.2, 0, w * 0.45, -h * 0.2, h * 0.9);
    s.addColorStop(0, light ? "rgba(230,255,250,0.5)" : "rgba(150,220,230,0.25)");
    s.addColorStop(1, "rgba(150,220,230,0)");
    g.fillStyle = s;
    g.fillRect(0, 0, w, h);
    bed = U.layer(w, h);
    var b = bed.getContext("2d"), rnd = U.rng(809), p = rnd() * 6;
    var sand = light ? U.mix([170, 176, 150], water[2], 0.35) : U.mix([40, 52, 60], water[2], 0.3);
    var sg = b.createLinearGradient(0, h * 0.84, 0, h);
    sg.addColorStop(0, U.rgba(sand));
    sg.addColorStop(1, U.rgba(U.mix(sand, [0, 0, 0], 0.45)));
    b.fillStyle = sg;
    b.beginPath();
    b.moveTo(0, h);
    for (var x = 0; x <= w + 4; x += 4) {
      var u = x / w;
      b.lineTo(x, h * (0.9 - 0.025 * Math.sin(u * 3 + p) - 0.012 * Math.sin(u * 9 + p)));
    }
    b.lineTo(w, h);
    b.closePath();
    b.fill();
    var rock = U.mix(sand, [0, 0, 0], 0.55);
    for (var r = 0; r < 9; r++) {
      var rx = (r < 5 ? rnd() * 0.25 : 0.75 + rnd() * 0.25) * w, rr = h * (0.025 + rnd() * 0.05);
      b.fillStyle = U.rgba(U.mix(rock, sand, rnd() * 0.3));
      b.beginPath();
      b.ellipse(rx, h * 0.92, rr * 1.4, rr, 0, Math.PI, 0);
      b.fill();
    }
    raySpr = U.layer(64, 256);
    var rg = raySpr.getContext("2d");
    var vg = rg.createLinearGradient(0, 0, 0, 256);
    vg.addColorStop(0, "rgba(220,255,250,0.9)");
    vg.addColorStop(1, "rgba(220,255,250,0)");
    rg.fillStyle = vg;
    rg.fillRect(0, 0, 64, 256);
    rg.globalCompositeOperation = "destination-in";
    var hg = rg.createLinearGradient(0, 0, 64, 0);
    hg.addColorStop(0, "rgba(0,0,0,0)");
    hg.addColorStop(0.5, "rgba(0,0,0,1)");
    hg.addColorStop(1, "rgba(0,0,0,0)");
    rg.fillStyle = hg;
    rg.fillRect(0, 0, 64, 256);
    bubSpr = U.layer(64, 64);
    var bb = bubSpr.getContext("2d");
    var ring = bb.createRadialGradient(32, 32, 0, 32, 32, 30);
    ring.addColorStop(0, "rgba(220,250,255,0.05)");
    ring.addColorStop(0.75, "rgba(220,250,255,0.18)");
    ring.addColorStop(0.92, "rgba(235,255,255,0.75)");
    ring.addColorStop(1, "rgba(235,255,255,0)");
    bb.fillStyle = ring;
    bb.fillRect(0, 0, 64, 64);
    bb.fillStyle = "rgba(255,255,255,0.85)";
    bb.beginPath();
    bb.ellipse(22, 20, 6, 4, -0.6, 0, 6.2832);
    bb.fill();
  }
  function build(w, h, o) {
    var rnd = U.rng(821);
    rays = [];
    for (var i = 0; i < 7; i++) rays.push({ x: 0.1 + i * 0.13 + rnd() * 0.05, wd: 0.04 + rnd() * 0.07, tilt: 0.12 + rnd() * 0.1, f: 0.15 + rnd() * 0.2, p: rnd() * 6.28, a: 0.06 + rnd() * 0.08 });
    fish = [];
    for (var j = 0; j < (o.lite ? 3 : 6); j++) {
      fish.push({ x: rnd(), y: 0.3 + rnd() * 0.4, s: 0.018 + rnd() * 0.03, v: 0.008 + rnd() * 0.012, dir: rnd() < 0.5 ? -1 : 1, p: rnd() * 6.28, a: 0.35 + rnd() * 0.3 });
    }
    weed = [];
    for (var k = 0; k < (o.lite ? 14 : 26); k++) {
      var cl = [0.06, 0.16, 0.3, 0.72, 0.85, 0.94][k % 6];
      weed.push({ x: cl + (rnd() - 0.5) * 0.08, len: 0.1 + rnd() * 0.22, wd: 0.006 + rnd() * 0.006, p: rnd() * 6.28, f: 0.4 + rnd() * 0.4, c: rnd() < 0.5 ? 0 : 1 });
    }
    bubbles = [];
    var vents = [0.18, 0.55, 0.83];
    for (var m = 0; m < (o.lite ? 22 : 46); m++) {
      var vent = m % 4 === 3 ? rnd() : vents[m % 3] + (rnd() - 0.5) * 0.03;
      var near = rnd();
      bubbles.push({ x: vent, ph: rnd(), v: 0.05 + rnd() * 0.06, r: 0.004 + near * near * 0.012, wa: 0.006 + rnd() * 0.012, wf: 1 + rnd() * 2, wp: rnd() * 6.28 });
    }
    paint(w, h);
  }
  function drawFish(ctx, x, y, s, dir, wag) {
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(dir * s, s);
    ctx.beginPath();
    ctx.moveTo(1, 0);
    ctx.quadraticCurveTo(0.3, -0.42, -0.6, -0.05);
    ctx.lineTo(-1.05, -0.35 + wag);
    ctx.lineTo(-0.95, 0.02 + wag * 0.5);
    ctx.lineTo(-1.05, 0.35 + wag);
    ctx.lineTo(-0.6, 0.05);
    ctx.quadraticCurveTo(0.3, 0.38, 1, 0);
    ctx.fill();
    ctx.restore();
  }

  ForgeLive.scene("bubbles", {
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
      ctx.globalCompositeOperation = "lighter";
      for (var i = 0; i < rays.length; i++) {
        var R = rays[i];
        var rx = (R.x + 0.02 * Math.sin(t * 0.08 + R.p)) * w;
        ctx.globalAlpha = R.a * (0.55 + 0.45 * Math.sin(t * R.f + R.p)) * (light ? 1.3 : 1);
        ctx.setTransform(Math.cos(R.tilt), Math.sin(R.tilt), -Math.sin(R.tilt), Math.cos(R.tilt), rx, -h * 0.05);
        ctx.drawImage(raySpr, -R.wd * w / 2, 0, R.wd * w, h * 0.95);
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      // caustic shimmer just under the surface
      ctx.globalAlpha = light ? 0.16 : 0.1;
      ctx.strokeStyle = "rgb(230,255,255)";
      ctx.lineWidth = 1.2;
      for (var c = 0; c < 3; c++) {
        ctx.beginPath();
        for (var x = 0; x <= w; x += 8) {
          var y = h * (0.02 + c * 0.025) + h * 0.008 * Math.sin(x / w * 18 + t * (0.5 + c * 0.2) + c * 2) + h * 0.006 * Math.sin(x / w * 41 - t * 0.7);
          if (x) ctx.lineTo(x, y);
          else ctx.moveTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalCompositeOperation = "source-over";
      ctx.fillStyle = U.rgba(fishCol);
      for (var f = 0; f < fish.length; f++) {
        var F = fish[f];
        var fx = (F.x + F.dir * F.v * t) % 1.4;
        if (fx < 0) fx += 1.4;
        ctx.globalAlpha = F.a;
        drawFish(ctx, (fx - 0.2) * w, (F.y + 0.015 * Math.sin(t * 0.3 + F.p)) * h, F.s * w, F.dir, 0.12 * Math.sin(t * 3 + F.p));
      }
      ctx.globalAlpha = 1;
      ctx.drawImage(bed, 0, 0, w, h);
      for (var k = 0; k < weed.length; k++) {
        var Wd = weed[k], bx = Wd.x * w, by = h * 0.93, len = Wd.len * h, wd = Wd.wd * w;
        var L = [], Rt = [];
        for (var s = 0; s <= 8; s++) {
          var v = s / 8;
          var sway = len * (0.16 * Math.sin(t * Wd.f * 0.6 + Wd.p) + 0.05 * Math.sin(t * Wd.f * 1.7 + v * 3 + Wd.p)) * Math.pow(v, 1.5);
          var cx = bx + sway, cy = by - v * len, half = wd * (1 - v * 0.85);
          L.push(cx - half, cy);
          Rt.push(cx + half, cy);
        }
        ctx.fillStyle = U.rgba(weedCols[Wd.c], 0.92);
        ctx.beginPath();
        ctx.moveTo(L[0], L[1]);
        for (var q = 2; q < L.length; q += 2) ctx.lineTo(L[q], L[q + 1]);
        for (var z = Rt.length - 2; z >= 0; z -= 2) ctx.lineTo(Rt[z], Rt[z + 1]);
        ctx.closePath();
        ctx.fill();
      }
      for (var m = 0; m < bubbles.length; m++) {
        var B = bubbles[m];
        var u = (t * B.v + B.ph) % 1;
        var r = B.r * h * (0.8 + 0.4 * u);
        var bxp = (B.x + B.wa * Math.sin(t * B.wf + B.wp) * u) * w, byp = h * (0.93 - u * 1.0);
        ctx.globalAlpha = Math.min(1, u * 6) * (light ? 0.85 : 0.7);
        ctx.drawImage(bubSpr, bxp - r, byp - r, r * 2, r * 2);
      }
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = bed = raySpr = bubSpr = rays = fish = weed = bubbles = null;
    },
  });
})();
