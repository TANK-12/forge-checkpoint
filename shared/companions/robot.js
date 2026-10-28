/* companion: Robot | A small round-wheeled robot that rolls along the bottom edge, scans about, waves and powers down for a nap */
(function () {
  var U = ForgeLive.util;
  var BW = 64, BH = 76; // the robot's own small canvas, CSS px
  var FPS = 12;
  var POSES = { roll: 1, scan: 1, wave: 1, sleep: 1 };

  /* ---------- drawing ---------- */
  function palette(o) {
    var accent = U.hex(o.accent, "#6ea8fe");
    if (o.mode === "light") {
      return {
        body: U.mix([214, 220, 232], accent, 0.12), dark: [92, 100, 120], line: "rgba(40,46,66,0.75)",
        face: [34, 40, 58], eye: U.mix([120, 230, 255], accent, 0.35), glow: "rgba(0,0,0,0)",
      };
    }
    return {
      body: U.mix([150, 160, 182], accent, 0.18), dark: [62, 68, 88], line: "rgba(10,12,22,0.85)",
      face: [18, 22, 34], eye: U.mix([130, 240, 255], accent, 0.4), glow: U.rgba(accent, 0.55),
    };
  }
  // f: frame 0..11 (wheel spin); eyes: open | closed | scan; look: -1..1; arm: 0 down .. 1 up; lamp: 0..1
  function draw(cv, f, eyes, look, arm, lamp, pal) {
    var g = cv.getContext("2d");
    var dpr = cv.width / BW;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.clearRect(0, 0, cv.width, cv.height);
    g.setTransform(dpr, 0, 0, dpr, 32 * dpr, 0);
    g.lineWidth = 1.6;
    g.lineJoin = "round";
    g.strokeStyle = pal.line;
    function rr(x, y, w, h, r) {
      g.beginPath();
      g.moveTo(x + r, y);
      g.arcTo(x + w, y, x + w, y + h, r);
      g.arcTo(x + w, y + h, x, y + h, r);
      g.arcTo(x, y + h, x, y, r);
      g.arcTo(x, y, x + w, y, r);
      g.closePath();
    }
    // wheel with spokes that turn
    var spin = (f / 12) * 6.2832;
    g.fillStyle = U.rgba(pal.dark, 1);
    g.beginPath();
    g.arc(0, 64, 9, 0, 6.2832);
    g.fill();
    g.stroke();
    g.strokeStyle = U.rgba(pal.body, 0.9);
    g.beginPath();
    for (var i = 0; i < 3; i++) {
      var a = spin + (i * 6.2832) / 3;
      g.moveTo(0, 64);
      g.lineTo(Math.cos(a) * 7, 64 + Math.sin(a) * 7);
    }
    g.stroke();
    g.strokeStyle = pal.line;
    // body
    var grad = g.createLinearGradient(0, 30, 0, 58);
    grad.addColorStop(0, U.rgba(U.mix(pal.body, [255, 255, 255], 0.25), 1));
    grad.addColorStop(1, U.rgba(pal.body, 1));
    g.fillStyle = grad;
    rr(-14, 34, 28, 22, 6);
    g.fill();
    g.stroke();
    // chest light
    g.fillStyle = U.rgba(pal.eye, 0.35 + lamp * 0.6);
    g.beginPath();
    g.arc(0, 45, 3, 0, 6.2832);
    g.fill();
    // arms: the near one waves
    g.strokeStyle = U.rgba(pal.dark, 1);
    g.lineWidth = 3;
    g.lineCap = "round";
    g.beginPath();
    g.moveTo(-14, 40);
    g.lineTo(-19, 50);
    var aa = 1.1 - arm * 2.3 + (arm > 0.5 ? Math.sin(spin * 2) * 0.35 : 0);
    g.moveTo(14, 40);
    g.lineTo(14 + Math.cos(aa) * 11, 40 + Math.sin(aa) * 11);
    g.stroke();
    g.lineWidth = 1.6;
    g.strokeStyle = pal.line;
    // neck and head, turned by look
    var hx = look * 3;
    g.fillStyle = U.rgba(pal.dark, 1);
    g.fillRect(-3, 29, 6, 6);
    g.fillStyle = grad;
    rr(-15 + hx, 10, 30, 20, 7);
    g.fill();
    g.stroke();
    // antenna with its lamp
    g.beginPath();
    g.moveTo(hx, 10);
    g.lineTo(hx, 3);
    g.stroke();
    g.shadowColor = pal.glow;
    g.shadowBlur = lamp > 0.5 ? 8 * dpr : 0;
    g.fillStyle = lamp > 0.5 ? U.rgba(pal.eye, 1) : U.rgba(pal.dark, 1);
    g.beginPath();
    g.arc(hx, 3, 2.6, 0, 6.2832);
    g.fill();
    g.shadowBlur = 0;
    // face screen
    g.fillStyle = U.rgba(pal.face, 1);
    rr(-11 + hx, 14, 22, 12, 4);
    g.fill();
    g.fillStyle = U.rgba(pal.eye, 1);
    g.strokeStyle = U.rgba(pal.eye, 1);
    var ex = hx + look * 3;
    if (eyes === "closed") {
      g.lineWidth = 1.4;
      g.beginPath();
      g.moveTo(ex - 7, 20);
      g.lineTo(ex - 3, 20);
      g.moveTo(ex + 3, 20);
      g.lineTo(ex + 7, 20);
      g.stroke();
    } else if (eyes === "scan") {
      g.fillRect(ex - 8 + ((f % 6) / 5) * 12, 18, 4, 4);
    } else {
      g.fillRect(ex - 7, 17, 4, 5);
      g.fillRect(ex + 3, 17, 4, 5);
    }
  }

  /* ---------- behaviour ---------- */
  function rand(a, b) {
    return a + Math.random() * (b - a);
  }
  function pick(table) {
    var r = Math.random(), acc = 0;
    for (var k in table) {
      acc += table[k];
      if (r < acc) return k;
    }
    return k;
  }

  ForgeLive.companion("robot", {
    lighter: { balanced: "", light: "still" },
    start: function (layer, opts) {
      var o = opts || {};
      var cv = document.createElement("canvas");
      var dpr = Math.min(2, window.devicePixelRatio || 1);
      cv.width = Math.round(BW * dpr);
      cv.height = Math.round(BH * dpr);
      cv.className = "forge-robot";
      cv.setAttribute("aria-hidden", "true");
      cv.style.cssText =
        "position:absolute;left:0;top:0;width:" + BW + "px;height:" + BH +
        "px;pointer-events:none;will-change:transform;transition:opacity 1.2s ease;opacity:0.94";
      layer.appendChild(cv);

      var pal = palette(o);
      var x = 0, tx = 0, dir = 1, look = 0, arm = 0, lamp = 0;
      var act = "idle", until = 0, timer = 0, frozen = false, stopped = false;
      var frame = 0, eyes = "open", drawn = "";

      function width() {
        return Math.max(BW * 3, layer.clientWidth || window.innerWidth || 800);
      }
      function floorY() {
        var h = Math.max(BH * 2, layer.clientHeight || window.innerHeight || 600);
        return h - Math.max(0, +o.bottom || 0) - BH;
      }
      function place() {
        x = Math.max(0, Math.min(width() - BW, x));
        cv.style.transform =
          "translate3d(" + Math.round(x) + "px," + Math.round(floorY()) + "px,0) scaleX(" + dir + ")";
      }
      function paint(force) {
        var key = frame + ":" + eyes + ":" + look.toFixed(1) + ":" + arm.toFixed(2) + ":" + (lamp > 0.5);
        if (!force && key === drawn) return;
        drawn = key;
        draw(cv, frame, eyes, look, arm, lamp, pal);
      }
      function staticMode() {
        return o.animations === false || !!o.pose;
      }
      function begin(name, secs) {
        act = name;
        until = performance.now() + secs * 1000;
        eyes = name === "sleep" ? "closed" : name === "scan" ? "scan" : "open";
        if (name === "roll") {
          tx = rand(0.05, 0.9) * (width() - BW);
          dir = tx >= x ? 1 : -1;
        }
        cv.style.opacity = name === "sleep" ? "0.7" : "0.94";
      }
      function next() {
        var c = act === "roll"
          ? pick({ scan: 0.35, wave: 0.15, idle: 0.3, sleep: 0.2 })
          : act === "sleep"
            ? "roll"
            : pick({ roll: 0.75, scan: 0.1, sleep: 0.15 });
        if (c === "roll") begin("roll", 30);
        else if (c === "scan") begin("scan", rand(2.5, 4.5));
        else if (c === "wave") begin("wave", 2.2);
        else if (c === "idle") begin("idle", rand(2, 5));
        else begin("sleep", rand(8, 20));
      }
      function tick() {
        timer = 0;
        if (stopped || frozen || staticMode() || document.hidden) return;
        var now = performance.now();
        if (now >= until) next();
        if (act === "roll") {
          var d = tx - x;
          if (Math.abs(d) < 2) begin(pick({ idle: 0.5, scan: 0.3, wave: 0.2 }), rand(2, 4));
          else {
            x += Math.sign(d) * Math.min(Math.abs(d), 36 / FPS);
            frame = (frame + 1) % 12;
          }
        }
        var t = (now / 1000) % 60;
        look = act === "scan" ? Math.sin(t * 2.4) : look * 0.8;
        arm += ((act === "wave" ? 1 : 0) - arm) * 0.35;
        if (act === "wave") frame = (frame + 1) % 12;
        lamp = act === "sleep" ? (Math.sin(t * 1.2) > 0.6 ? 0.6 : 0) : Math.sin(t * 3) > 0.2 ? 1 : 0;
        if (act === "idle" && eyes === "open" && Math.random() < 0.03) {
          eyes = "closed";
          setTimeout(function () {
            if (eyes === "closed" && act === "idle") eyes = "open";
          }, 160);
        }
        place();
        paint(false);
        timer = setTimeout(tick, act === "sleep" ? 500 : 1000 / FPS);
      }
      function schedule() {
        if (timer) clearTimeout(timer);
        timer = 0;
        if (!stopped && !frozen && !staticMode() && !document.hidden) timer = setTimeout(tick, 1000 / FPS);
      }
      function still() {
        var p = o.pose && POSES[o.pose] ? o.pose : "roll";
        x = Math.round((width() - BW) * 0.3);
        dir = 1;
        frame = 2;
        act = p;
        eyes = p === "sleep" ? "closed" : p === "scan" ? "scan" : "open";
        look = p === "scan" ? 0.8 : 0;
        arm = p === "wave" ? 1 : 0;
        lamp = p === "sleep" ? 0 : 1;
        cv.style.transition = "none";
        cv.style.opacity = p === "sleep" ? "0.7" : "0.94";
        place();
        paint(true);
      }
      function onResize() {
        place();
      }
      document.addEventListener("visibilitychange", schedule);
      window.addEventListener("resize", onResize);

      if (staticMode()) still();
      else {
        x = rand(0.1, 0.8) * (width() - BW);
        begin("idle", rand(1, 2.5));
        place();
        paint(true);
        schedule();
      }

      return {
        stop: function () {
          stopped = true;
          if (timer) clearTimeout(timer);
          document.removeEventListener("visibilitychange", schedule);
          window.removeEventListener("resize", onResize);
          if (cv.parentNode) cv.parentNode.removeChild(cv);
        },
        update: function (n) {
          var was = staticMode();
          o = n || {};
          pal = palette(o);
          if (staticMode()) still();
          else {
            if (was) {
              cv.style.transition = "opacity 1.2s ease";
              begin("idle", 1);
            }
            place();
            paint(true);
            schedule();
          }
        },
        still: function (on) {
          frozen = !!on;
          schedule();
        },
      };
    },
  });
})();
