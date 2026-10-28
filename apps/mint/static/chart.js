/* Mint's charts: plain SVG, no library. A line chart (each line may carry a
 * p10-p90 band, which makes it a fan of futures) and a histogram, both with
 * a hover readout and a legend. Series colours come from the caller (the
 * plan paths' colours live in paths.json); words and numbers stay in text
 * colours, so a colour never carries meaning alone.
 *
 *   lineChart(host, {x, series, yFormat, xFormat, marker, height, label})
 *     x       ISO dates or numbers (years), one per point
 *     series  [{name, values, color, dash, band: [lo[], hi[]], guide}]
 *             guide: a reference line (a goal). It stretches the y range only
 *             while it is within GUIDE_REACH times the other lines' top; past
 *             that it is named above the chart, so the other lines stay readable.
 *     marker  {index, label}  a dashed upright line, e.g. where test years start
 *   histChart(host, {lo, hi, counts, mark, markLabel, label})
 *
 * Both redraw themselves when the host changes width.
 */

const NS = "http://www.w3.org/2000/svg";
const GUIDE_REACH = 2;

function svg(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  if (parent) parent.appendChild(n);
  return n;
}

function div(cls, text) {
  const n = document.createElement("div");
  n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}

export function money(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "–";
  return `${v < 0 ? "-" : ""}$${Math.round(Math.abs(v)).toLocaleString("en-AU")}`;
}

export function moneyShort(v) {
  const a = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(a >= 1e7 ? 0 : 1)}m`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k`;
  return `${sign}$${Math.round(a)}`;
}

function niceTicks(lo, hi, n = 4) {
  if (!(hi > lo)) hi = lo + 1;
  const raw = (hi - lo) / n;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  for (let v = Math.floor(lo / step) * step; v < hi + step; v += step) {
    out.push(Number(v.toFixed(10)));
    if (v >= hi) break;
  }
  return out;
}

function xTickIndexes(x, maxLabels) {
  const n = x.length;
  if (n < 2) return [0];
  if (typeof x[0] === "string") {
    // year starts; month starts when that gives fewer than three marks
    const starts = (len) => x.flatMap((d, i) => (i === 0 || d.slice(0, len) !== x[i - 1].slice(0, len) ? [i] : []));
    const years = starts(4);
    const marks = years.length < 3 ? starts(7) : years;
    const every = Math.ceil(marks.length / maxLabels);
    return marks.filter((_, k) => k % every === 0);
  }
  const every = Math.max(1, Math.ceil((n - 1) / maxLabels));
  const out = [];
  for (let i = 0; i < n; i += every) out.push(i);
  if (out[out.length - 1] !== n - 1 && n - 1 - out[out.length - 1] >= every / 2) out.push(n - 1);
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

// A date tick reads "2019" on year marks, "Mar" on month marks ("Mar 2026" on
// the first one and on each January).
function xTickText(v, monthly, first) {
  if (typeof v !== "string") return String(v);
  if (!monthly) return v.slice(0, 4);
  const m = MONTHS[Number(v.slice(5, 7)) - 1];
  return first || v.slice(5, 7) === "01" ? `${m} ${v.slice(0, 4)}` : m;
}

// Redraw on width changes; one observer per host.
function mount(host, draw) {
  host._mintDraw = draw;
  if (!host._mintObserver) {
    let last = 0;
    let frame = 0;
    host._mintObserver = new ResizeObserver(() => {
      const w = host.clientWidth;
      if (w && Math.abs(w - last) > 4) {
        last = w;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => host._mintDraw && host._mintDraw());
      }
    });
    host._mintObserver.observe(host);
  }
  draw();
}

function legend(host, series) {
  if (series.length < 2) return;
  const box = div("chart-legend");
  for (const s of series) {
    const item = div("chart-key");
    const sw = document.createElement("span");
    sw.className = s.dash ? "sw dash" : "sw";
    sw.style.setProperty("--c", s.color);
    item.append(sw, document.createTextNode(s.name));
    box.append(item);
  }
  host.append(box);
}

function tipBox(host) {
  const tip = div("chart-tip");
  tip.hidden = true;
  host.append(tip);
  return tip;
}

function showTip(host, tip, px, py, title, rows) {
  tip.replaceChildren(div("tip-title", title));
  for (const r of rows) {
    const row = div("tip-row");
    const sw = document.createElement("span");
    sw.className = r.dash ? "sw dash" : "sw";
    if (r.color) sw.style.setProperty("--c", r.color);
    row.append(sw, div("tip-name", r.name), div("tip-val", r.value));
    tip.append(row);
  }
  tip.hidden = false;
  const w = host.clientWidth;
  const tw = tip.offsetWidth;
  const left = px + 14 + tw > w ? Math.max(0, px - 14 - tw) : px + 14;
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(0, py - tip.offsetHeight / 2)}px`;
}

export function lineChart(host, opts) {
  const { x, series } = opts;
  const yFormat = opts.yFormat || moneyShort;
  const tipFormat = opts.tipFormat || money;
  const xFormat = opts.xFormat || ((v) => String(v));
  const height = opts.height || 260;
  mount(host, () => {
    host.replaceChildren();
    host.classList.add("chart");
    legend(host, series);
    const width = Math.max(260, host.clientWidth || 600);
    const labelled = series.length <= 4 && width >= 480 && opts.endLabels !== false;
    const span = (list) => {
      let a = Infinity;
      let b = -Infinity;
      for (const s of list) {
        for (const arr of [s.values, ...(s.band || [])]) {
          for (const v of arr) {
            if (v === null || v === undefined) continue;
            a = Math.min(a, v);
            b = Math.max(b, v);
          }
        }
      }
      return [a, b];
    };
    let [lo, hi] = span(series.filter((s) => !s.guide));
    const above = new Set();
    for (const s of series.filter((s) => s.guide)) {
      const [glo, ghi] = span([s]);
      if (!Number.isFinite(ghi)) continue;
      if (hi > 0 && glo > hi * GUIDE_REACH) above.add(s);
      else {
        lo = Math.min(lo, glo);
        hi = Math.max(hi, ghi);
      }
    }
    if (!Number.isFinite(lo)) {
      lo = 0;
      hi = 1;
    }
    lo = Math.min(0, lo);
    const pad = { l: 52, r: labelled ? 104 : 14, t: opts.marker || above.size ? 22 : 10, b: 26 };
    const pw = width - pad.l - pad.r;
    const ph = height - pad.t - pad.b;
    const yt = niceTicks(lo, hi * 1.02);
    const y0 = yt[0];
    const y1 = yt[yt.length - 1];
    const n = x.length;
    const X = (i) => pad.l + (n < 2 ? pw / 2 : (i / (n - 1)) * pw);
    const Y = (v) => pad.t + ph - ((v - y0) / (y1 - y0 || 1)) * ph;
    const root = svg("svg", {
      viewBox: `0 0 ${width} ${height}`,
      width,
      height,
      role: "img",
      tabindex: 0,
      "aria-label": opts.label || "chart",
    });
    host.append(root);
    for (const t of yt) {
      svg("line", { x1: pad.l, x2: pad.l + pw, y1: Y(t), y2: Y(t), class: t === 0 ? "axis" : "grid" }, root);
      svg("text", { x: pad.l - 8, y: Y(t) + 4, class: "tick", "text-anchor": "end" }, root).textContent = yFormat(t);
    }
    const ticks = xTickIndexes(x, Math.max(2, Math.floor(pw / 70)));
    const monthly = typeof x[0] === "string" && ticks.some((i, k) => k > 0 && x[i].slice(0, 4) === x[ticks[k - 1]].slice(0, 4));
    for (const [k, i] of ticks.entries()) {
      svg("text", { x: X(i), y: height - 8, class: "tick", "text-anchor": "middle" }, root).textContent = xTickText(x[i], monthly, k === 0);
    }
    if (opts.marker && opts.marker.index > 0 && opts.marker.index < n) {
      const mx = X(opts.marker.index);
      svg("line", { x1: mx, x2: mx, y1: pad.t - 6, y2: pad.t + ph, class: "marker" }, root);
      svg("text", { x: mx + 4, y: pad.t - 8, class: "tick" }, root).textContent = opts.marker.label;
    }
    const pathOf = (vals) => {
      let d = "";
      let pen = false;
      vals.forEach((v, i) => {
        if (v === null || v === undefined) {
          pen = false;
          return;
        }
        d += `${pen ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`;
        pen = true;
      });
      return d;
    };
    for (const s of series) {
      if (!s.band) continue;
      const [b0, b1] = s.band;
      let d = "";
      b1.forEach((v, i) => (d += `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`));
      for (let i = b0.length - 1; i >= 0; i--) d += `L${X(i).toFixed(1)},${Y(b0[i]).toFixed(1)}`;
      svg("path", { d: d + "Z", fill: s.color, "fill-opacity": 0.16, stroke: "none" }, root);
    }
    for (const s of series) {
      if (above.has(s)) continue;
      svg("path", {
        d: pathOf(s.values),
        fill: "none",
        stroke: s.color,
        "stroke-width": 2,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
        "stroke-dasharray": s.dash ? "5 4" : "none",
      }, root);
    }
    for (const s of above) {
      const note = svg("text", { x: pad.l + pw, y: pad.t - 8, class: "end-label guide-above", "text-anchor": "end" }, root);
      note.textContent = `\u2191 ${s.name}: above the chart`;
    }
    if (labelled) {
      const ends = series
        .filter((s) => !above.has(s))
        .map((s) => ({ s, v: s.values[n - 1] }))
        .filter((e) => e.v !== null && e.v !== undefined)
        .map((e) => ({ ...e, y: Y(e.v) }))
        .sort((a, b) => a.y - b.y);
      for (let k = 1; k < ends.length; k++) ends[k].y = Math.max(ends[k].y, ends[k - 1].y + 14);
      for (const e of ends) {
        svg("text", { x: pad.l + pw + 8, y: Math.min(e.y, pad.t + ph) + 4, class: "end-label" }, root).textContent = e.s.name;
      }
    }
    const cross = svg("line", { y1: pad.t, y2: pad.t + ph, class: "cross", visibility: "hidden" }, root);
    const dots = series.map((s) => svg("circle", { r: 4, fill: s.color, class: "dot", visibility: "hidden" }, root));
    const hit = svg("rect", { x: pad.l, y: pad.t, width: pw, height: ph, fill: "transparent" }, root);
    const tip = tipBox(host);
    let at = -1;
    const show = (i) => {
      at = Math.max(0, Math.min(n - 1, i));
      const cx = X(at);
      cross.setAttribute("x1", cx);
      cross.setAttribute("x2", cx);
      cross.setAttribute("visibility", "visible");
      const rows = [];
      series.forEach((s, k) => {
        const v = s.values[at];
        const off = above.has(s);
        if (v === null || v === undefined || off) dots[k].setAttribute("visibility", "hidden");
        if (v === null || v === undefined) return;
        if (!off) {
          dots[k].setAttribute("cx", cx);
          dots[k].setAttribute("cy", Y(v));
          dots[k].setAttribute("visibility", "visible");
        }
        let value = off ? `${tipFormat(v)} (above the chart)` : tipFormat(v);
        if (s.band) value += `  (${tipFormat(s.band[0][at])} to ${tipFormat(s.band[1][at])})`;
        rows.push({ name: s.name, value, color: s.color, dash: s.dash });
      });
      showTip(host, tip, cx, pad.t + ph / 3, xFormat(x[at]), rows);
    };
    const hide = () => {
      cross.setAttribute("visibility", "hidden");
      dots.forEach((d) => d.setAttribute("visibility", "hidden"));
      tip.hidden = true;
    };
    hit.addEventListener("pointermove", (ev) => {
      const r = root.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * width;
      show(Math.round(((px - pad.l) / pw) * (n - 1)));
    });
    hit.addEventListener("pointerleave", hide);
    root.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
        ev.preventDefault();
        show((at < 0 ? n - 1 : at) + (ev.key === "ArrowRight" ? 1 : -1));
      } else if (ev.key === "Escape") hide();
    });
    root.addEventListener("blur", hide);
  });
}

export function histChart(host, opts) {
  const { lo, hi, counts } = opts;
  const height = opts.height || 150;
  mount(host, () => {
    host.replaceChildren();
    host.classList.add("chart");
    const width = Math.max(260, host.clientWidth || 600);
    const pad = { l: 14, r: 14, t: 22, b: 26 };
    const pw = width - pad.l - pad.r;
    const ph = height - pad.t - pad.b;
    const top = Math.max(1, ...counts);
    const total = counts.reduce((a, b) => a + b, 0) || 1;
    const n = counts.length;
    const bw = pw / n;
    const span = hi - lo || 1;
    const X = (v) => pad.l + ((v - lo) / span) * pw;
    const base = pad.t + ph;
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", "aria-label": opts.label || "histogram" }, host);
    svg("line", { x1: pad.l, x2: pad.l + pw, y1: base, y2: base, class: "axis" }, root);
    const tip = tipBox(host);
    counts.forEach((c, i) => {
      const x0 = pad.l + i * bw + 1;
      const w = Math.max(1, bw - 2);
      const h = (c / top) * ph;
      const y = base - h;
      const r = Math.min(4, w / 2, h);
      const d = h <= 0 ? "" : `M${x0},${base}V${y + r}Q${x0},${y} ${x0 + r},${y}H${x0 + w - r}Q${x0 + w},${y} ${x0 + w},${y + r}V${base}Z`;
      if (d) svg("path", { d, class: "bar" }, root);
      const hit = svg("rect", { x: pad.l + i * bw, y: pad.t, width: bw, height: ph, fill: "transparent" }, root);
      const a = lo + (i / n) * span;
      const b = lo + ((i + 1) / n) * span;
      hit.addEventListener("pointermove", () => {
        showTip(host, tip, x0 + w / 2, pad.t + ph / 2, `${money(a)} to ${money(b)}`, [
          { name: "coin-flip copies", value: `${c} of ${total}` },
        ]);
      });
      hit.addEventListener("pointerleave", () => (tip.hidden = true));
    });
    for (const t of niceTicks(lo, hi, Math.max(2, Math.floor(pw / 110)))) {
      if (t < lo || t > hi) continue;
      svg("text", { x: X(t), y: height - 8, class: "tick", "text-anchor": "middle" }, root).textContent = moneyShort(t);
    }
    if (opts.mark !== undefined && opts.mark !== null) {
      const mx = Math.max(pad.l, Math.min(pad.l + pw, X(opts.mark)));
      svg("line", { x1: mx, x2: mx, y1: pad.t - 4, y2: base, class: "mark" }, root);
      const anchor = mx > pad.l + pw * 0.75 ? "end" : "start";
      svg("text", { x: mx + (anchor === "end" ? -4 : 4), y: pad.t - 8, class: "end-label", "text-anchor": anchor }, root).textContent =
        opts.markLabel || "this one";
    }
  });
}
