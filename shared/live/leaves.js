/* live: Leaves | Autumn leaves tumbling down through a low, hazy amber sun */
(function () {
  var U = ForgeLive.util;
  var bg, sprites, mote, leaves, motes, accent, light, W, H;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    light = o.mode === "light";
  }
  function radial(size, col, soft) {
    var c = U.layer(size, size), g = c.getContext("2d"), r = size / 2;
    var gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, U.rgba(col, 1));
    gr.addColorStop(soft, U.rgba(col, 0.5));
    gr.addColorStop(1, U.rgba(col, 0));
    g.fillStyle = gr;
    g.fillRect(0, 0, size, size);
    return c;
  }
  // one leaf sprite, pointing up; kind 0 is an oval leaf, 1 a five-lobed maple
  function leaf(col, kind) {
    var S = 64, c = U.layer(S, S), g = c.getContext("2d");
    g.translate(S / 2, S / 2);
    g.beginPath();
    if (kind === 0) {
      g.moveTo(0, -28);
      g.quadraticCurveTo(20, -8, 0, 24);
      g.quadraticCurveTo(-20, -8, 0, -28);
    } else {
      for (var k = 0; k <= 60; k++) {
        var th = (k / 60) * 6.2832;
        var lobe = Math.pow(Math.abs(Math.cos(2.5 * (th + Math.PI / 2))), 0.7);
        var r = 26 * (0.5 + 0.5 * lobe) * (th > 1.2 && th < 1.95 ? 0.6 : 1);
        var px = Math.cos(th) * r, py = -Math.sin(th) * r * 0.95;
        if (k) g.lineTo(px, py);
        else g.moveTo(px, py);
      }
      g.closePath();
    }
    var gr = g.createLinearGradient(-20, -20, 20, 20);
    gr.addColorStop(0, U.rgba(U.mix(col, [255, 230, 160], 0.25)));
    gr.addColorStop(1, U.rgba(U.mix(col, [40, 10, 0], 0.25)));
    g.fillStyle = gr;
    g.fill();
    g.strokeStyle = U.rgba(U.mix(col, [40, 10, 0], 0.45), 0.8);
    g.lineWidth = 1.2;
    g.beginPath();
    g.moveTo(0, 30);
    g.lineTo(0, -20);
    if (kind === 1) {
      g.moveTo(0, 4);
      g.lineTo(-15, -10);
      g.moveTo(0, 4);
      g.lineTo(15, -10);
    }
    g.stroke();
    return c;
  }
  function paint(w, h) {
    W = w;
    H = h;
    bg = U.layer(w, h);
    var g = bg.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, h);
    if (light) {
      lin.addColorStop(0, "rgb(236,222,200)");
      lin.addColorStop(0.6, "rgb(246,224,186)");
      lin.addColorStop(1, "rgb(222,184,140)");
    } else {
      lin.addColorStop(0, U.rgba(U.mix([22, 12, 12], accent, 0.05)));
      lin.addColorStop(0.55, "rgb(58,28,16)");
      lin.addColorStop(0.85, "rgb(104,52,22)");
      lin.addColorStop(1, "rgb(70,32,16)");
    }
    g.fillStyle = lin;
    g.fillRect(0, 0, w, h);
    // the low sun and its haze
    var sx = w * 0.72, sy = h * 0.7;
    var s = g.createRadialGradient(sx, sy, 0, sx, sy, h * 0.9);
    s.addColorStop(0, light ? "rgba(255,240,200,0.85)" : "rgba(255,190,100,0.5)");
    s.addColorStop(0.25, light ? "rgba(255,214,150,0.35)" : "rgba(230,130,50,0.2)");
    s.addColorStop(1, "rgba(200,100,40,0)");
    g.fillStyle = s;
    g.fillRect(0, 0, w, h);
    // faint sun shafts
    g.save();
    g.globalCompositeOperation = "lighter";
    for (var k = 0; k < 6; k++) {
      var ang = -2.2 + k * 0.22;
      var sh = g.createLinearGradient(sx, sy, sx + Math.cos(ang) * w, sy + Math.sin(ang) * w);
      sh.addColorStop(0, light ? "rgba(255,240,210,0.12)" : "rgba(255,170,80,0.06)");
      sh.addColorStop(1, "rgba(255,170,80,0)");
      g.fillStyle = sh;
      g.beginPath();
      g.moveTo(sx, sy);
      g.lineTo(sx + Math.cos(ang - 0.04) * w * 1.5, sy + Math.sin(ang - 0.04) * w * 1.5);
      g.lineTo(sx + Math.cos(ang + 0.04) * w * 1.5, sy + Math.sin(ang + 0.04) * w * 1.5);
      g.closePath();
      g.fill();
    }
    g.restore();
    // blurred canopy at the top corners and leaf litter below
    var rnd = U.rng(307);
    var canopy = light ? [150, 80, 40] : [30, 12, 8];
    for (var i = 0; i < 70; i++) {
      var left = i % 2 === 0;
      var cx = (left ? rnd() * 0.35 : 1 - rnd() * 0.35) * w;
      var cy = rnd() * rnd() * h * 0.35;
      var r = h * (0.05 + rnd() * 0.1);
      var cg = g.createRadialGradient(cx, cy, 0, cx, cy, r);
      var cc = U.mix(canopy, [200, 90, 30], rnd() * 0.4);
      cg.addColorStop(0, U.rgba(cc, light ? 0.18 : 0.35));
      cg.addColorStop(1, U.rgba(cc, 0));
      g.fillStyle = cg;
      g.fillRect(cx - r, cy - r, r * 2, r * 2);
    }
    for (var j = 0; j < 260; j++) {
      var lx = rnd() * w, ly = h * (0.9 + rnd() * 0.12);
      g.fillStyle = U.rgba(U.mix([170, 70, 25], [230, 160, 60], rnd()), (light ? 0.25 : 0.18) + rnd() * 0.15);
      g.beginPath();
      g.ellipse(lx, ly, h * 0.008, h * 0.004, rnd() * 3, 0, 6.2832);
      g.fill();
    }
    var v = g.createRadialGradient(w / 2, h * 0.55, h * 0.35, w / 2, h * 0.55, w * 0.75);
    v.addColorStop(0, "rgba(0,0,0,0)");
    v.addColorStop(1, light ? "rgba(120,60,20,0.18)" : "rgba(0,0,0,0.5)");
    g.fillStyle = v;
    g.fillRect(0, 0, w, h);
    var cols = [[214, 120, 40], [176, 64, 30], [230, 170, 60], [140, 48, 30], U.mix(accent, [200, 110, 50], 0.55)];
    sprites = [];
    for (var c = 0; c < cols.length; c++) sprites.push(leaf(cols[c], 0), leaf(cols[c], 1));
    mote = radial(32, [255, 214, 150], 0.3);
  }
  function build(w, h, o) {
    var rnd = U.rng(311);
    leaves = [];
    var n = o.lite ? 16 : 32;
    for (var i = 0; i < n; i++) {
      var z = rnd();
      leaves.push({
        x: rnd(), y: rnd() * 1.25, v: 0.035 + z * 0.05, s: 0.018 + z * z * 0.035, a: 0.55 + z * 0.45,
        sa: 0.03 + rnd() * 0.06, sf: 0.3 + rnd() * 0.4, sp: rnd() * 6.28, rot: rnd() * 6.28,
        spin: (rnd() - 0.5) * 1.2, flip: 0.6 + rnd() * 1.4, fp: rnd() * 6.28, spr: Math.floor(rnd() * 10),
        d: 0.006 + rnd() * 0.01, z: z,
      });
    }
    leaves.sort(function (a, b) {
      return a.z - b.z;
    });
    motes = [];
    for (var j = 0; j < (o.lite ? 15 : 30); j++) {
      motes.push({ x: 0.45 + rnd() * 0.5, y: 0.3 + rnd() * 0.6, ax: 0.02 + rnd() * 0.04, ay: 0.02 + rnd() * 0.04, f: 0.05 + rnd() * 0.1, p: rnd() * 6.28, r: 1 + rnd() * 2.5 });
    }
    paint(w, h);
  }

  ForgeLive.scene("leaves", {
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
      for (var j = 0; j < motes.length; j++) {
        var m = motes[j];
        var mx = (m.x + m.ax * Math.sin(t * m.f + m.p)) * w, my = (m.y + m.ay * Math.sin(t * m.f * 1.3 + m.p * 2)) * h;
        ctx.globalAlpha = 0.25 + 0.2 * Math.sin(t * 0.7 + m.p);
        ctx.drawImage(mote, mx - m.r * 3, my - m.r * 3, m.r * 6, m.r * 6);
      }
      ctx.globalCompositeOperation = "source-over";
      for (var i = 0; i < leaves.length; i++) {
        var L = leaves[i];
        var y = (((L.y + L.v * t) % 1.25) - 0.12) * h;
        var x = (L.x + L.d * t + L.sa * Math.sin(t * L.sf + L.sp)) % 1;
        if (x < 0) x += 1;
        x = (x * 1.2 - 0.1) * w;
        var flip = Math.cos(t * L.flip + L.fp);
        var sx = (flip < 0 ? -1 : 1) * Math.max(0.15, Math.abs(flip));
        var rot = L.rot + L.spin * t + 0.6 * Math.sin(t * L.sf + L.sp);
        var s = L.s * h;
        ctx.globalAlpha = L.a * (flip < 0 ? 0.8 : 1);
        ctx.setTransform(Math.cos(rot) * sx, Math.sin(rot) * sx, -Math.sin(rot), Math.cos(rot), x, y);
        ctx.drawImage(sprites[L.spr], -s, -s, s * 2, s * 2);
      }
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.globalAlpha = 1;
    },
    stop: function () {
      bg = sprites = mote = leaves = motes = null;
    },
  });
})();
