/* The map's 3D scene: bodies, orbits, the star catalog and the galaxy model.
 *
 * Scale is the whole problem. The map runs from a moon a few kilometres wide
 * out to a galaxy 30 kiloparsecs across -- a range of about 10^17 -- and a GPU
 * works in 32-bit floats. So nothing is ever placed at its true coordinate.
 * Every frame, positions are worked out in doubles on the CPU in AU, the
 * camera's target is subtracted, and the result is scaled so the camera always
 * sits SCENE_DIST units from its target (a "floating origin"). Big static
 * point clouds (stars, the galaxy) keep their own parsec coordinates and get
 * the same subtract-and-scale as an object transform.
 *
 * Axes: positions are J2000 ecliptic (x toward the March equinox, z toward
 * the ecliptic north pole). Three.js is y-up, so ecliptic (x, y, z) is drawn
 * at (x, z, -y).
 */

import * as THREE from "three";

import { bvToTemperature, temperatureToRgb } from "../../core/color.js";
import { mulberry32 } from "../../core/nbody.js";
import { buildGalaxyModel, galacticToEcliptic } from "../../core/galaxy.js";
import { poleFrame } from "../../core/ephemeris.js";
import { AU_KM, PARSEC_AU } from "../../core/units.js";

export const SCENE_DIST = 10;
const FOV = 50;

// Smallest on-screen radius, in CSS pixels, per kind of body in "enlarged" mode.
const MIN_PIXELS = { star: 7, planet: 3.5, dwarf: 2.6, moon: 2.2 };

export const toThree = (v) => new THREE.Vector3(v[0], v[2], -v[1]);
export const fromThree = (v) => [v.x, -v.z, v.y];

const smooth = (a, b, x) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/* --- procedural surfaces ----------------------------------------------------- */

function surfaceTexture(body) {
  const w = 512;
  const h = 256;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext("2d");
  const rng = mulberry32(hashString(body.id));
  const blob = (x, y, rx, ry, color, alpha) => {
    g.globalAlpha = alpha;
    g.fillStyle = color;
    for (const dx of [-w, 0, w]) {
      g.beginPath();
      g.ellipse(x + dx, y, rx, ry, 0, 0, Math.PI * 2);
      g.fill();
    }
  };

  g.fillStyle = body.color;
  g.fillRect(0, 0, w, h);
  if (body.kind === "star") {
    for (let i = 0; i < 2600; i++) {
      blob(rng() * w, rng() * h, 2 + rng() * 5, 2 + rng() * 4, rng() < 0.5 ? "#fff3c0" : "#e8902c", 0.16);
    }
  } else if (body.bands) {
    let y = 0;
    while (y < h) {
      const bh = 3 + rng() * 16;
      g.globalAlpha = 0.55 + rng() * 0.45;
      g.fillStyle = body.bands[Math.floor(rng() * body.bands.length)];
      g.fillRect(0, y, w, bh + 1);
      y += bh;
    }
    for (let i = 0; i < 500; i++) {
      blob(rng() * w, rng() * h, 6 + rng() * 30, 1 + rng() * 3, body.bands[Math.floor(rng() * body.bands.length)], 0.18);
    }
    if (body.id === "jupiter") blob(w * 0.3, h * 0.64, 22, 11, "#c0573a", 0.85);
  } else if (body.surface === "ocean") {
    g.fillStyle = "#1c4c96";
    g.fillRect(0, 0, w, h);
    for (let c = 0; c < 7; c++) {
      const cx = rng() * w;
      const cy = h * (0.22 + rng() * 0.56);
      for (let i = 0; i < 70; i++) {
        blob(cx + (rng() - 0.5) * 120, cy + (rng() - 0.5) * 70, 6 + rng() * 18, 4 + rng() * 12, rng() < 0.6 ? "#3f7a3a" : "#9a8455", 0.9);
      }
    }
    g.globalAlpha = 0.95;
    g.fillStyle = "#f2f6fa";
    g.fillRect(0, 0, w, 14);
    g.fillRect(0, h - 18, w, 18);
    for (let i = 0; i < 180; i++) blob(rng() * w, rng() * h, 10 + rng() * 40, 2 + rng() * 5, "#ffffff", 0.28);
  } else {
    for (let i = 0; i < 260; i++) {
      const r = 1 + rng() ** 3 * 22;
      blob(rng() * w, rng() * h, r, r * 0.8, rng() < 0.55 ? "#000000" : "#ffffff", 0.06 + rng() * 0.12);
    }
    if (body.id === "mars") {
      g.globalAlpha = 0.9;
      g.fillStyle = "#f3efe8";
      g.fillRect(0, 0, w, 9);
      g.fillRect(0, h - 7, w, 7);
    }
  }
  g.globalAlpha = 1;
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

function ringMesh(body) {
  const inner = body.rings.inner_km / body.radius_km;
  const outer = body.rings.outer_km / body.radius_km;
  const geo = new THREE.RingGeometry(inner, outer, 160, 1);
  const pos = geo.attributes.position;
  const uv = geo.attributes.uv;
  for (let i = 0; i < pos.count; i++) {
    const r = Math.hypot(pos.getX(i), pos.getY(i));
    uv.setXY(i, (r - inner) / (outer - inner), 0.5);
  }
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 1;
  const g = canvas.getContext("2d");
  const rng = mulberry32(hashString(body.id + "rings"));
  for (let x = 0; x < 512; x++) {
    const gap = body.id === "saturn" && x > 300 && x < 318; // the Cassini Division
    const a = gap ? 0.04 : 0.25 + rng() * 0.6;
    g.fillStyle = body.rings.color;
    g.globalAlpha = a;
    g.fillRect(x, 0, 1, 1);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.MeshBasicMaterial({
    map: tex,
    transparent: true,
    side: THREE.DoubleSide,
    depthWrite: false,
    opacity: body.id === "saturn" ? 0.95 : 0.35,
  });
  const mesh = new THREE.Mesh(geo, mat);
  mesh.rotation.x = -Math.PI / 2;
  return mesh;
}

function glowTexture(stops) {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  for (const [at, color] of stops) grad.addColorStop(at, color);
  g.fillStyle = grad;
  g.fillRect(0, 0, 128, 128);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* --- shaders ---------------------------------------------------------------- */

const STAR_VERTEX = /* glsl */ `
  attribute float absmag;
  attribute vec3 starColor;
  uniform float uUnitsPerPc;
  uniform float uPixelRatio;
  uniform float uLimit;
  uniform float uFloor;
  varying vec3 vColor;
  varying float vAlpha;
  #include <common>
  #include <logdepthbuf_pars_vertex>
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float d = length(mv.xyz);
    float dpc = max(d / uUnitsPerPc, 1e-7);
    // Apparent magnitude as seen from the camera, wherever the camera is.
    float m = absmag + 5.0 * log(dpc) * 0.4342944819 - 5.0;
    float b = pow(10.0, -0.4 * (m - uLimit));
    float size = 1.3 * pow(b, 0.33);
    vAlpha = max(clamp(sqrt(b), 0.0, 1.0), uFloor);
    size = max(size, uFloor > 0.0 ? 1.2 : 0.0);
    if (size < 0.8) { vAlpha *= size / 0.8; size = 0.8; }
    if (vAlpha < 0.025) size = 0.0;
    vColor = starColor;
    // Far stars are pulled in along their line of sight so they stay inside
    // the depth range; direction is all that matters for a point that far.
    mv.xyz = (mv.xyz / d) * min(d, 5.0e8);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = min(size, 16.0) * uPixelRatio;
    #include <logdepthbuf_vertex>
  }
`;

const POINT_FRAGMENT = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  #include <common>
  #include <logdepthbuf_pars_fragment>
  void main() {
    #include <logdepthbuf_fragment>
    float r = length(gl_PointCoord - 0.5) * 2.0;
    float a = smoothstep(1.0, 0.0, r);
    gl_FragColor = vec4(vColor * vAlpha * a * a, 1.0);
  }
`;

const GALAXY_VERTEX = /* glsl */ `
  attribute vec3 color;
  uniform float uUnitsPerPc;
  uniform float uFocalPx;
  uniform float uPixelRatio;
  uniform float uFade;
  varying vec3 vColor;
  varying float vAlpha;
  #include <common>
  #include <logdepthbuf_pars_vertex>
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    float d = length(mv.xyz);
    float size = clamp(90.0 * uUnitsPerPc * uFocalPx / d, 1.0, 3.2);
    vColor = color;
    vAlpha = uFade * 0.32;
    mv.xyz = (mv.xyz / d) * min(d, 5.0e8);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uFade > 0.001 ? size * uPixelRatio : 0.0;
    #include <logdepthbuf_vertex>
  }
`;

/* --- the view ----------------------------------------------------------------- */

export class MapView {
  constructor(container, ephemeris) {
    this.container = container;
    this.eph = ephemeris;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, logarithmicDepthBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setClearColor(0x020309, 1);
    container.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(FOV, 1, 1e-6, 1e10);
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.07));
    this.sunLight = new THREE.PointLight(0xfff4e0, 3.2, 0, 0);
    this.scene.add(this.sunLight);

    this.bodies = new Map();
    this.screen = new Map();
    this._buildBodies();
    this._buildGalaxy();
    this.stars = null;

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

  _buildBodies() {
    const sphere = new THREE.SphereGeometry(1, 64, 40);
    for (const body of this.eph.list()) {
      const tex = surfaceTexture(body);
      const material =
        body.kind === "star"
          ? new THREE.MeshBasicMaterial({ map: tex, color: 0xffffff })
          : new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 });
      const mesh = new THREE.Mesh(sphere, material);
      if (body.pole) {
        const axis = toThree(poleFrame(body.pole)[2]).normalize();
        mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), axis);
      }
      if (body.rings) mesh.add(ringMesh(body));
      this.scene.add(mesh);

      let orbit = null;
      if (body.elements) {
        const geo = new THREE.BufferGeometry();
        geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(257 * 3), 3));
        orbit = new THREE.Line(
          geo,
          new THREE.LineBasicMaterial({ color: body.color, transparent: true, opacity: 0.4, depthWrite: false }),
        );
        orbit.frustumCulled = false;
        this.scene.add(orbit);
      }
      this.bodies.set(body.id, { body, mesh, orbit, orbitJd: NaN });
    }

    this.sunGlow = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: glowTexture([
          [0, "rgba(255,244,214,1)"],
          [0.12, "rgba(255,214,140,0.85)"],
          [0.35, "rgba(255,160,70,0.22)"],
          [1, "rgba(255,120,40,0)"],
        ]),
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        transparent: true,
      }),
    );
    this.scene.add(this.sunGlow);
  }

  _buildGalaxy() {
    const model = buildGalaxyModel({ count: 70000 });
    this.galaxyModel = model;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(toThreeArray(model.positions), 3));
    geo.setAttribute("color", new THREE.BufferAttribute(model.colors, 3));
    this.galaxyUniforms = {
      uUnitsPerPc: { value: 1 },
      uFocalPx: { value: 500 },
      uPixelRatio: { value: this.renderer.getPixelRatio() },
      uFade: { value: 0 },
    };
    const points = new THREE.Points(
      geo,
      new THREE.ShaderMaterial({
        uniforms: this.galaxyUniforms,
        vertexShader: GALAXY_VERTEX,
        fragmentShader: POINT_FRAGMENT,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        transparent: true,
      }),
    );
    points.frustumCulled = false;
    points.renderOrder = -2;

    // A soft face-on glow drawn from the same points, lying in the galactic
    // plane, so the galaxy reads as a disc and not only as dots.
    const size = 256;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const g = canvas.getContext("2d");
    g.globalCompositeOperation = "lighter";
    const extent = model.extent_pc;
    for (let i = 0; i < model.plane.length / 2; i++) {
      const x = ((model.plane[i * 2] / extent + 1) / 2) * size;
      const y = ((1 - model.plane[i * 2 + 1] / extent) / 2) * size;
      const c = model.colors;
      g.fillStyle = `rgba(${(c[i * 3] * 255) | 0},${(c[i * 3 + 1] * 255) | 0},${(c[i * 3 + 2] * 255) | 0},0.025)`;
      g.fillRect(x, y, 1.5, 1.5);
    }
    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    this.galaxyGlowMaterial = new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      side: THREE.DoubleSide,
      opacity: 0,
    });
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(2 * extent, 2 * extent), this.galaxyGlowMaterial);
    const ex = toThree(galacticToEcliptic([1, 0, 0]));
    const ey = toThree(galacticToEcliptic([0, 1, 0]));
    const ez = toThree(galacticToEcliptic([0, 0, 1]));
    glow.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(ex, ey, ez));
    glow.position.copy(toThree(model.labels[0].position));
    glow.renderOrder = -3;

    this.galaxy = new THREE.Group();
    this.galaxy.add(points, glow);
    this.scene.add(this.galaxy);
  }

  /* Stars from the packed catalog buffer (see tools/build_star_catalog.py). */
  setStars(buffer) {
    const header = new DataView(buffer, 0, 12);
    const magic = String.fromCharCode(...new Uint8Array(buffer, 0, 4));
    if (magic !== "CSTR" || header.getUint32(4, true) !== 1) throw new Error("Unrecognised star file");
    const count = header.getUint32(8, true);
    const rec = new Float32Array(buffer, 12, count * 6);
    const pos = new Float32Array(count * 3);
    const absmag = new Float32Array(count);
    const color = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const o = i * 6;
      pos[i * 3] = rec[o];
      pos[i * 3 + 1] = rec[o + 2];
      pos[i * 3 + 2] = -rec[o + 1];
      absmag[i] = rec[o + 3];
      color.set(temperatureToRgb(bvToTemperature(rec[o + 5])), i * 3);
    }
    this.starRecords = rec;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("absmag", new THREE.BufferAttribute(absmag, 1));
    geo.setAttribute("starColor", new THREE.BufferAttribute(color, 3));
    this.starUniforms = {
      uUnitsPerPc: { value: 1 },
      uPixelRatio: { value: this.renderer.getPixelRatio() },
      uLimit: { value: 6.5 },
      uFloor: { value: 0 },
    };
    this.stars = new THREE.Points(
      geo,
      new THREE.ShaderMaterial({
        uniforms: this.starUniforms,
        vertexShader: STAR_VERTEX,
        fragmentShader: POINT_FRAGMENT,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
        transparent: true,
      }),
    );
    this.stars.frustumCulled = false;
    this.stars.renderOrder = -1;
    this.scene.add(this.stars);
    return count;
  }

  /* Heliocentric ecliptic position of catalog star i, in AU. */
  starPosition(i) {
    const r = this.starRecords;
    return [r[i * 6] * PARSEC_AU, r[i * 6 + 1] * PARSEC_AU, r[i * 6 + 2] * PARSEC_AU];
  }

  cameraOffsetDir(yaw, pitch) {
    return new THREE.Vector3(Math.cos(pitch) * Math.sin(yaw), Math.sin(pitch), Math.cos(pitch) * Math.cos(yaw));
  }

  /* Camera position in heliocentric ecliptic AU. */
  cameraWorld(view) {
    const d = fromThree(this.cameraOffsetDir(view.yaw, view.pitch));
    return [view.target[0] + d[0] * view.dist, view.target[1] + d[1] * view.dist, view.target[2] + d[2] * view.dist];
  }

  /* Scene units per AU for a view. */
  scaleFor(view) {
    return SCENE_DIST / view.dist;
  }

  pxPerUnitAt(depth) {
    return this.height / (2 * depth * Math.tan((FOV * Math.PI) / 360));
  }

  /* Screen position (CSS px) of a heliocentric AU position, or null if behind. */
  project(p, view) {
    const s = this.scaleFor(view);
    const v = toThree([(p[0] - view.target[0]) * s, (p[1] - view.target[1]) * s, (p[2] - view.target[2]) * s]);
    const depth = v.distanceTo(this.camera.position);
    v.project(this.camera);
    if (v.z > 1 || v.z < -1) return null;
    return { x: ((v.x + 1) / 2) * this.width, y: ((1 - v.y) / 2) * this.height, depth };
  }

  render(view, jd, opts) {
    const s = this.scaleFor(view);
    const cam = this.camera;
    cam.position.copy(this.cameraOffsetDir(view.yaw, view.pitch).multiplyScalar(SCENE_DIST));
    cam.up.set(0, 1, 0);
    cam.lookAt(0, 0, 0);
    cam.updateMatrixWorld();

    const camWorld = this.cameraWorld(view);
    const sunDistance = Math.hypot(camWorld[0], camWorld[1], camWorld[2]);
    // Planets vanish as you leave the solar system; from light-years out
    // they would be invisible anyway.
    const system = 1 - smooth(4e3, 6e4, sunDistance);
    const rel = (p) => [(p[0] - view.target[0]) * s, (p[1] - view.target[1]) * s, (p[2] - view.target[2]) * s];
    this.screen.clear();

    for (const [id, entry] of this.bodies) {
      const { body, mesh, orbit } = entry;
      const p = this.eph.position(id, jd);
      mesh.position.copy(toThree(rel(p)));
      const depth = Math.max(mesh.position.distanceTo(cam.position), 1e-9);
      const ppu = this.pxPerUnitAt(depth);
      const trueR = (body.radius_km / AU_KM) * s;
      let minPx = opts.trueScale ? 0 : MIN_PIXELS[body.kind] || 2;
      if (body.kind === "star") minPx = opts.trueScale ? 0 : 2 + 5 * system;
      const r = Math.max(trueR, minPx / ppu);
      mesh.scale.setScalar(r);

      const scr = new THREE.Vector3().copy(mesh.position).project(cam);
      const onScreen = scr.z < 1 && scr.z > -1;
      const info = {
        x: ((scr.x + 1) / 2) * this.width,
        y: ((1 - scr.y) / 2) * this.height,
        r: r * ppu,
        visible: onScreen,
        depth,
      };
      this.screen.set(id, info);

      let show = body.kind === "star" || system > 0.01;
      if (body.kind === "moon" && !opts.trueScale) {
        const parent = this.screen.get(body.parent);
        const gap = parent ? Math.hypot(info.x - parent.x, info.y - parent.y) : 1e9;
        // A moon drawn on top of its enlarged planet only hides the planet.
        if (parent && gap < parent.r + info.r + 3) show = false;
        info.crowded = parent ? gap < parent.r + 14 : false;
      }
      mesh.visible = show;
      info.visible = info.visible && show;

      if (orbit) {
        const parentPos = body.parent ? this.eph.position(body.parent, jd) : [0, 0, 0];
        if (entry.orbitJd !== jd) {
          orbit.geometry.attributes.position.array.set(toThreeArray(this.eph.orbitPath(id, jd, 256)));
          orbit.geometry.attributes.position.needsUpdate = true;
          entry.orbitJd = jd;
        }
        orbit.position.copy(toThree(rel(parentPos)));
        orbit.scale.setScalar(s);
        const pdepth = Math.max(orbit.position.distanceTo(cam.position), 1e-9);
        const a = (body.elements.a_au ?? (body.elements.a_km ? body.elements.a_km / AU_KM : body.elements.a[0])) * s;
        const orbitPx = a * this.pxPerUnitAt(pdepth);
        const fade = smooth(10, 60, orbitPx) * (1 - smooth(4e5, 2e6, orbitPx)) * system;
        const selected = opts.selectedId === id;
        orbit.material.opacity = (selected ? 0.8 : body.kind === "moon" ? 0.28 : 0.38) * fade;
        orbit.visible = opts.showOrbits && fade > 0.01;
        info.orbitPx = orbitPx;
      }
    }

    const sun = this.bodies.get("sun");
    this.sunLight.position.copy(sun.mesh.position);
    const sunInfo = this.screen.get("sun");
    const glowPx = Math.max(sunInfo.r * 7, 14 + 60 * system);
    this.sunGlow.position.copy(sun.mesh.position);
    this.sunGlow.scale.setScalar((glowPx * 2) / this.pxPerUnitAt(sunInfo.depth));
    this.sunGlow.material.opacity = 0.35 + 0.65 * system;

    // Clouds in parsecs share one transform: the Sun's place, scaled.
    const unitsPerPc = s * PARSEC_AU;
    const origin = toThree(rel([0, 0, 0]));
    if (this.stars) {
      this.stars.position.copy(origin);
      this.stars.scale.setScalar(unitsPerPc);
      this.stars.visible = opts.showStars;
      this.starUniforms.uUnitsPerPc.value = unitsPerPc;
      this.starUniforms.uLimit.value = opts.starLimit;
      this.starUniforms.uFloor.value = 0.04 * smooth(2e7, 4e8, sunDistance);
    }
    this.galaxy.position.copy(origin);
    this.galaxy.scale.setScalar(unitsPerPc);
    const galaxyFade = opts.showGalaxy ? smooth(3e7, 6e8, view.dist) : 0;
    this.galaxy.visible = galaxyFade > 0.001;
    this.galaxyUniforms.uUnitsPerPc.value = unitsPerPc;
    this.galaxyUniforms.uFocalPx.value = this.pxPerUnitAt(1) * this.renderer.getPixelRatio();
    this.galaxyUniforms.uFade.value = galaxyFade;
    this.galaxyGlowMaterial.opacity = galaxyFade * 0.3;
    this.galaxyFade = galaxyFade;
    this.systemFade = system;
    this.sunDistance = sunDistance;

    this.renderer.render(this.scene, cam);
  }

  dispose() {
    this._observer.disconnect();
    this.scene.traverse((o) => {
      o.geometry?.dispose?.();
      const m = o.material;
      if (m) {
        m.map?.dispose?.();
        m.dispose?.();
      }
    });
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }
}

function toThreeArray(ecl) {
  const out = new Float32Array(ecl.length);
  for (let i = 0; i < ecl.length; i += 3) {
    out[i] = ecl[i];
    out[i + 1] = ecl[i + 2];
    out[i + 2] = -ecl[i + 1];
  }
  return out;
}
