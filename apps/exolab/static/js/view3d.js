// The 3D bench: the VRM person wearing the fitted suit, posed from the
// core's bone rotations, with the exo shoulder mechanism drawn live from the
// layout the core returns (pivots, motor axes, links, struts, cuffs) and
// in suit colours (carbon pods, metal struts, a cyan twist ring) that glow
// amber over a rating and red past the limit; the Heat colours layer paints
// every part green, amber or red instead. Around the shoulder: the reach
// dome (the range map wrapped round the joint) and the gimbal-lock cones.
// The core computes the right arm; the left side mirrors a frame across the
// body's mid-plane so the suit reads as a pair.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { attachSuit, disposePerson, hideDress, loadPerson, tintUndersuit } from "./suit.js";

const COL = { pass: 0x59d499, warn: 0xf2a154, fail: 0xf2637d };
// Close-fit clash dots: into the skin or another shell, under 3 mm, and the
// body in itself (the pose's fault, not the suit's).
const CLASH_COL = { fail: 0xff2a4d, warn: 0xffb020, body: 0xa08cff };
const METAL = 0xa7b0bd;
const DARK = 0x2b313c;
const RING = 0x2aa9c9;
const GLOW = { warn: 0x7a4208, fail: 0x8a1020 };
const AXIS_COL = [0xffb454, 0x8ee06e, 0x6ab8ff];
const UP = new THREE.Vector3(0, 1, 0);
const _a = new THREE.Vector3();
const _b = new THREE.Vector3();
const _d = new THREE.Vector3();
const GEO = {
  cyl: new THREE.CylinderGeometry(1, 1, 1, 18, 1),
  band: new THREE.CylinderGeometry(1, 1, 1, 40, 1, true),
  sph: new THREE.SphereGeometry(1, 18, 12),
  cone: new THREE.ConeGeometry(1, 1, 32, 1, true),
};

let DOT = null;
/** A round dot for the reach dome's points (they are squares without it). */
function dotTexture() {
  if (DOT) return DOT;
  const c = document.createElement("canvas");
  c.width = c.height = 32;
  const g = c.getContext("2d");
  g.fillStyle = "#fff";
  g.beginPath();
  g.arc(16, 16, 15, 0, Math.PI * 2);
  g.fill();
  DOT = new THREE.CanvasTexture(c);
  return DOT;
}

function std(color, extra = {}) {
  return new THREE.MeshStandardMaterial({ color, metalness: 0.55, roughness: 0.38, ...extra });
}

/** Meshes made once and re-placed every frame; unused ones hide. */
class Pool {
  constructor(group) {
    this.group = group;
    this.items = new Map();
    this.used = new Set();
  }
  begin() {
    this.used.clear();
  }
  get(key, make) {
    let o = this.items.get(key);
    if (!o) {
      o = make();
      this.items.set(key, o);
      this.group.add(o);
    }
    o.visible = true;
    this.used.add(key);
    return o;
  }
  end() {
    for (const [k, o] of this.items) if (!this.used.has(k)) o.visible = false;
  }
}

function placeTube(m, a, b, r) {
  _a.fromArray(a);
  _b.fromArray(b);
  _d.subVectors(_b, _a);
  const len = _d.length();
  m.position.addVectors(_a, _b).multiplyScalar(0.5);
  if (len > 1e-9) m.quaternion.setFromUnitVectors(UP, _d.multiplyScalar(1 / len));
  m.scale.set(r, Math.max(len, 1e-4), r);
}

function placeAlong(m, at, axis, r, len) {
  m.position.fromArray(at);
  _d.fromArray(axis);
  if (_d.lengthSq() > 1e-12) m.quaternion.setFromUnitVectors(UP, _d.normalize());
  m.scale.set(r, len, r);
}

/** Suit colours: the part keeps its base colour on a pass and glows amber
 *  or red on a warning or failure. With heat on, the old green, amber, red. */
function tint(m, level, base = METAL, heat = false) {
  const hot = level === "warn" || level === "fail";
  const c = heat && level && COL[level] != null ? COL[level] : hot ? COL[level] : base;
  m.material.color.setHex(c);
  m.material.emissive.setHex(hot ? GLOW[level] : 0x000000);
}

export function jointLevel(torque, spec) {
  if (!spec || !spec.powered) return null;
  const t = Math.abs(torque || 0);
  if (t <= spec.torque_cont_nm) return "pass";
  return t <= spec.torque_peak_nm ? "warn" : "fail";
}
export function safetyLevel(s) {
  if (s == null) return null;
  return s >= 2 ? "pass" : s >= 1 ? "warn" : "fail";
}
export function kpaLevel(p, comfort) {
  if (p == null) return null;
  const long = comfort?.pressure_long_kpa ?? 4.3;
  const short = comfort?.pressure_short_kpa ?? 13.3;
  return p <= long ? "pass" : p <= short ? "warn" : "fail";
}

export class View3D {
  constructor(canvas, note) {
    this.canvas = canvas;
    this.note = note;
    this.ok = false;
    // Draw only for about a second after something changes (see tick).
    this.until = 0;
    this._active = false;
    this.person = null;
    this.parts = new Map();
    this.key = "";
    this.pending = null;
    this.layers = { mech: true, suit: true, forces: true, axes: true, reach: true, lock: true, heat: false };
    this.reach = null;
    this.blank = false;
    try {
      this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    } catch (err) {
      note.textContent = "This window has no WebGL, so the 3D view is off. Every number still works.";
      return;
    }
    this.ok = true;
    const r = this.renderer;
    r.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    r.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0e14);
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.02, 60);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.addEventListener("change", () => this.dirty());
    // A lost and restored GL context, or the page shown again, needs a fresh
    // picture: the view only draws after dirty().
    canvas.addEventListener("webglcontextrestored", () => this.dirty());
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) this.dirty();
    });
    this.scene.add(new THREE.HemisphereLight(0xdfe8ff, 0x1c2029, 1.5));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(-1.6, 3.2, 2.6);
    const rim = new THREE.DirectionalLight(0x5fd0ff, 1.1);
    rim.position.set(1.8, 2.2, -2.6);
    this.scene.add(key, rim);
    const grid = new THREE.GridHelper(6, 30, 0x2c3444, 0x171c26);
    this.scene.add(grid);
    this.right = new THREE.Group();
    this.left = new THREE.Group();
    this.left.scale.x = -1; // the body's mid-plane is x = 0
    this.scene.add(this.right, this.left);
    this.poolR = new Pool(this.right);
    this.poolL = new Pool(this.left);
    this.clock = new THREE.Clock();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
    this.setCamera("shoulder");
    const loop = () => {
      requestAnimationFrame(loop);
      this.tick();
    };
    loop();
  }

  /** The view is on screen only while the tester route is open. */
  get active() {
    return this._active;
  }

  set active(on) {
    this._active = on;
    if (on) this.dirty();
  }

  /** Something on screen changed: draw for about a second, so the camera's
   *  damping and the person's spring bones can settle. */
  dirty() {
    this.until = performance.now() + 1000;
  }

  resize() {
    if (!this.ok) return;
    const p = this.canvas.parentElement;
    const w = p.clientWidth;
    const hgt = p.clientHeight;
    if (!w || !hgt) return;
    this.renderer.setSize(w, hgt, false);
    this.camera.aspect = w / hgt;
    this.camera.updateProjectionMatrix();
    this.dirty();
  }

  tick() {
    if (!this.active) return;
    const dt = Math.min(this.clock.getDelta(), 0.05);
    // update() is true while a drag or its damping still moves the camera.
    if (this.controls.update()) this.dirty();
    if (performance.now() > this.until) return;
    if (this.person) this.person.vrm.update(dt);
    this.renderer.render(this.scene, this.camera);
  }

  setCamera(name, gh) {
    if (!this.ok) return;
    const g = new THREE.Vector3().fromArray(gh || this.gh || [-0.17, 1.36, -0.01]);
    // Front: the whole body in the frame, from the person's own height.
    const tall = this.height || 1.6;
    const fit = (tall * 0.56) / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    const presets = {
      // About 0.6 m from the joint, in front of it and out to her right.
      shoulder: [new THREE.Vector3(0, -0.03, 0).add(g), new THREE.Vector3(-0.52, 0.04, 0.3).add(g)],
      front: [new THREE.Vector3(0, tall / 2, 0), new THREE.Vector3(0, tall * 0.55, Math.max(fit, 1.2))],
      side: [new THREE.Vector3(0, 1.05, 0), new THREE.Vector3(-3.6, 1.25, 0.25)],
      back: [new THREE.Vector3(0, 1.2, 0), new THREE.Vector3(0.5, 1.7, -3.1)],
      top: [g.clone(), new THREE.Vector3(-0.08, 1.1, 0.2).add(g)],
    };
    const [target, pos] = presets[name] || presets.shoulder;
    this.camName = name;
    this.canvas.dataset.view = `${name} ${pos.distanceTo(target).toFixed(2)}`;
    this.controls.target.copy(target);
    this.camera.position.copy(pos);
    this.controls.update();
    this.dirty();
  }

  /** Load the person and the suit for a model (once per character and suit). */
  async load(model) {
    if (!this.ok || !model?.character) return;
    const key = `${model.character.url}|${model.suit_asset?.glb || ""}`;
    if (key === this.key) return;
    this.key = key;
    const token = (this.token = {});
    this.note.textContent = "Loading the person and the suit…";
    try {
      const person = await loadPerson(model.character.url);
      let parts = new Map();
      const info = { hidden: 0, undersuit: false, parts: 0 };
      if (model.suit_asset?.glb) {
        const sidecar = model.suit_asset.sidecar ? await fetch(model.suit_asset.sidecar).then((r) => r.json()) : {};
        parts = await attachSuit(person.vrm, model.suit_asset.glb, sidecar);
        info.hidden = hideDress(person.vrm, sidecar.hide_rule);
        info.undersuit = tintUndersuit(person.vrm, sidecar);
        info.parts = parts.size;
      }
      if (token !== this.token) {
        disposePerson(person);
        return;
      }
      if (this.person) {
        this.scene.remove(this.person.vrm.scene);
        disposePerson(this.person);
      }
      this.person = person;
      this.parts = parts;
      this.info = info;
      // How the skin was dressed, for tests/check_ui.py: the undersuit, or
      // how many skin faces went into the light suit's shorts.
      const shorts = person.vrm.scene.userData.exolabSkin?.shorts || 0;
      this.canvas.dataset.skin = info.undersuit ? "undersuit" : `shorts ${shorts}`;
      for (const [, o] of parts) o.visible = this.layers.suit;
      this.scene.add(person.vrm.scene);
      person.vrm.scene.visible = !this.blank;
      const head = person.vrm.humanoid.getNormalizedBoneNode("head");
      if (head) {
        person.vrm.scene.updateMatrixWorld(true);
        this.height = head.getWorldPosition(_a).y + 0.13;
      }
      if (this.camName === "front") this.setCamera("front");
      this.note.textContent = "";
      this.dirty();
      if (this.pending) this.show(...this.pending);
    } catch (err) {
      if (token === this.token) this.note.textContent = `The 3D model did not load: ${err.message}`;
    }
  }

  setLayer(name, on) {
    this.layers[name] = on;
    if (name === "suit") for (const [, o] of this.parts) o.visible = on;
    if (name === "reach" && this.reach) this.reach.visible = on;
    this.dirty();
    if (this.pending) this.show(...this.pending);
  }

  /** A planned model has no body yet: hide the person, suit and mechanism. */
  setBlank(on) {
    this.blank = on;
    if (this.person) this.person.vrm.scene.visible = !on;
    this.right.visible = this.left.visible = !on;
    this.canvas.dataset.blank = String(on);
    this.dirty();
  }

  /** The reach dome: every reachable cell of the range map as a dot at arm's
   *  length from the shoulder, coloured by its level. null removes it. */
  showReach(map) {
    if (!this.ok) return;
    if (this.reach) {
      this.right.remove(this.reach);
      this.reach.geometry.dispose();
      this.reach.material.dispose();
      this.reach = null;
    }
    this.dirty();
    const cells = (map?.cells || []).filter((c) => c.level !== "out" && c.dir);
    this.canvas.dataset.reach = String(cells.length);
    if (!cells.length || !map.gh) return;
    const pos = new Float32Array(cells.length * 3);
    const col = new Float32Array(cells.length * 3);
    const c = new THREE.Color();
    cells.forEach((cell, i) => {
      for (let k = 0; k < 3; k++) pos[i * 3 + k] = map.gh[k] + cell.dir[k] * map.reach_m;
      c.setHex(COL[cell.level] ?? COL.warn);
      col.set([c.r, c.g, c.b], i * 3);
    });
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    const mat = new THREE.PointsMaterial({
      size: 0.014,
      map: dotTexture(),
      alphaTest: 0.5,
      vertexColors: true,
      transparent: true,
      opacity: 0.9,
      depthWrite: false,
    });
    this.reach = new THREE.Points(geo, mat);
    this.reach.visible = this.layers.reach;
    this.right.add(this.reach);
  }

  /** Pose the person and draw the mechanism for one frame. ctx carries the
   *  suit specs (joint ratings), the comfort bands and the left-side frame. */
  show(frame, ctx) {
    this.pending = [frame, ctx];
    if (!this.ok || !frame) return;
    this.dirty();
    if (frame.layout?.gh) this.gh = frame.layout.gh;
    const left = ctx.leftFrame || frame;
    this.pose(frame, left);
    this.draw(this.poolR, frame, ctx, true);
    this.draw(this.poolL, left, ctx, false);
  }

  pose(frame, left) {
    if (!this.person) return;
    const { vrm, vrm0 } = this.person;
    const set = (name, q, mirror) => {
      const node = vrm.humanoid.getNormalizedBoneNode(name);
      if (!node || !q) return;
      let [x, y, z, w] = q;
      if (mirror) {
        y = -y;
        z = -z;
      }
      if (vrm0) {
        x = -x;
        z = -z;
      }
      node.quaternion.set(x, y, z, w);
    };
    for (const [name, q] of Object.entries(frame.bones || {})) set(name, q, false);
    for (const [name, q] of Object.entries(left.bones || {})) set(name.replace(/^right/, "left"), q, true);
  }

  draw(pool, frame, ctx, main) {
    pool.begin();
    const L = frame.layout || {};
    const show = this.layers.mech;
    const joints = Object.fromEntries((ctx.suit?.joints || []).map((j) => [j.key, j]));
    const safety = Object.fromEntries((frame.structure || []).map((s) => [s.id, s.safety]));
    const press = Object.fromEntries((frame.cuffs || []).map((c) => [c.id, c.pressure_kpa]));
    const tq = frame.torques || {};
    const heat = this.layers.heat;
    const tube = (key, a, b, r, level, base) => {
      const m = pool.get(key, () => new THREE.Mesh(GEO.cyl, std(base ?? METAL)));
      placeTube(m, a, b, r);
      tint(m, level, base ?? METAL, heat);
      return m;
    };
    const along = (key, at, axis, r, len, level, base, geo = GEO.cyl) => {
      const m = pool.get(key, () => new THREE.Mesh(geo, std(base ?? DARK, { side: THREE.DoubleSide })));
      placeAlong(m, at, axis, r, len);
      tint(m, level, base ?? DARK, heat);
      return m;
    };
    const dot = (key, at, r, color) => {
      const m = pool.get(key, () => new THREE.Mesh(GEO.sph, std(color, { emissive: color, emissiveIntensity: 0.6 })));
      m.position.fromArray(at);
      m.scale.setScalar(r);
      return m;
    };
    if (main) this.tintClashes(frame);
    if (show) {
      if (L.base) tube("base", L.base[0], L.base[1], 0.011, null, DARK);
      if (L.girdle) {
        tube("g1", L.girdle[0], L.girdle[1], 0.01);
        tube("g2", L.girdle[1], L.girdle[2], 0.01);
        dot("gk", L.girdle[1], 0.014, 0x3a4352);
      }
      for (const name of ["link1", "link2"]) {
        const pts = L[name] || [];
        for (let i = 0; i + 1 < pts.length; i++) tube(`${name}.${i}`, pts[i], pts[i + 1], 0.009);
      }
      (L.pods || []).forEach((at, i) => {
        const k = `J${i + 1}`;
        along(`pod${i}`, at, L.axes?.[i] || [0, 1, 0], 0.027, 0.036, jointLevel(tq[k], joints[k]));
      });
      if (L.ring) along("ring", L.ring.at, L.ring.axis, L.ring.radius, 0.018, jointLevel(tq.J3, joints.J3), RING, GEO.band);
      const sd = L.strut_d || [0.02, 0.018];
      if (L.upper_strut) tube("us", L.upper_strut[0], L.upper_strut[1], sd[0] / 2, safetyLevel(safety.upper_arm_link));
      if (L.fore_strut) tube("fs", L.fore_strut[0], L.fore_strut[1], sd[1] / 2, safetyLevel(safety.forearm_link));
      if (L.elbow_joint) {
        along("el", L.elbow_joint.at, L.elbow_joint.axis, 0.024, 0.032, jointLevel(tq.elbow, joints.elbow));
      }
      const cable = L.cable || [];
      for (let i = 0; i + 1 < cable.length; i++) tube(`cab${i}`, cable[i], cable[i + 1], 0.003, null, 0xffb454);
      for (const c of L.cuffs || []) {
        const lvl = kpaLevel(press[c.id], ctx.comfort);
        const glb = this.parts.get(`${c.id}_${main ? "R" : "L"}`);
        if (glb && this.layers.suit) {
          if (main && !frame.clash) this.tintPart(glb, lvl);
        } else {
          along(`cuff.${c.id}`, c.at, c.axis, c.radius, c.width, lvl, 0x55606e, GEO.band);
        }
      }
    }
    if (main) {
      // Drawn through the shells, so a clash inside one still shows.
      (frame.clash || []).forEach((c, i) => {
        const col = CLASH_COL[c.level] ?? CLASH_COL.warn;
        const m = dot(`clash${i}`, c.at, c.level === "body" ? 0.011 : 0.0075, col);
        m.material.color.setHex(col);
        m.material.emissive.setHex(col);
        m.material.depthTest = false;
        m.renderOrder = 10;
      });
      // What is marked, readable from the page (the UI check reads it).
      this.canvas.dataset.clash = String(frame.clash?.length || 0);
    }
    if (main && L.gh) {
      dot("gh", L.gh, 0.011, 0xff5470);
      dot("centre", L.centre || L.gh, 0.009, 0x5fd0ff);
      const mis = (frame.misalign_mm || 0) > 1;
      if (mis && L.centre) tube("mis", L.gh, L.centre, 0.0025, null, 0xffe066);
      if (this.layers.axes && L.axes && L.centre) {
        L.axes.forEach((ax, i) => {
          const a = L.centre.map((v, j) => v - ax[j] * 0.1);
          const b = L.centre.map((v, j) => v + ax[j] * 0.1);
          tube(`ax${i}`, a, b, 0.0022, null, AXIS_COL[i]);
        });
      }
      let cones = 0;
      if (this.layers.lock && L.lock && L.axes && L.centre) {
        // The gimbal-lock zone: the arm inside the outer cone round axis 1
        // warns, inside the inner one it fails (as the lock check does).
        const locked = (frame.issues || []).some((i) => i.code === "lock");
        const len = L.lock.length;
        for (const sign of [1, -1]) {
          for (const [lvl, deg, alpha] of [["warn", L.lock.warn_deg, 0.12], ["fail", L.lock.fail_deg, 0.25]]) {
            const m = pool.get(`lock.${lvl}.${sign}`, () =>
              new THREE.Mesh(
                GEO.cone,
                new THREE.MeshBasicMaterial({ color: COL[lvl], transparent: true, depthWrite: false, side: THREE.DoubleSide }),
              ),
            );
            _d.fromArray(L.axes[0]).multiplyScalar(sign).normalize();
            m.quaternion.setFromUnitVectors(UP, _b.copy(_d).negate());
            m.position.fromArray(L.centre).addScaledVector(_d, len / 2);
            const r = len * Math.tan(THREE.MathUtils.degToRad(deg));
            m.scale.set(r, len, r);
            m.material.opacity = lvl === "fail" && locked ? 0.5 : alpha;
            cones++;
          }
        }
      }
      this.canvas.dataset.lock = String(cones);
      if (this.layers.forces) {
        for (const c of L.cuffs || []) {
          const f = c.force || [0, 0, 0];
          const n = Math.hypot(...f);
          if (n < 0.5) continue;
          const arrow = pool.get(`f.${c.id}`, () => new THREE.ArrowHelper(UP, new THREE.Vector3(), 0.1, 0xffa040));
          arrow.position.fromArray(c.at);
          arrow.setDirection(_d.fromArray(f).normalize());
          const len = Math.min(0.3, 0.012 + n * 0.0025);
          arrow.setLength(len, Math.min(0.03, len * 0.35), 0.016);
        }
      }
    }
    pool.end();
  }

  /** Close fit: each suit part tinted by its worst clash in the frame. A
   *  frame from another test resets what close fit tinted. */
  tintClashes(frame) {
    if (!frame.clash) {
      if (this.clashTinted) for (const [, node] of this.parts) this.tintPart(node, "pass");
      this.clashTinted = false;
      return;
    }
    const rank = { pass: 0, warn: 1, fail: 2 };
    const worst = new Map();
    for (const c of frame.clash) {
      if (c.level === "body") continue;
      for (const name of c.part.split("+")) {
        if ((rank[c.level] || 0) > (rank[worst.get(name)] || 0)) worst.set(name, c.level);
      }
    }
    for (const [name, node] of this.parts) this.tintPart(node, worst.get(name) || "pass");
    this.clashTinted = true;
    this.canvas.dataset.tinted = [...worst.keys()].filter((n) => this.parts.has(n)).join(" ");
  }

  tintPart(node, level) {
    node.traverse((m) => {
      if (!m.isMesh) return;
      if (!m.userData.ownMat) {
        m.material = [m.material].flat()[0].clone();
        m.userData.ownMat = true;
        m.userData.baseEmissive = m.material.emissive ? m.material.emissive.getHex() : 0;
      }
      if (!m.material.emissive) return;
      const c = level === "fail" ? 0x8a1020 : level === "warn" ? 0x6a3a08 : m.userData.baseEmissive;
      m.material.emissive.setHex(c);
    });
  }
}
