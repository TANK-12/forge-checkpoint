// Drawing the test range: sky, ground, course boxes, crates, walls, targets,
// sentries, props and the little effects (boost flames, slam ring, tracers,
// wall rubble). Reads the sim each frame; owns no game rules.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";
import { crateBox } from "./physics.js";

const PH = "/shared/assets/polyhaven";
const tex = new THREE.TextureLoader();

function texSet(id, kinds, repeat, srgbKind = "diff") {
  const out = {};
  for (const [slot, file] of Object.entries(kinds)) {
    const t = tex.load(`${PH}/${id}/1k/textures/${id}_${file}_1k.jpg`);
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(repeat[0], repeat[1]);
    t.anisotropy = 4;
    if (file === srgbKind || file === "col") t.colorSpace = THREE.SRGBColorSpace;
    out[slot] = t;
  }
  return out;
}

function labelTexture(lines, opts = {}) {
  const c = document.createElement("canvas");
  c.width = opts.w || 256;
  c.height = opts.h || 128;
  const g = c.getContext("2d");
  g.fillStyle = opts.bg || "#1b2228";
  g.fillRect(0, 0, c.width, c.height);
  if (opts.stripe) {
    g.fillStyle = opts.stripe;
    g.fillRect(0, 0, c.width, 14);
    g.fillRect(0, c.height - 14, c.width, 14);
  }
  g.fillStyle = opts.fg || "#e9f4fb";
  g.textAlign = "center";
  g.textBaseline = "middle";
  const size = opts.size || 48;
  lines.forEach((ln, i) => {
    g.font = `${i === 0 ? 700 : 500} ${i === 0 ? size : size * 0.55}px system-ui, sans-serif`;
    g.fillText(ln, c.width / 2, c.height / 2 + (i - (lines.length - 1) / 2) * size * 0.95);
  });
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function boxMesh(b, mat) {
  const sx = b.max[0] - b.min[0];
  const sy = b.max[1] - b.min[1];
  const sz = b.max[2] - b.min[2];
  const m = new THREE.Mesh(new THREE.BoxGeometry(sx, sy, sz), mat);
  m.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

// Box UVs in metres, so textures keep their real scale on any box size.
function worldUV(mesh, perM = 0.5) {
  const g = mesh.geometry;
  const p = g.attributes.position;
  const n = g.attributes.normal;
  const uv = g.attributes.uv;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i) + mesh.position.x;
    const y = p.getY(i) + mesh.position.y;
    const z = p.getZ(i) + mesh.position.z;
    const ax = Math.abs(n.getX(i));
    const ay = Math.abs(n.getY(i));
    if (ay > 0.5) uv.setXY(i, x * perM, z * perM);
    else if (ax > 0.5) uv.setXY(i, z * perM, y * perM);
    else uv.setXY(i, x * perM, y * perM);
  }
  uv.needsUpdate = true;
}

export class View {
  constructor(canvas, sim) {
    this.sim = sim;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x9fb2c2);
    this.scene.fog = new THREE.Fog(0xa9b8c4, 60, 160);
    this.camera = new THREE.PerspectiveCamera(65, 1, 0.05, 400);
    this.effects = [];
    this.loads = [];
    this.lights();
    this.sky();
    this.build();
    this.resize();
    window.addEventListener("resize", () => this.resize());
  }

  resize() {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  lights() {
    const hemi = new THREE.HemisphereLight(0xdfe9f2, 0x4a4438, 0.9);
    this.scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff1dc, 2.2);
    sun.position.set(18, 30, -12);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    const sc = sun.shadow.camera;
    sc.left = sc.bottom = -22;
    sc.right = sc.top = 22;
    sc.near = 1;
    sc.far = 90;
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.03;
    this.sun = sun;
    this.scene.add(sun, sun.target);
  }

  sky() {
    const url = `${PH}/overcast_soil_puresky/1k/overcast_soil_puresky_1k.hdr`;
    const p = new HDRLoader()
      .loadAsync(url)
      .then((hdr) => {
        hdr.mapping = THREE.EquirectangularReflectionMapping;
        this.scene.background = hdr;
        this.scene.backgroundIntensity = 0.9;
        const pm = new THREE.PMREMGenerator(this.renderer);
        this.scene.environment = pm.fromEquirectangular(hdr).texture;
        this.scene.environmentIntensity = 0.55;
        pm.dispose();
      })
      .catch(() => {});
    this.loads.push(p);
  }

  build() {
    const s = this.sim;
    const ground = texSet("rocks_ground_02", { map: "col", normalMap: "nor_gl", roughnessMap: "rough" }, [60, 60]);
    const gmat = new THREE.MeshStandardMaterial({ ...ground, color: 0xc9c2b5 });
    const g = new THREE.Mesh(new THREE.PlaneGeometry(160, 160), gmat);
    g.rotation.x = -Math.PI / 2;
    g.receiveShadow = true;
    this.scene.add(g);

    const conc = texSet("cracked_concrete_wall", { map: "diff", normalMap: "nor_gl", roughnessMap: "rough" }, [1, 1]);
    const courseMat = new THREE.MeshStandardMaterial({ ...conc, color: 0xd6d3cc });
    const accentMat = new THREE.MeshStandardMaterial({ color: 0xf0a020, roughness: 0.5 });
    const barrierMat = new THREE.MeshStandardMaterial({ ...conc, color: 0xb9b6ae });
    for (const b of s.statics) {
      if (b.kind === "ground") continue;
      const mat = b.kind === "bar" || b.kind === "post" ? accentMat : b.kind === "barrier" ? barrierMat : courseMat;
      const m = boxMesh(b, mat);
      if (mat.map) worldUV(m, 0.5);
      this.scene.add(m);
      if (b.label) this.sign([b.label], (b.min[0] + b.max[0]) / 2, b.max[1] + 0.45, b.min[2] - 0.02, 1.6, 0.4);
    }

    const brick = texSet("red_brick_03", { map: "diff", normalMap: "nor_gl", roughnessMap: "rough" }, [1, 1]);
    const wallMats = {
      plaster: new THREE.MeshStandardMaterial({ color: 0xe2dccd, roughness: 0.95 }),
      breeze: new THREE.MeshStandardMaterial({ ...brick, color: 0xb7aca2 }),
      concrete: new THREE.MeshStandardMaterial({ ...conc, color: 0x9a9893 }),
    };
    this.wallMeshes = s.walls.map((w) => {
      const m = boxMesh(w, wallMats[w.kind]);
      if (wallMats[w.kind].map) worldUV(m, 0.8);
      this.scene.add(m);
      this.sign([w.label], (w.min[0] + w.max[0]) / 2, w.max[1] + 0.4, w.min[2] - 0.02, 2.2, 0.45);
      return m;
    });
    this.wallMats = wallMats;

    const metal = texSet("blue_metal_plate", { map: "diff", normalMap: "nor_gl" }, [1, 1]);
    this.crateMeshes = s.crates.map((c) => {
      const side = new THREE.MeshStandardMaterial({
        map: labelTexture([`${c.kg} kg`], { bg: c.kg >= 100 ? "#3b4652" : "#6b5434", stripe: "#f0a020", size: 56 }),
        roughness: 0.7,
      });
      const top = new THREE.MeshStandardMaterial({ ...metal, color: c.kg >= 100 ? 0x8899aa : 0xb08d5c, metalness: 0.3 });
      const m = new THREE.Mesh(new THREE.BoxGeometry(c.hx * 2, c.hy * 2, c.hz * 2), [side, side, top, top, side, side]);
      m.castShadow = m.receiveShadow = true;
      this.scene.add(m);
      return m;
    });

    const ring = new THREE.MeshStandardMaterial({ map: this.targetTexture(), roughness: 0.6 });
    const post = new THREE.MeshStandardMaterial({ color: 0x3a3f44, roughness: 0.8 });
    this.targetMeshes = s.targets.map((t) => {
      const grp = new THREE.Group();
      const disc = new THREE.Mesh(new THREE.CylinderGeometry(0.4, 0.4, 0.05, 28), ring);
      disc.rotation.x = Math.PI / 2;
      disc.castShadow = true;
      const pivot = new THREE.Group();
      pivot.position.y = 0.0;
      disc.position.y = t.y;
      const stick = new THREE.Mesh(new THREE.BoxGeometry(0.06, t.y - 0.35, 0.06), post);
      stick.position.y = (t.y - 0.35) / 2;
      stick.castShadow = true;
      pivot.add(disc, stick);
      grp.add(pivot);
      grp.position.set(t.x, 0, t.z);
      grp.rotation.y = Math.atan2(-t.x, -t.z);
      this.scene.add(grp);
      return pivot;
    });

    const body = new THREE.MeshStandardMaterial({ color: 0x4a5058, roughness: 0.5, metalness: 0.6 });
    const eye = new THREE.MeshStandardMaterial({ color: 0xff3020, emissive: 0xff2010, emissiveIntensity: 2 });
    this.eyeOff = new THREE.MeshStandardMaterial({ color: 0x302020 });
    this.eyeOn = eye;
    this.sentryMeshes = s.sentries.map((sn) => {
      const base = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.5, 1.0, 12), body);
      base.position.set(sn.x, 0.5, sn.z);
      base.castShadow = true;
      const head = new THREE.Group();
      head.position.set(sn.x, 1.3, sn.z);
      const hm = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.4, 0.7), body);
      hm.castShadow = true;
      const gun = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, 0.7, 8), body);
      gun.rotation.x = Math.PI / 2;
      gun.position.z = 0.6;
      const e = new THREE.Mesh(new THREE.SphereGeometry(0.08, 10, 8), eye);
      e.position.set(0, 0.08, 0.36);
      head.add(hm, gun, e);
      head.userData.eye = e;
      this.scene.add(base, head);
      return head;
    });

    for (const sg of s.level.signs) this.sign([sg.text], sg.x, sg.y, sg.z, 2.4, 0.7, true);
    this.props(s.level.props);

    // Effects that get reused.
    const flame = new THREE.MeshBasicMaterial({ color: 0x8fe0ff, transparent: true, opacity: 0.8, depthWrite: false, blending: THREE.AdditiveBlending });
    this.flame = new THREE.Mesh(new THREE.ConeGeometry(0.14, 0.7, 12, 1, true), flame);
    this.flame.rotation.x = Math.PI;
    this.flame.visible = false;
    this.scene.add(this.flame);
    this.flameT = 0;
  }

  targetTexture() {
    const c = document.createElement("canvas");
    c.width = c.height = 128;
    const g = c.getContext("2d");
    const cols = ["#f2f2f2", "#d02a20", "#f2f2f2", "#d02a20", "#f2f2f2"];
    cols.forEach((col, i) => {
      g.fillStyle = col;
      g.beginPath();
      g.arc(64, 64, 64 - i * 12.5, 0, Math.PI * 2);
      g.fill();
    });
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
  }

  sign(lines, x, y, z, w, h, both = false) {
    const t = labelTexture(lines, { bg: "#14191e", fg: "#e9f4fb", stripe: "#5fd0ff", w: 512, h: Math.round((512 * h) / w), size: 64 });
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: t, side: both ? THREE.DoubleSide : THREE.FrontSide }));
    m.position.set(x, y, z);
    m.rotation.y = Math.PI;
    this.scene.add(m);
    return m;
  }

  props(list) {
    const byAsset = {};
    for (const p of list) (byAsset[p.asset] ||= []).push(p);
    const gl = new GLTFLoader();
    for (const [asset, items] of Object.entries(byAsset)) {
      const p = gl
        .loadAsync(`${PH}/${asset}/1k/${asset}_1k.gltf`)
        .then((g) => {
          for (const it of items) {
            const o = g.scene.clone();
            o.position.set(it.x, 0, it.z);
            o.rotation.y = it.rotY || 0;
            o.traverse((m) => {
              if (m.isMesh) m.castShadow = m.receiveShadow = true;
            });
            this.scene.add(o);
          }
        })
        .catch(() => {});
      this.loads.push(p);
    }
    // Road barriers along the range edge, one model, many copies.
    const p = gl
      .loadAsync(`${PH}/concrete_road_barrier/1k/concrete_road_barrier_1k.gltf`)
      .then((g) => {
        const bb = new THREE.Box3().setFromObject(g.scene);
        const len = Math.max(bb.max.x - bb.min.x, bb.max.z - bb.min.z);
        const alongX = bb.max.x - bb.min.x >= bb.max.z - bb.min.z;
        for (const side of [-32, 32]) {
          for (let z = -10; z < 54; z += len) {
            const o = g.scene.clone();
            o.position.set(side, 0, z + len / 2);
            o.rotation.y = alongX ? Math.PI / 2 : 0;
            this.scene.add(o);
          }
        }
        for (const zEdge of [-12.4, 54.4]) {
          for (let x = -32; x < 32; x += len) {
            const o = g.scene.clone();
            o.position.set(x + len / 2, 0, zEdge);
            o.rotation.y = alongX ? 0 : Math.PI / 2;
            this.scene.add(o);
          }
        }
      })
      .catch(() => {});
    this.loads.push(p);
  }

  add(obj) {
    this.scene.add(obj);
  }

  // One-off effects from the sim's events.
  onEvent(e) {
    if (e.type === "boost") this.flameT = e.kind === "slam" ? 0.6 : 0.35;
    if (e.type === "slam") this.slamRing(e);
    if (e.type === "shot") this.tracer(e.from, e.to);
    if (e.type === "wall") this.rubble(this.sim.walls[e.id]);
  }

  slamRing(e) {
    const m = new THREE.Mesh(
      new THREE.RingGeometry(0.2, 0.45, 40),
      new THREE.MeshBasicMaterial({ color: 0x8fe0ff, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }),
    );
    m.rotation.x = -Math.PI / 2;
    m.position.set(e.x, e.y + 0.05, e.z);
    this.scene.add(m);
    this.effects.push({ m, t: 0, life: 0.6, grow: e.r });
  }

  tracer(a, b) {
    const g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(...a), new THREE.Vector3(...b)]);
    const m = new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xff4030, transparent: true, opacity: 1 }));
    this.scene.add(m);
    this.effects.push({ m, t: 0, life: 0.1 });
  }

  rubble(w) {
    const mat = this.wallMats[w.kind];
    const cx = (w.min[0] + w.max[0]) / 2;
    const cz = (w.min[2] + w.max[2]) / 2;
    for (let i = 0; i < 14; i++) {
      const s = 0.15 + Math.random() * 0.25;
      const m = new THREE.Mesh(new THREE.BoxGeometry(s, s, s), mat);
      m.position.set(cx + (Math.random() - 0.5) * (w.max[0] - w.min[0]), w.min[1] + Math.random() * (w.max[1] - w.min[1]), cz);
      m.castShadow = true;
      this.scene.add(m);
      const v = new THREE.Vector3((Math.random() - 0.5) * 3, 1 + Math.random() * 3, (Math.random() - 0.3) * 4);
      this.effects.push({ m, t: 0, life: 2.5, v, spin: Math.random() * 6 });
    }
  }

  update(dt, player) {
    const s = this.sim;
    s.walls.forEach((w, i) => (this.wallMeshes[i].visible = w.intact));
    s.crates.forEach((c, i) => {
      const m = this.crateMeshes[i];
      const b = crateBox(c);
      m.position.set((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
      m.rotation.y = c.held ? player.yaw : 0;
    });
    s.targets.forEach((t, i) => {
      const piv = this.targetMeshes[i];
      const want = t.down ? -Math.PI / 2 : 0;
      piv.rotation.x += (want - piv.rotation.x) * Math.min(1, dt * 10);
    });
    s.sentries.forEach((sn, i) => {
      const h = this.sentryMeshes[i];
      h.rotation.y = sn.yaw;
      h.userData.eye.material = sn.offT > 0 ? this.eyeOff : this.eyeOn;
    });
    // Boost flame under the feet.
    this.flameT -= dt;
    this.flame.visible = this.flameT > 0 || player.slamming;
    if (this.flame.visible) {
      this.flame.position.set(player.x, player.y - 0.2 + (player.slamming ? 1.8 : 0), player.z);
      this.flame.rotation.x = player.slamming ? 0 : Math.PI;
      this.flame.scale.setScalar(0.8 + Math.random() * 0.4);
    }
    for (const fx of this.effects) {
      fx.t += dt;
      const k = fx.t / fx.life;
      if (fx.grow) {
        const r = 0.3 + k * fx.grow * 2.2;
        fx.m.scale.set(r, r, r);
        fx.m.material.opacity = 0.9 * (1 - k);
      } else if (fx.v) {
        fx.v.y -= 9.81 * dt;
        fx.m.position.addScaledVector(fx.v, dt);
        if (fx.m.position.y < 0.1) {
          fx.m.position.y = 0.1;
          fx.v.multiplyScalar(0.5);
          fx.v.y = Math.abs(fx.v.y) * 0.3;
        }
        fx.m.rotation.x += fx.spin * dt;
      } else {
        fx.m.material.opacity = 1 - k;
      }
      if (fx.t >= fx.life) {
        this.scene.remove(fx.m);
        fx.m.geometry.dispose();
        if (!fx.v) fx.m.material.dispose();
      }
    }
    this.effects = this.effects.filter((fx) => fx.t < fx.life);
    // Keep the sun's shadow box on the player.
    this.sun.position.set(player.x + 18, 30, player.z - 12);
    this.sun.target.position.set(player.x, 0, player.z);
  }

  render() {
    this.renderer.render(this.scene, this.camera);
  }
}
