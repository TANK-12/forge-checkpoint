/* live: Synthwave | A neon perspective grid scrolling toward a striped sun */
(function () {
  var U = ForgeLive.util;
  var sky, floor, sunSpr, sunCut, accent, neon, hz;

  function colours(o) {
    accent = U.hex(o.accent, "#6ea8fe");
    neon = U.mix([255, 60, 200], accent, 0.45);
  }
  function paint(w, h) {
    hz = Math.round(h * 0.6);
    sky = U.layer(w, h);
    var g = sky.getContext("2d");
    var lin = g.createLinearGradient(0, 0, 0, hz);
    lin.addColorStop(0, U.rgba(U.mix([10, 4, 30], accent, 0.12)));
    lin.addColorStop(0.6, U.rgba(U.mix([60, 10, 80], accent, 0.12)));
    lin.addColorStop(1, U.rgba(U.mix([200, 50, 120], neon, 0.3)));
    g.fillStyle = lin;
    g.fillRect(0, 0, w, hz + 1);
    var rnd = U.rng(13);
    for (var s = 0; s < 160; s++) {
      var y = rnd() * hz * 0.7;
      g.fillStyle = "rgba(255,230,255," + (0.2 + rnd() * 0.6) * (1 - y / (hz * 0.7)) + ")";
      var z = rnd() < 0.1 ? 2 : 1.2;
      g.fillRect(rnd() * w, y, z, z);
    }
    // a glow where the sun meets the horizon
    var hg = g.createRadialGradient(w / 2, hz, 0, w / 2, hz, w * 0.45);
    hg.addColorStop(0, "rgba(255,120,170,0.35)");
    hg.addColorStop(1, "rgba(255,120,170,0)");
    g.fillStyle = hg;
    g.fillRect(0, 0, w, hz);
    // the sun: yellow to pink, cut into stripes per frame
    var sr = Math.round(Math.min(w, h) * 0.24);
    sunSpr = U.layer(sr * 2, sr * 2);
    var sg = sunSpr.getContext("2d");
    var sl = sg.createLinearGradient(0, 0, 0, sr * 2);
    sl.addColorStop(0, "rgb(255,236,120)");
    sl.addColorStop(0.5, "rgb(255,150,110)");
    sl.addColorStop(1, U.rgba(neon));
    sg.fillStyle = sl;
    sg.beginPath();
    sg.arc(sr, sr, sr, 0, 6.2832);
    sg.fill();
    sunCut = U.layer(sr * 2, sr * 2);
    // mountains in front of the sun, with a neon rim
    var mr = U.rng(29);
    var pts = [];
    for (var i = 0; i <= 40; i++) {
      var u = i / 40;
      var edge = Math.abs(u - 0.5) * 2; // low in the middle so the sun shows
      var m = (0.25 + 0.75 * edge) * (0.5 + mr() * 0.5);
      pts.push([u * w, hz - m * h * 0.12]);
    }
    floor = U.layer(w, h);
    var f = floor.getContext("2d");
    f.beginPath();
    f.moveTo(0, hz);
    for (var k = 0; k < pts.length; k++) f.lineTo(pts[k][0], pts[k][1]);
    f.lineTo(w, hz);
    f.closePath();
    f.fillStyle = U.rgba(U.mix([20, 6, 40], accent, 0.1));
    f.fill();
    f.strokeStyle = U.rgba(neon, 0.55);
    f.lineWidth = 1.5;
    f.beginPath();
    for (var q = 0; q < pts.length; q++) f[q ? "lineTo" : "moveTo"](pts[q][0], pts[q][1]);
    f.stroke();
    // the floor
    var fl = f.createLinearGradient(0, hz, 0, h);
    fl.addColorStop(0, U.rgba(U.mix([40, 8, 60], neon, 0.25)));
    fl.addColorStop(0.25, "rgb(14,4,26)");
    fl.addColorStop(1, "rgb(6,2,14)");
    f.fillStyle = fl;
    f.fillRect(0, hz, w, h - hz);
    // the lines running to the vanishing point never move: draw them once
    var cx = w / 2;
    for (var j = -24; j <= 24; j++) {
      var xb = cx + j * w * 0.07;
      var a = 0.55 * (1 - Math.abs(j) / 26);
      f.strokeStyle = U.rgba(neon, a * 0.25);
      f.lineWidth = 4;
      f.beginPath();
      f.moveTo(cx + j * 2, hz);
      f.lineTo(xb, h);
      f.stroke();
      f.strokeStyle = U.rgba(neon, a);
      f.lineWidth = 1.2;
      f.stroke();
    }
    f.fillStyle = U.rgba([255, 180, 230], 0.8);
    f.fillRect(0, hz - 1, w, 2);
  }

  ForgeLive.scene("synthwave", {
    lighter: { balanced: { fps: 0.5, res: 0.7 }, light: "still" },
    fps: 30,
    res: 0.6,
    start: function (ctx, w, h, o) {
      colours(o);
      paint(w, h);
    },
    resize: function (ctx, w, h) {
      paint(w, h);
    },
    update: function (o) {
      colours(o);
      paint(sky.width, sky.height);
    },
    frame: function (ctx, t, dt, w, h) {
      ctx.drawImage(sky, 0, 0, w, h);
      // the sun's stripes slide down slowly
      var d = sunSpr.width, r = d / 2;
      var g = sunCut.getContext("2d");
      g.globalCompositeOperation = "copy";
      g.drawImage(sunSpr, 0, 0);
      g.globalCompositeOperation = "destination-out";
      g.fillStyle = "#000";
      var off = (t * 6) % 22;
      for (var y = r * 0.9 + off - 22; y < d; y += 22) {
        if (y < r * 0.85) continue;
        var th = 2 + ((y - r) / r) * 9;
        g.fillRect(0, y, d, th);
      }
      g.globalCompositeOperation = "source-over";
      ctx.drawImage(sunCut, w / 2 - r, hz - r * 1.35);
      ctx.drawImage(floor, 0, 0, w, h);
      // rows of the grid come toward the viewer
      ctx.lineCap = "butt";
      var speed = 0.6, rows = 18, cam = h - hz;
      var ph = (t * speed) % 1;
      for (var i = rows; i >= 0; i--) {
        var z = i + 1 - ph;
        var y2 = hz + (cam * 0.5) / z;
        if (y2 > h + 4) continue;
        var near = Math.min(1, (y2 - hz) / (h - hz) * 1.6);
        ctx.strokeStyle = U.rgba(neon, 0.18 * near);
        ctx.lineWidth = 2 + near * 5;
        ctx.beginPath();
        ctx.moveTo(0, y2);
        ctx.lineTo(w, y2);
        ctx.stroke();
        ctx.strokeStyle = U.rgba(neon, 0.15 + 0.7 * near);
        ctx.lineWidth = 0.8 + near * 1.2;
        ctx.stroke();
      }
    },
    stop: function () {
      sky = floor = sunSpr = sunCut = null;
    },
  });
})();
