/* PixelForge drawing tools, kept free of the DOM so node can test them
   (tests/tools.test.mjs).

   A sprite frame is rows of single-character palette keys. Every tool works on
   those rows and returns new ones; it never edits the rows it is given, so
   the page can keep a snapshot for shape previews and undo.

   TOOLS is the registry: a new tool is one entry here. The page builds the
   toolbar, the button tooltips and the keyboard shortcuts from it.

     id     stable name ("tool:<id>" is its keyboard action)
     label  what the toolbar button says
     key    its key (checked against the other shortcuts by the node test)
     help   the button tooltip
     drag   how the pointer drives it:
              "stroke" apply from the last point to this one on every move
              "shape"  re-apply from the press point to this one, on the
                       rows as they were when the press began
              "once"   apply once, where the press began
              "pick"   read the key under the cursor, change nothing
     apply  (rows, a, b, key, {w, h, mirror}) -> new rows; a and b are {x, y} */
(function (root) {
  "use strict";

  /** Every cell on the straight line from (x0, y0) to (x1, y1), ends included,
      each step touching the last (Bresenham). */
  function linePoints(x0, y0, x1, y1) {
    const pts = [];
    const dx = Math.abs(x1 - x0), dy = -Math.abs(y1 - y0);
    const sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
    let err = dx + dy, x = x0, y = y0;
    for (;;) {
      pts.push({ x, y });
      if (x === x1 && y === y1) return pts;
      const e2 = 2 * err;
      if (e2 >= dy) { err += dy; x += sx; }
      if (e2 <= dx) { err += dx; y += sy; }
    }
  }

  /** The outline of the box with corners (x0, y0) and (x1, y1). */
  function rectPoints(x0, y0, x1, y1) {
    const l = Math.min(x0, x1), r = Math.max(x0, x1);
    const t = Math.min(y0, y1), b = Math.max(y0, y1);
    const pts = [];
    for (let x = l; x <= r; x++) { pts.push({ x, y: t }); if (b !== t) pts.push({ x, y: b }); }
    for (let y = t + 1; y < b; y++) { pts.push({ x: l, y }); if (r !== l) pts.push({ x: r, y }); }
    return pts;
  }

  /** The points plus their reflection across the sprite's vertical centre. */
  function withMirror(points, o) {
    if (!o || !o.mirror) return points;
    return points.concat(points.map((p) => ({ x: o.w - 1 - p.x, y: p.y })));
  }

  /** New rows with `key` at each point on the sprite; points off it are dropped. */
  function plot(rows, points, key) {
    const h = rows.length;
    const touched = new Map();
    for (const { x, y } of points) {
      if (y < 0 || y >= h || x < 0 || x >= rows[y].length) continue;
      if (!touched.has(y)) touched.set(y, rows[y].split(""));
      touched.get(y)[x] = key;
    }
    const out = rows.slice();
    for (const [y, cells] of touched) out[y] = cells.join("");
    return out;
  }

  /** New rows with the 4-connected area of one key around (x, y) set to `key`. */
  function floodFill(rows, x, y, key) {
    const h = rows.length;
    if (y < 0 || y >= h || x < 0 || x >= rows[y].length) return rows.slice();
    const from = rows[y][x];
    if (from === key) return rows.slice();
    const grid = rows.map((r) => r.split(""));
    const stack = [[x, y]];
    while (stack.length) {
      const [cx, cy] = stack.pop();
      if (cy < 0 || cy >= h || cx < 0 || cx >= grid[cy].length || grid[cy][cx] !== from) continue;
      grid[cy][cx] = key;
      stack.push([cx + 1, cy], [cx - 1, cy], [cx, cy + 1], [cx, cy - 1]);
    }
    return grid.map((r) => r.join(""));
  }

  /** The key at a point, or null off the sprite. */
  function pick(rows, p) {
    const row = rows[p.y];
    return row !== undefined && p.x >= 0 && p.x < row.length ? row[p.x] : null;
  }

  function sameRows(a, b) {
    return a.length === b.length && a.every((r, i) => r === b[i]);
  }

  const TOOLS = [
    {
      id: "pencil", label: "pencil", key: "b", drag: "stroke",
      help: "Pencil: draw pixel by pixel in the chosen colour; right-click erases",
      apply: (rows, a, b, key, o) => plot(rows, withMirror(linePoints(a.x, a.y, b.x, b.y), o), key),
    },
    {
      id: "fill", label: "fill", key: "f", drag: "once",
      help: "Fill: colour the whole touching area of one colour",
      apply: (rows, a, b, key, o) => {
        const out = floodFill(rows, a.x, a.y, key);
        return o && o.mirror ? floodFill(out, o.w - 1 - a.x, a.y, key) : out;
      },
    },
    {
      id: "line", label: "line", key: "l", drag: "shape",
      help: "Line: press, drag and let go",
      apply: (rows, a, b, key, o) => plot(rows, withMirror(linePoints(a.x, a.y, b.x, b.y), o), key),
    },
    {
      id: "rect", label: "box", key: "r", drag: "shape",
      help: "Box: drag from one corner to the other",
      apply: (rows, a, b, key, o) => plot(rows, withMirror(rectPoints(a.x, a.y, b.x, b.y), o), key),
    },
    {
      id: "pick", label: "pick", key: "i", drag: "pick",
      help: "Pick: take the colour under the cursor, then go back to the last tool",
    },
  ];

  const get = (id) => TOOLS.find((t) => t.id === id) || TOOLS[0];

  /** Shortcut entries in editor_state.js's SHORTCUTS shape, one per tool. */
  function shortcuts() {
    return TOOLS.filter((t) => t.key).map((t) => ({
      action: "tool:" + t.id, keys: [t.key], tabs: ["sprites"],
      label: t.help.split(":")[0], button: "tool-" + t.id,
    }));
  }

  const api = { TOOLS, get, shortcuts, linePoints, rectPoints, plot, floodFill, pick, sameRows };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PixelTools = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
