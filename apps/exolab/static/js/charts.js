// Canvas charts for the bench: a line chart with limit lines and a time
// cursor, the shoulder range map (plane of elevation x elevation), and the
// materials chart (stiffness per weight against strength per weight).

const INK = "#e7e9ee";
const MUTED = "#8b93a3";
const GRID = "#262c37";
const LEVEL = { pass: "#59d499", warn: "#f2a154", fail: "#f2637d", out: "#1a1f28" };

function prep(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 300;
  const hgt = canvas.clientHeight || 160;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(hgt * dpr);
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, hgt);
  ctx.font = "11px system-ui, sans-serif";
  return { ctx, w, hgt };
}

function niceStep(span, n) {
  const raw = span / Math.max(1, n);
  const p = 10 ** Math.floor(Math.log10(raw || 1));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p;
}

// Pixels between two limit lines below which their labels share one row.
const LABEL_ROW = 12;

/** The limit lines' labels, at the right end above their line. Lines closer
 *  than a text row (two motors with the same rating) put their labels side
 *  by side on one row, right to left, instead of printing them over each
 *  other. Returns where each label went, for tests/js/charts_labels.mjs. */
export function limitLabels(ctx, lines, Y, right) {
  const tagged = lines
    .filter((l) => l.label && Number.isFinite(l.y))
    .map((l) => ({ l, y: Y(l.y) }))
    .sort((a, b) => a.y - b.y);
  const placed = [];
  let rowY = -Infinity;
  let x = right;
  ctx.textAlign = "right";
  ctx.textBaseline = "bottom";
  for (const { l, y } of tagged) {
    if (y - rowY >= LABEL_ROW) {
      rowY = y;
      x = right;
    }
    const width = ctx.measureText(l.label).width;
    ctx.fillStyle = l.color;
    ctx.fillText(l.label, x, rowY - 1);
    placed.push({ label: l.label, x0: x - width, x1: x, y: rowY - 1 });
    x -= width + 10;
  }
  return placed;
}

/** series: [{name, color, values, dash}], lines: [{y, color, label}]. */
export function lineChart(canvas, { t, series, lines = [], cursor = null, unit = "", xlabel = "s" }) {
  const { ctx, w, hgt } = prep(canvas);
  const pad = { l: 40, r: 10, t: 22, b: 20 };
  const xs = t && t.length ? t : [0, 1];
  const x0 = xs[0];
  const x1 = xs[xs.length - 1] > x0 ? xs[xs.length - 1] : x0 + 1;
  let lo = 0;
  let hi = 0;
  for (const s of series) for (const v of s.values) if (Number.isFinite(v)) (lo = Math.min(lo, v)), (hi = Math.max(hi, v));
  for (const l of lines) if (Number.isFinite(l.y)) (lo = Math.min(lo, l.y)), (hi = Math.max(hi, l.y));
  if (hi - lo < 1e-9) hi = lo + 1;
  hi += (hi - lo) * 0.08;
  const X = (x) => pad.l + ((x - x0) / (x1 - x0)) * (w - pad.l - pad.r);
  const Y = (y) => hgt - pad.b - ((y - lo) / (hi - lo)) * (hgt - pad.t - pad.b);
  const step = niceStep(hi - lo, 4);
  ctx.strokeStyle = GRID;
  ctx.fillStyle = MUTED;
  ctx.lineWidth = 1;
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let y = Math.ceil(lo / step) * step; y <= hi; y += step) {
    ctx.beginPath();
    ctx.moveTo(pad.l, Y(y));
    ctx.lineTo(w - pad.r, Y(y));
    ctx.stroke();
    ctx.fillText(`${+y.toFixed(6)}`, pad.l - 5, Y(y));
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  const xstep = niceStep(x1 - x0, 6);
  for (let x = Math.ceil(x0 / xstep) * xstep; x <= x1 + 1e-9; x += xstep) {
    ctx.fillText(`${+x.toFixed(3)}${x === 0 ? "" : ""}`, X(x), hgt - pad.b + 4);
  }
  ctx.textAlign = "left";
  ctx.fillText(unit, 4, 4);
  ctx.textAlign = "right";
  ctx.fillText(xlabel, w - pad.r, hgt - pad.b + 4);
  for (const l of lines) {
    ctx.strokeStyle = l.color;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l, Y(l.y));
    ctx.lineTo(w - pad.r, Y(l.y));
    ctx.stroke();
    ctx.setLineDash([]);
  }
  limitLabels(ctx, lines, Y, w - pad.r - 2);
  for (const s of series) {
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1.8;
    ctx.setLineDash(s.dash ? [4, 3] : []);
    ctx.beginPath();
    s.values.forEach((v, i) => {
      const x = X(xs[i] ?? i);
      if (i === 0) ctx.moveTo(x, Y(v));
      else ctx.lineTo(x, Y(v));
    });
    ctx.stroke();
  }
  ctx.setLineDash([]);
  let lx = pad.l;
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  for (const s of series) {
    ctx.fillStyle = s.color;
    ctx.fillRect(lx, 7, 9, 3);
    ctx.fillStyle = INK;
    ctx.fillText(s.name, lx + 12, 3);
    lx += 18 + ctx.measureText(s.name).width;
  }
  if (cursor != null && Number.isFinite(cursor)) {
    ctx.strokeStyle = "rgba(255,255,255,0.55)";
    ctx.beginPath();
    ctx.moveTo(X(cursor), pad.t);
    ctx.lineTo(X(cursor), hgt - pad.b);
    ctx.stroke();
  }
}

/** The range map; returns pick(x, y) -> cell under a mouse position. */
export function romMap(canvas, map, mark) {
  const { ctx, w, hgt } = prep(canvas);
  const pad = { l: 34, r: 8, t: 8, b: 26 };
  const planes = map.planes;
  const elevs = map.elevs;
  const cw = (w - pad.l - pad.r) / planes.length;
  const ch = (hgt - pad.t - pad.b) / elevs.length;
  const pi = new Map(planes.map((p, i) => [p, i]));
  const ei = new Map(elevs.map((e, i) => [e, i]));
  const at = (c) => [pad.l + pi.get(c.plane) * cw, hgt - pad.b - (ei.get(c.elev) + 1) * ch];
  for (const c of map.cells) {
    if (!pi.has(c.plane) || !ei.has(c.elev)) continue;
    const [x, y] = at(c);
    ctx.fillStyle = LEVEL[c.level] || LEVEL.out;
    ctx.globalAlpha = c.level === "out" ? 1 : 0.88;
    ctx.fillRect(x + 0.5, y + 0.5, cw - 1, ch - 1);
  }
  ctx.globalAlpha = 1;
  if (mark) {
    const near = (arr, v) => arr.reduce((b, x, i) => (Math.abs(x - v) < Math.abs(arr[b] - v) ? i : b), 0);
    const x = pad.l + near(planes, mark.plane) * cw;
    const y = hgt - pad.b - (near(elevs, mark.elev) + 1) * ch;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.strokeRect(x + 1, y + 1, cw - 2, ch - 2);
  }
  ctx.fillStyle = MUTED;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  planes.forEach((p, i) => {
    if (p % 45 === 0) ctx.fillText(`${p}°`, pad.l + (i + 0.5) * cw, hgt - pad.b + 3);
  });
  ctx.fillText("plane: sideways 0° · forward 90° · across 135°+", pad.l + (w - pad.l - pad.r) / 2, hgt - 11);
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  elevs.forEach((e, i) => {
    if (e % 45 === 0) ctx.fillText(`${e}°`, pad.l - 4, hgt - pad.b - (i + 0.5) * ch);
  });
  return (mx, my) => {
    const i = Math.floor((mx - pad.l) / cw);
    const j = Math.floor((hgt - pad.b - my) / ch);
    if (i < 0 || j < 0 || i >= planes.length || j >= elevs.length) return null;
    return map.cells.find((c) => c.plane === planes[i] && c.elev === elevs[j]) || null;
  };
}

/** Materials on log axes: E/rho (MJ/kg) against yield/rho (kJ/kg). The
 *  baseline sits as a ring, the edited value as a dot, joined by a line. */
export function ashby(canvas, mats) {
  const { ctx, w, hgt } = prep(canvas);
  const pad = { l: 40, r: 10, t: 10, b: 28 };
  const pts = mats.flatMap((m) => [m.base, m.now]);
  const xs = pts.map((p) => Math.log10(p[0]));
  const ys = pts.map((p) => Math.log10(p[1]));
  const xl = Math.floor(Math.min(...xs) * 2) / 2 - 0.1;
  const xh = Math.ceil(Math.max(...xs) * 2) / 2 + 0.1;
  const yl = Math.floor(Math.min(...ys) * 2) / 2 - 0.1;
  const yh = Math.ceil(Math.max(...ys) * 2) / 2 + 0.1;
  const X = (v) => pad.l + ((Math.log10(v) - xl) / (xh - xl)) * (w - pad.l - pad.r);
  const Y = (v) => hgt - pad.b - ((Math.log10(v) - yl) / (yh - yl)) * (hgt - pad.t - pad.b);
  ctx.strokeStyle = GRID;
  ctx.fillStyle = MUTED;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let e = Math.ceil(xl); e <= xh; e++) {
    ctx.beginPath();
    ctx.moveTo(X(10 ** e), pad.t);
    ctx.lineTo(X(10 ** e), hgt - pad.b);
    ctx.stroke();
    ctx.fillText(`${10 ** e}`, X(10 ** e), hgt - pad.b + 3);
  }
  ctx.fillText("stiffness per weight, E/ρ (MJ/kg)", pad.l + (w - pad.l - pad.r) / 2, hgt - 13);
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (let e = Math.ceil(yl); e <= yh; e++) {
    ctx.beginPath();
    ctx.moveTo(pad.l, Y(10 ** e));
    ctx.lineTo(w - pad.r, Y(10 ** e));
    ctx.stroke();
    ctx.fillText(`${10 ** e}`, pad.l - 4, Y(10 ** e));
  }
  ctx.save();
  ctx.translate(10, pad.t + (hgt - pad.t - pad.b) / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.fillText("strength per weight (kJ/kg)", 0, 0);
  ctx.restore();
  ctx.textAlign = "left";
  ctx.textBaseline = "middle";
  for (const m of mats) {
    const moved = Math.abs(m.base[0] - m.now[0]) > 1e-9 || Math.abs(m.base[1] - m.now[1]) > 1e-9;
    if (moved) {
      ctx.strokeStyle = m.colour;
      ctx.globalAlpha = 0.6;
      ctx.beginPath();
      ctx.arc(X(m.base[0]), Y(m.base[1]), 4, 0, Math.PI * 2);
      ctx.moveTo(X(m.base[0]), Y(m.base[1]));
      ctx.lineTo(X(m.now[0]), Y(m.now[1]));
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
    ctx.fillStyle = m.colour;
    ctx.beginPath();
    ctx.arc(X(m.now[0]), Y(m.now[1]), m.hot ? 5.5 : 4, 0, Math.PI * 2);
    ctx.fill();
    if (m.hot) {
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    }
  }
  // Labels: the touched material first, each on the side that fits inside
  // the plot, and none drawn over one already placed.
  const placed = [];
  for (const m of [...mats].sort((a, b) => Number(!!b.hot) - Number(!!a.hot))) {
    const x = X(m.now[0]);
    const y = Y(m.now[1]);
    const tw = ctx.measureText(m.short).width;
    const x0 = x + 7 + tw <= w - pad.r ? x + 7 : x - 7 - tw;
    const box = [x0 - 2, y - 7, x0 + tw + 2, y + 7];
    if (placed.some((b) => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) continue;
    placed.push(box);
    ctx.fillStyle = m.hot ? INK : MUTED;
    ctx.fillText(m.short, x0, y);
  }
}
