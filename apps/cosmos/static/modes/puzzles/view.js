/* The orbit puzzles' 3D scene.
 *
 * Levels are small next to the map (a few hundred units across; the explore
 * level a few thousand), so there is no floating origin: positions go straight
 * to the GPU. Axes follow the map: a level's plane is x/y with z up, drawn in
 * Three.js's y-up axes as (x, z, -y).
 *
 * Drawing budget: this has to look good on the laptop's integrated GPU at
 * about 13 W. Everything bright is a cheap additive sprite or a line, there is
 * no post-processing, the pixel ratio is capped at 1.25, and the mode only
 * redraws often while something is actually moving.
 */

import * as THREE from "three";

import { mulberry32 } from "../../core/nbody.js";
import { railState } from "../../core/nbody3d.js";
import { waypointPosition } from "../../core/puzzle.js";

const FOV = 50;
const MIN_PX = { star: 7, blackhole: 7, planet: 3.5, moon: 2.4 };
const PREVIEW_MAX = 3200;
const TRAIL_MAX = 8002;
const MAX_GHOSTS = 5;

export const toThree = (p) => new THREE.Vector3(p[0], p[2], -p[1]);
export const fromThree = (v) => [v.x, -v.z, v.y];

function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function canvasTexture(width, height, draw) {
  const c = document.createElement("canvas");
  c.width = width;
  c.height = height;
  draw(c.getContext("2d"), width, height);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

const glowTexture = () =>
  canvasTexture(128, 128, (g, s) => {
    const grad = g.createRadialGradient(s / 2, s / 2, 0, s / 2, s / 2, s / 2);
    grad.addColorStop(0, "rgba(255,255,255,1)");
    grad.addColorStop(0.12, "rgba(255,255,255,0.8)");
    grad.addColorStop(0.35, "rgba(255,255,255,0.2)");
    grad.addColorStop(1, "rgba(255,255,255,0)");
    g.fillStyle = grad;
    g.fillRect(0, 0, s, s);
  });

const ringTexture = () =>
  canvasTexture(128, 128, (g, s) => {
    g.strokeStyle = "rgba(255,255,255,0.22)";
    g.lineWidth = 16;
    g.beginPath();
    g.arc(s / 2, s / 2, s / 2 - 14, 0, Math.PI * 2);
    g.stroke();
    g.strokeStyle = "rgba(255,255,255,0.95)";
    g.lineWidth = 4;
    g.beginPath();
    g.arc(s / 2, s / 2, s / 2 - 8, 0, Math.PI * 2);
    g.stroke();
  });

function mix(hex, target, k) {
  const n = parseInt(hex.slice(1), 16);
  const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (target - v) * k));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/* A cheap procedural surface: bands for big planets, craters for small ones. */
function surfaceTexture(body) {
  const rng = mulberry32(hashString(body.id + body.color));
  return canvasTexture(256, 128, (g, w, h) => {
    g.fillStyle = body.color;
    g.fillRect(0, 0, w, h);
    const blob = (x, y, rx, ry, color, alpha) => {
      g.globalAlpha = alpha;
      g.fillStyle = color;
      for (const dx of [-w, 0, w]) {
        g.beginPath();
        g.ellipse(x + dx, y, rx, ry, 0, 0, Math.PI * 2);
        g.fill();
      }
    };
    if (body.kind === "planet" && body.r >= 1.6) {
      let y = 0;
      while (y < h) {
        const bh = 2 + rng() * 10;
        g.globalAlpha = 0.35 + rng() * 0.45;
        g.fillStyle = rng() < 0.5 ? mix(body.color, 255, 0.25 + rng() * 0.2) : mix(body.color, 0, 0.2 + rng() * 0.25);
        g.fillRect(0, y, w, bh + 1);
        y += bh;
      }
      for (let i = 0; i < 120; i++) blob(rng() * w, rng() * h, 4 + rng() * 22, 1 + rng() * 2.5, mix(body.color, rng() < 0.5 ? 255 : 0, 0.3), 0.18);
    } else {
      for (let i = 0; i < 160; i++) {
        const r = 1 + rng() ** 3 * 16;
        blob(rng() * w, rng() * h, r, r * 0.8, rng() < 0.55 ? "#000000" : "#ffffff", 0.05 + rng() * 0.12);
      }
    }
    g.globalAlpha = 1;
  });
}

function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* A face-on glow for a level's galaxy: soft blobs along logarithmic spiral
 * arms, drawn once into one texture. Its arms use the same formula the level's
 * star systems were placed with (level.glow: radius, inner, arms, pitch_deg). */
function galaxyTexture({ radius, inner = radius * 0.09, arms = 3, pitch_deg = 14, color = "#7f9cff", core_color = "#ffd9a0" }) {
  const rng = mulberry32(7);
  return canvasTexture(1024, 1024, (g, s) => {
    const c = s / 2;
    g.globalCompositeOperation = "lighter";
    const core = g.createRadialGradient(c, c, 0, c, c, s * 0.14);
    core.addColorStop(0, rgba(core_color, 0.85));
    core.addColorStop(0.35, rgba(core_color, 0.22));
    core.addColorStop(1, rgba(core_color, 0));
    g.fillStyle = core;
    g.fillRect(0, 0, s, s);
    const wind = 1 / Math.tan((pitch_deg * Math.PI) / 180);
    const rIn = inner / radius;
    for (let i = 0; i < 9000; i++) {
      const rr = rIn + (1 - rIn) * Math.pow(rng(), 0.8);
      const theta = ((i % arms) * 2 * Math.PI) / arms + Math.log(rr / rIn) * wind + (rng() - 0.5) * 0.55;
      const x = c + Math.cos(theta) * rr * c + (rng() - 0.5) * 0.05 * c;
      const y = c - Math.sin(theta) * rr * c + (rng() - 0.5) * 0.05 * c;
      const size = 4 + rng() * 16 * (1 - rr * 0.6);
      const grad = g.createRadialGradient(x, y, 0, x, y, size);
      grad.addColorStop(0, rgba(rng() < 0.18 ? core_color : color, 0.05 * (1 - rr * 0.7)));
      grad.addColorStop(1, rgba(color, 0));
      g.fillStyle = grad;
      g.fillRect(x - size, y - size, size * 2, size * 2);
    }
  });
}

function discMaterial() {
  const tex = canvasTexture(256, 1, (g, w) => {
    for (let x = 0; x < w; x++) {
      const u = x / w;
      const a = Math.pow(1 - u, 1.6) * (0.6 + 0.4 * Math.sin(u * 40) ** 2);
      g.fillStyle = `rgba(${255},${Math.round(150 + 90 * (1 - u))},${Math.round(70 + 120 * (1 - u) ** 3)},${a})`;
      g.fillRect(x, 0, 1, 1);
    }
  });
  return new THREE.MeshBasicMaterial({ map: tex, transparent: true, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, depthWrite: false });
}

function discGeometry(inner, outer) {
  const geo = new THREE.RingGeometry(inner, outer, 128, 1);
  const pos = geo.attributes.position;
  const uv = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) uv.setXY(i, (Math.hypot(pos.getX(i), pos.getY(i)) - inner) / (outer - inner), 0.5);
  return geo;
}

function circleLine(material, segments = 128) {
  const pts = new Float32Array((segments + 1) * 3);
  for (let k = 0; k <= segments; k++) {
    const a = (k / segments) * Math.PI * 2;
    pts[k * 3] = Math.cos(a);
    pts[k * 3 + 2] = Math.sin(a);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
  const line = new THREE.Line(geo, material);
  if (material.isLineDashedMaterial) line.computeLineDistances();
  line.frustumCulled = false;
  return line;
}

export class PuzzleView {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true, powerPreference: "low-power" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    this.renderer.setClearColor(0x03040a, 1);
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(FOV, 1, 0.01, 1e7);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.14));
    this.glowTex = glowTexture();
    this.ringTex = ringTexture();
    this.sphere = new THREE.SphereGeometry(1, 40, 24);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.raycaster = new THREE.Raycaster();
    this.ghosts = [];
    this._buildBackdrop();

    this._resize = () => {
      const w = container.clientWidth || 1;
      const h = container.clientHeight || 1;
      this.renderer.setSize(w, h, false);
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
      this.width = w;
      this.height = h;
    };
    this._resize();
    this._observer = new ResizeObserver(this._resize);
    this._observer.observe(container);
  }

  /* A fixed sky: scattered stars plus a faint band, drawn at infinity. */
  _buildBackdrop() {
    const rng = mulberry32(1234);
    const count = 2600;
    const pos = new Float32Array(count * 3);
    const col = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const band = i > count * 0.55;
      let x;
      let y;
      let z;
      if (band) {
        const a = rng() * Math.PI * 2;
        const lift = (rng() - 0.5) * 0.28 * (rng() + 0.2);
        x = Math.cos(a);
        y = lift;
        z = Math.sin(a);
      } else {
        const u = rng() * 2 - 1;
        const a = rng() * Math.PI * 2;
        const s = Math.sqrt(1 - u * u);
        x = s * Math.cos(a);
        y = u;
        z = s * Math.sin(a);
      }
      const l = Math.hypot(x, y, z);
      // Tip the band so it crosses the sky at an angle, like the Milky Way.
      const ty = (y * Math.cos(1.05) - z * Math.sin(1.05)) / l;
      const tz = (y * Math.sin(1.05) + z * Math.cos(1.05)) / l;
      pos.set([x / l, ty, tz], i * 3);
      const b = band ? 0.25 + rng() * 0.3 : 0.35 + rng() ** 2 * 0.65;
      const warm = rng();
      col.set(warm < 0.2 ? [b, b * 0.85, b * 0.7] : warm > 0.8 ? [b * 0.8, b * 0.88, b] : [b, b, b], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("color", new THREE.BufferAttribute(col, 3));
    this.sky = new THREE.Points(
      geo,
      new THREE.PointsMaterial({ size: 1.6, sizeAttenuation: false, vertexColors: true, transparent: true, depthWrite: false, depthTest: false }),
    );
    this.sky.scale.setScalar(1e6);
    this.sky.renderOrder = -10;
    this.sky.frustumCulled = false;
    this.scene.add(this.sky);
  }

  _sprite(color, opacity = 1, texture = this.glowTex) {
    const s = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: texture, color, transparent: true, opacity, blending: THREE.AdditiveBlending, depthWrite: false }),
    );
    this.group.add(s);
    return s;
  }

  _clearLevel() {
    for (const child of [...this.group.children]) {
      this.group.remove(child);
      child.traverse((o) => {
        if (o.geometry && o.geometry !== this.sphere) o.geometry.dispose();
        const m = o.material;
        if (m) {
          if (m.map && m.map !== this.glowTex && m.map !== this.ringTex) m.map.dispose();
          m.dispose();
        }
      });
    }
    this.ghosts = [];
  }

  setLevel(level, sys, fields) {
    this._clearLevel();
    this.level = level;
    this.sys = sys;
    this.fields = fields;
    this.fieldT = NaN;
    sys.at(0);

    this.starEntries = [];
    this.bodies = sys.bodies.map((b, i) => {
      let material;
      if (b.kind === "star") material = new THREE.MeshBasicMaterial({ color: b.color });
      else if (b.kind === "blackhole") material = new THREE.MeshBasicMaterial({ color: 0x000000 });
      else material = new THREE.MeshStandardMaterial({ map: surfaceTexture(b), roughness: 1, metalness: 0 });
      const mesh = new THREE.Mesh(this.sphere, material);
      mesh.rotation.z = b.kind === "planet" ? 0.3 : 0;
      this.group.add(mesh);
      const entry = { body: b, index: i, mesh, glow: null, light: null, disc: null, lens: null, orbit: null };
      if (b.kind === "star") {
        entry.glow = this._sprite(b.color, 0.9);
        this.starEntries.push(entry);
      }
      if (b.kind === "blackhole") {
        entry.disc = new THREE.Mesh(discGeometry(1.6, 6), discMaterial());
        this.group.add(entry.disc);
        entry.glow = this._sprite("#ff9c4a", 0.35);
        entry.lens = this._sprite("#ffe7c0", 0.55, this.ringTex);
      }
      if (b.orbit) {
        const T = 2 * Math.PI * Math.sqrt(b.orbit.a ** 3 / b.mu);
        const pts = new Float32Array(257 * 3);
        for (let k = 0; k <= 256; k++) {
          const s = railState(b.orbit, b.mu, (T * k) / 256);
          pts[k * 3] = s[0];
          pts[k * 3 + 1] = s[2];
          pts[k * 3 + 2] = -s[1];
        }
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(pts, 3));
        entry.orbit = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: b.color, transparent: true, opacity: 0.25, depthWrite: false }));
        entry.orbit.frustumCulled = false;
        this.group.add(entry.orbit);
      }
      return entry;
    });
    // Four point lights at most, moved each frame to the stars nearest the
    // camera, so a galaxy of forty suns costs the same as a solar system.
    this.lights = this.starEntries.slice(0, 4).map(() => {
      const light = new THREE.PointLight(0xffffff, 2.6, 0, 0);
      this.group.add(light);
      return light;
    });
    if (!this.lights.length) {
      // A level with no star (Earth and Moon, say) is lit by a distant sun.
      const sun = new THREE.DirectionalLight(0xfff4e0, 2.4);
      sun.position.copy(toThree(level.sunlight || [1, 0.4, 0.6]));
      this.group.add(sun);
    }

    this.fieldPoints = fields.map((f) => {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(f.count * 3), 3));
      const pts = new THREE.Points(
        geo,
        new THREE.PointsMaterial({ color: 0xc2b39a, size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0.85, depthWrite: false }),
      );
      pts.frustumCulled = false;
      this.group.add(pts);
      return { points: pts, buffer: new Float32Array(f.count * 3) };
    });

    let extent = 1;
    for (let i = 0; i < sys.bodies.length; i++) extent = Math.max(extent, Math.hypot(sys.px[i], sys.py[i], sys.pz[i]));
    this.extent = extent;
    this.grid = new THREE.PolarGridHelper(extent * 1.15, 16, 6, 96, 0x34406a, 0x1c2340);
    this.grid.material.transparent = true;
    this.grid.material.opacity = 0.3;
    this.grid.material.depthWrite = false;
    this.group.add(this.grid);
    if (level.glow?.radius > 0) {
      const glow = new THREE.Mesh(
        new THREE.PlaneGeometry(1, 1),
        new THREE.MeshBasicMaterial({ map: galaxyTexture(level.glow), transparent: true, opacity: 0.65, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.DoubleSide }),
      );
      glow.rotation.x = -Math.PI / 2;
      glow.scale.set(level.glow.radius * 2, level.glow.radius * 2, 1);
      glow.renderOrder = -5;
      this.group.add(glow);
    }

    const g = level.goal;
    this.markers = {};
    if (g.type === "reach") {
      this.markers.zone = this._sprite("#ffcf6b", 0.9, this.ringTex);
      this.markers.haze = new THREE.Mesh(this.sphere, new THREE.MeshBasicMaterial({ color: 0xffcf6b, transparent: true, opacity: 0.06, depthWrite: false }));
      this.group.add(this.markers.haze);
    } else if (g.type === "waypoints") {
      this.markers.rings = g.points.map(() => this._sprite("#ffcf6b", 0.6, this.ringTex));
    } else if (g.type === "orbit") {
      this.markers.outer = circleLine(new THREE.LineDashedMaterial({ color: 0x8fb4ff, dashSize: 0.035, gapSize: 0.03, transparent: true, opacity: 0.55, depthWrite: false }));
      this.markers.inner = circleLine(new THREE.LineBasicMaterial({ color: 0xff8a78, transparent: true, opacity: 0.4, depthWrite: false }));
      this.group.add(this.markers.outer, this.markers.inner);
    } else if (g.type === "land") {
      this.markers.pad = this._sprite("#7ad0b0", 0.85, this.ringTex);
    }

    this.launchRing = this._sprite("#8fb4ff", 0.9, this.ringTex);
    this.probeHalo = this._sprite("#8fb4ff", 0.9);
    this.probeCore = this._sprite("#ffffff", 1);
    const arrowGeo = new THREE.BufferGeometry();
    arrowGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(6), 3));
    this.arrow = new THREE.Line(arrowGeo, new THREE.LineBasicMaterial({ color: 0x8fb4ff, transparent: true, opacity: 0.9, depthWrite: false }));
    this.arrow.frustumCulled = false;
    this.arrowHead = new THREE.Mesh(new THREE.ConeGeometry(0.35, 1, 14), new THREE.MeshBasicMaterial({ color: 0x8fb4ff }));
    this.group.add(this.arrow, this.arrowHead);
    this.aim = null;

    const previewGeo = new THREE.BufferGeometry();
    previewGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(PREVIEW_MAX * 3), 3));
    this.preview = new THREE.Line(previewGeo, new THREE.LineDashedMaterial({ color: 0x8fb4ff, dashSize: 1, gapSize: 0.7, transparent: true, opacity: 0.85, depthWrite: false }));
    this.preview.frustumCulled = false;
    this.preview.visible = false;

    const trailGeo = new THREE.BufferGeometry();
    trailGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(TRAIL_MAX * 3), 3));
    this.trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: 0xd9b8ff, transparent: true, opacity: 0.95, depthWrite: false }));
    this.trail.frustumCulled = false;
    this.trail.visible = false;
    this.group.add(this.preview, this.trail);
  }

  /* Copy flat physics xyz into a line's buffer, thinning if there are too many. */
  _fillLine(line, points, max) {
    const count = Math.floor(points.length / 3);
    const stride = Math.max(1, Math.ceil(count / (max - 1)));
    const arr = line.geometry.attributes.position.array;
    let n = 0;
    for (let i = 0; i < count; i += stride) {
      arr[n * 3] = points[i * 3];
      arr[n * 3 + 1] = points[i * 3 + 2];
      arr[n * 3 + 2] = -points[i * 3 + 1];
      n++;
    }
    if ((count - 1) % stride !== 0 && count > 0) {
      const i = count - 1;
      arr[n * 3] = points[i * 3];
      arr[n * 3 + 1] = points[i * 3 + 2];
      arr[n * 3 + 2] = -points[i * 3 + 1];
      n++;
    }
    line.geometry.setDrawRange(0, n);
    line.geometry.attributes.position.needsUpdate = true;
    return n;
  }

  setPreview(points, hit = false) {
    if (!points || points.length < 6) {
      this.preview.visible = false;
      return;
    }
    const n = this._fillLine(this.preview, points, PREVIEW_MAX);
    // Pad the unused tail with the last point so line distances do not jump.
    const arr = this.preview.geometry.attributes.position.array;
    for (let k = n; k < PREVIEW_MAX; k++) arr.copyWithin(k * 3, (n - 1) * 3, n * 3);
    this.preview.computeLineDistances();
    this.preview.material.color.set(hit ? 0xff8a78 : 0x8fb4ff);
    this.preview.visible = true;
  }

  setTrail(points) {
    if (!points || points.length < 6) {
      this.trail.visible = false;
      return;
    }
    this._fillLine(this.trail, points, TRAIL_MAX);
    this.trail.visible = true;
  }

  addGhost(points) {
    const count = Math.min(Math.floor(points.length / 3), TRAIL_MAX);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0x9fb8ff, transparent: true, opacity: 0.25, depthWrite: false }));
    line.frustumCulled = false;
    this._fillLine(line, points, count);
    this.group.add(line);
    this.ghosts.push(line);
    while (this.ghosts.length > MAX_GHOSTS) {
      const old = this.ghosts.shift();
      this.group.remove(old);
      old.geometry.dispose();
      old.material.dispose();
    }
    this.ghosts.forEach((g, k) => (g.material.opacity = 0.08 + (0.22 * (k + 1)) / this.ghosts.length));
  }

  clearGhosts() {
    for (const g of this.ghosts) {
      this.group.remove(g);
      g.geometry.dispose();
      g.material.dispose();
    }
    this.ghosts = [];
  }

  /* The aim arrow: { origin, dir, length } in physics units, or null. */
  setAim(aim) {
    this.aim = aim;
  }

  pxPerUnitAt(depth) {
    return this.height / (2 * Math.max(depth, 1e-9) * Math.tan((FOV * Math.PI) / 360));
  }

  /* How many pixels across a body was drawn last frame, from its centre. */
  bodyRadiusPx(index) {
    return this.bodies?.[index]?.screenRadius || 0;
  }

  project(p) {
    const v = toThree(p).project(this.camera);
    return { x: ((v.x + 1) / 2) * this.width, y: ((1 - v.y) / 2) * this.height, visible: v.z > -1 && v.z < 1 };
  }

  /* Where a screen point meets the horizontal plane at height z, or null. */
  planeHit(clientX, clientY, z) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
    const out = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -z), out) ? fromThree(out) : null;
  }

  /* The camera's right and up directions, in physics axes. */
  screenAxes() {
    const m = this.camera.matrixWorld;
    return { right: fromThree(new THREE.Vector3().setFromMatrixColumn(m, 0)), up: fromThree(new THREE.Vector3().setFromMatrixColumn(m, 1)) };
  }

  /* view: { target, yaw, pitch, dist }. st: { t, phase, probe, waypoint, launchOrigin, showGrid, now } */
  render(view, st) {
    const cam = this.camera;
    const target = toThree(view.target);
    const dir = new THREE.Vector3(Math.cos(view.pitch) * Math.sin(view.yaw), Math.sin(view.pitch), Math.cos(view.pitch) * Math.cos(view.yaw));
    cam.position.copy(target).addScaledVector(dir, view.dist);
    cam.up.set(0, 1, 0);
    cam.lookAt(target);
    cam.near = Math.max(1e-3, view.dist * 1e-4);
    cam.updateProjectionMatrix();
    cam.updateMatrixWorld();
    this.sky.position.copy(cam.position);

    const sys = this.sys.at(st.t);
    const pulse = 1 + 0.07 * Math.sin(st.now / 280);
    const pxAt = (v) => this.pxPerUnitAt(v.distanceTo(cam.position));

    for (const e of this.bodies) {
      const b = e.body;
      const i = e.index;
      e.mesh.position.set(sys.px[i], sys.pz[i], -sys.py[i]);
      const ppu = pxAt(e.mesh.position);
      const r = Math.max(b.r, (MIN_PX[b.kind] || 3) / ppu);
      e.mesh.scale.setScalar(r);
      e.screenRadius = r * ppu;
      if (e.glow) {
        e.glow.position.copy(e.mesh.position);
        e.glow.scale.setScalar(b.kind === "star" ? Math.max(r * 9, 70 / ppu) : Math.max(r * 7, 40 / ppu));
      }
      if (e.disc) {
        e.disc.position.copy(e.mesh.position);
        e.disc.scale.setScalar(r);
        e.disc.rotation.set(-Math.PI / 2 + 0.38, 0, st.now * 0.00025);
        e.lens.position.copy(e.mesh.position);
        e.lens.scale.setScalar(r * 2.6);
      }
      if (e.orbit) {
        const parent = this.bodies[b.parentIndex].mesh.position;
        e.orbit.position.copy(parent);
        const px = b.orbit.a * pxAt(parent);
        e.orbit.material.opacity = 0.25 * Math.min(1, Math.max(0, (px - 8) / 30));
      }
    }

    if (this.lights.length) {
      const near = this.starEntries.length > this.lights.length ? [...this.starEntries].sort((a, b) => a.mesh.position.distanceToSquared(target) - b.mesh.position.distanceToSquared(target)) : this.starEntries;
      this.lights.forEach((light, k) => {
        light.position.copy(near[k].mesh.position);
        light.color.set(near[k].body.color);
      });
    }

    if (this.fieldT !== st.t) {
      this.fields.forEach((f, k) => {
        const { points, buffer } = this.fieldPoints[k];
        f.positions(sys, st.t, buffer);
        const arr = points.geometry.attributes.position.array;
        for (let j = 0; j < f.count; j++) {
          arr[j * 3] = buffer[j * 3];
          arr[j * 3 + 1] = buffer[j * 3 + 2];
          arr[j * 3 + 2] = -buffer[j * 3 + 1];
        }
        points.geometry.attributes.position.needsUpdate = true;
      });
      this.fieldT = st.t;
    }

    const g = this.level.goal;
    const bodyPos = (id) => this.bodies[sys.index.get(id)].mesh.position;
    if (g.type === "reach") {
      const p = bodyPos(g.target);
      const tb = this.sys.body(g.target);
      const ppu = pxAt(p);
      this.markers.zone.position.copy(p);
      this.markers.zone.scale.setScalar(Math.max(2 * (tb.r + g.radius), 30 / ppu) * pulse);
      this.markers.haze.position.copy(p);
      this.markers.haze.scale.setScalar(tb.r + g.radius);
    } else if (g.type === "waypoints") {
      g.points.forEach((w, k) => {
        const s = this.markers.rings[k];
        s.position.copy(toThree(waypointPosition(sys, w, st.t)));
        const ppu = pxAt(s.position);
        const next = k === st.waypoint;
        s.scale.setScalar(Math.max(2 * w.radius, 24 / ppu) * (next ? pulse : 1));
        s.material.color.set(k < st.waypoint ? 0x7ad0b0 : 0xffcf6b);
        s.material.opacity = k < st.waypoint ? 0.35 : next ? 1 : 0.45;
      });
    } else if (g.type === "orbit") {
      const p = bodyPos(g.target);
      const tb = this.sys.body(g.target);
      this.markers.outer.position.copy(p);
      this.markers.outer.scale.setScalar(g.max_apoapsis);
      this.markers.inner.position.copy(p);
      this.markers.inner.scale.setScalar(tb.r + g.min_altitude);
    } else if (g.type === "land") {
      const p = bodyPos(g.target);
      const tb = this.sys.body(g.target);
      this.markers.pad.position.copy(p);
      this.markers.pad.scale.setScalar(Math.max(tb.r * 2.9, 30 / pxAt(p)) * pulse);
    }

    const aiming = st.phase === "aim" && st.launchOrigin;
    this.launchRing.visible = !!aiming;
    if (aiming) {
      const p = toThree(st.launchOrigin);
      this.launchRing.position.copy(p);
      this.launchRing.scale.setScalar((46 / pxAt(p)) * pulse);
    }
    const showArrow = aiming && this.aim;
    this.arrow.visible = !!showArrow;
    this.arrowHead.visible = !!showArrow;
    if (showArrow) {
      const a = this.aim;
      const from = toThree(a.origin);
      const d = toThree(a.dir).normalize();
      const len = a.lengthPx / pxAt(from);
      const tip = from.clone().addScaledVector(d, len);
      const arr = this.arrow.geometry.attributes.position.array;
      arr.set([from.x, from.y, from.z, tip.x, tip.y, tip.z]);
      this.arrow.geometry.attributes.position.needsUpdate = true;
      this.arrowHead.position.copy(tip);
      this.arrowHead.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), d);
      this.arrowHead.scale.setScalar(16 / pxAt(tip));
    }

    const probe = st.probe;
    this.probeHalo.visible = !!probe;
    this.probeCore.visible = !!probe;
    if (probe) {
      const p = toThree([probe.x, probe.y, probe.z]);
      const ppu = pxAt(p);
      this.probeHalo.position.copy(p);
      this.probeHalo.scale.setScalar(26 / ppu);
      this.probeCore.position.copy(p);
      this.probeCore.scale.setScalar(7 / ppu);
    }

    this.grid.visible = st.showGrid;
    const dash = view.dist * 0.012;
    this.preview.material.dashSize = dash;
    this.preview.material.gapSize = dash * 0.8;
    this.renderer.render(this.scene, cam);
  }

  dispose() {
    this._observer.disconnect();
    this._clearLevel();
    this.sky.geometry.dispose();
    this.sky.material.dispose();
    this.sphere.dispose();
    this.glowTex.dispose();
    this.ringTex.dispose();
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}
