// PrintForge 3D view: one STL on a print bed, with orbit, pan and zoom.
// STL files are Z-up in millimetres; three.js is Y-up, so the mesh is turned
// once on load. Model "front" is +Y in the STL (the Juggernaut faces +Y).
import * as THREE from "three";

const VIEWS = {
  // directions in STL axes (x right, y front, z up)
  iso: [1, 1, 0.8],
  front: [0, 1, 0.05],
  back: [0, -1, 0.05],
  left: [-1, 0, 0.05],
  right: [1, 0, 0.05],
  top: [0, 0.001, 1],
  below: [1, 1, -0.8], // 3/4 from underneath, where the overhangs face
};

// Overhang tint: faces pointing down steeper than the support angle (from
// vertical) turn red, except faces resting on the bed. Done in the shader from
// the face normals the mesh already has, so it costs no memory per model.
// The material draws both sides, and the side the camera sees of a closed
// mesh always faces out: the stored normal times the facing (gl_FrontFacing)
// is the outward one whichever way the triangles wind, so an inside-out
// print is drawn and tinted like a normal one.
const OVERHANG_RED = "vec3(0.9, 0.3, 0.24)";
const OVERHANG_GLOW = "vec3(0.3, 0.05, 0.03)";
const BED_MM = 0.2;

function addOverhangTint(material, uniforms) {
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader =
      "varying float vPfY;\nvarying float vPfNy;\n" +
      shader.vertexShader.replace(
        "#include <begin_vertex>",
        "#include <begin_vertex>\nvPfY = position.y;\nvPfNy = normal.y;",
      );
    shader.fragmentShader =
      "uniform float uPfOn;\nuniform float uPfSin;\nvarying float vPfY;\nvarying float vPfNy;\n" +
      shader.fragmentShader
        .replace(
          "#include <color_fragment>",
          `#include <color_fragment>
float pfOh = (uPfOn > 0.5 && vPfNy * (gl_FrontFacing ? 1.0 : -1.0) < -uPfSin && vPfY > ${BED_MM.toFixed(2)}) ? 1.0 : 0.0;
diffuseColor.rgb = mix(diffuseColor.rgb, ${OVERHANG_RED}, pfOh);`,
        )
        // a little glow of its own, so the red reads even in the shade underneath
        .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>\ntotalEmissiveRadiance += ${OVERHANG_GLOW} * pfOh;`);
  };
}

function rafLoop(step) {
  const frame = (t) => step(t) !== false && requestAnimationFrame(frame);
  requestAnimationFrame(frame);
  return {};
}

export function parseSTL(buffer) {
  const dv = new DataView(buffer);
  if (buffer.byteLength >= 84) {
    const n = dv.getUint32(80, true);
    if (84 + n * 50 === buffer.byteLength) {
      const pos = new Float32Array(n * 9);
      for (let i = 0; i < n; i++) {
        const o = 84 + i * 50 + 12;
        for (let k = 0; k < 9; k++) pos[i * 9 + k] = dv.getFloat32(o + k * 4, true);
      }
      return pos;
    }
  }
  const text = new TextDecoder().decode(buffer);
  const nums = [];
  const re = /vertex\s+(\S+)\s+(\S+)\s+(\S+)/g;
  let m;
  while ((m = re.exec(text))) nums.push(+m[1], +m[2], +m[3]);
  return new Float32Array(nums);
}

export class Viewer {
  constructor(host) {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    host.appendChild(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.5, 20000);
    this.scene.add(this.camera);
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x2a2a33, 1.1);
    this.scene.add(this.hemi);
    this.key = new THREE.DirectionalLight(0xffffff, 2.0);
    this.key.position.set(0.6, 0.8, 0.4); // follows the camera, like a head lamp
    this.camera.add(this.key);
    this.rim = new THREE.DirectionalLight(0xbfd4ff, 0.8);
    this.rim.position.set(-1, 1.5, -1.5);
    this.scene.add(this.rim);
    // both sides, so an inside-out print shows its outside (three.js lights a
    // back face with its normal turned round), not the far walls from within
    this.material = new THREE.MeshStandardMaterial({ color: 0xc9c3b5, roughness: 0.55, metalness: 0.05, side: THREE.DoubleSide });
    this.overhang = { uPfOn: { value: 0 }, uPfSin: { value: Math.sin(Math.PI / 4) } };
    addOverhangTint(this.material, this.overhang);
    this.mesh = null;
    this.bedSize = [256, 256, 256];
    this.bedOn = true;
    this.bed = new THREE.Group();
    this.scene.add(this.bed);
    this.target = new THREE.Vector3();
    this.theta = 0.8;
    this.phi = 1.1;
    this.radius = 400;
    this.autoRotate = false;
    this.lightScale = 1;
    this.modelSize = [0, 0, 0];
    this._bindControls();
    new ResizeObserver(() => this._resize()).observe(host);
    this._resize();
    this._frames = null;
    this.setBed(this.bedSize, true);
  }

  // Draws only when something changed, and keeps drawing only while the
  // turntable runs. ForgeIdle.loop pauses while the page cannot be seen.
  _mark() {
    this._dirty = true;
    if (this._frames) return;
    let last = 0;
    const step = (t) => {
      if (this.autoRotate) {
        this.theta += (last ? Math.min(t - last, 100) : 16) * 0.00024;
        this._dirty = true;
      }
      last = t;
      if (this._dirty) this._render();
      if (this.autoRotate) return true;
      this._frames = null;
      return false;
    };
    this._frames = window.ForgeIdle ? window.ForgeIdle.loop(step) : rafLoop(step);
  }

  _resize() {
    const w = this.host.clientWidth || 1;
    const h = this.host.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this._mark();
  }

  _render() {
    const s = Math.sin(this.phi);
    this.camera.position.set(
      this.target.x + this.radius * s * Math.sin(this.theta),
      this.target.y + this.radius * Math.cos(this.phi),
      this.target.z + this.radius * s * Math.cos(this.theta),
    );
    this.camera.lookAt(this.target);
    this.renderer.render(this.scene, this.camera);
    this._dirty = false;
  }

  _bindControls() {
    const el = this.renderer.domElement;
    let drag = null;
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("pointerdown", (e) => {
      drag = { x: e.clientX, y: e.clientY, pan: e.button === 2 || e.shiftKey };
      el.setPointerCapture(e.pointerId);
    });
    el.addEventListener("pointermove", (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      const dy = e.clientY - drag.y;
      drag.x = e.clientX;
      drag.y = e.clientY;
      if (drag.pan) {
        const k = this.radius * 0.0016;
        const right = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 0);
        const up = new THREE.Vector3().setFromMatrixColumn(this.camera.matrixWorld, 1);
        this.target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
      } else {
        this.theta -= dx * 0.008;
        this.phi = Math.min(Math.max(this.phi - dy * 0.008, 0.05), Math.PI - 0.05);
      }
      this._mark();
      el.dispatchEvent(new CustomEvent("orbit", { bubbles: true }));
    });
    el.addEventListener("pointerup", () => (drag = null));
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      this.radius = Math.min(Math.max(this.radius * Math.exp(e.deltaY * 0.0012), 5), 15000);
      this._mark();
    }, { passive: false });
    el.addEventListener("dblclick", () => this.fit());
  }

  setMesh(positions) {
    if (this.mesh) {
      this.scene.remove(this.mesh);
      this.mesh.geometry.dispose();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    g.rotateX(-Math.PI / 2);
    g.computeBoundingBox();
    const b = g.boundingBox;
    g.translate(-(b.min.x + b.max.x) / 2, -b.min.y, -(b.min.z + b.max.z) / 2);
    g.computeVertexNormals();
    g.computeBoundingBox();
    const s = g.boundingBox.getSize(new THREE.Vector3());
    this.modelSize = [s.x, s.z, s.y]; // back to STL x, y, z
    this.mesh = new THREE.Mesh(g, this.material);
    this.scene.add(this.mesh);
    this.setBed(this.bedSize, this.bedOn);
    this.fit();
    return this.modelSize;
  }

  // Takes the model off the bed (a file that failed to load must not leave
  // the previous print on show under its name).
  clear() {
    if (!this.mesh) return;
    this.scene.remove(this.mesh);
    this.mesh.geometry.dispose();
    this.mesh = null;
    this.modelSize = [0, 0, 0];
    this.setBed(this.bedSize, this.bedOn);
  }

  // Red faces where the print needs support: `angle` in degrees from
  // vertical (inside-out meshes need nothing extra, see addOverhangTint).
  setOverhang(on, angle = 45) {
    this.overhang.uPfOn.value = on ? 1 : 0;
    this.overhang.uPfSin.value = Math.sin((angle * Math.PI) / 180);
    this._mark();
  }

  fits() {
    const [x, y, z] = this.modelSize;
    const [bx, by, bz] = this.bedSize;
    return Math.min(x, y) <= Math.min(bx, by) && Math.max(x, y) <= Math.max(bx, by) && z <= bz;
  }

  setBed(size, on) {
    this.bedSize = size.map(Number);
    this.bedOn = on;
    for (const part of [...this.bed.children]) {
      part.geometry.dispose();
      part.material.dispose();
    }
    this.bed.clear();
    if (!on) {
      this._mark();
      return;
    }
    let [bx, by] = this.bedSize;
    const [mx, my] = this.modelSize;
    // turn the bed to match the model's long side, as a slicer would
    if ((mx > my) !== (bx > by)) [bx, by] = [by, bx];
    const ok = !this.mesh || this.fits();
    const plate = new THREE.Mesh(
      new THREE.PlaneGeometry(bx, by),
      new THREE.MeshStandardMaterial({ color: 0x1c1f26, roughness: 0.9, transparent: true, opacity: 0.85 }),
    );
    plate.rotation.x = -Math.PI / 2;
    plate.position.y = -0.05;
    this.bed.add(plate);
    const lines = [];
    for (let x = -bx / 2; x <= bx / 2 + 0.01; x += 10) lines.push(x, 0, -by / 2, x, 0, by / 2);
    for (let z = -by / 2; z <= by / 2 + 0.01; z += 10) lines.push(-bx / 2, 0, z, bx / 2, 0, z);
    const grid = new THREE.BufferGeometry();
    grid.setAttribute("position", new THREE.Float32BufferAttribute(lines, 3));
    this.bed.add(new THREE.LineSegments(grid, new THREE.LineBasicMaterial({ color: 0x3a4050 })));
    const edge = new THREE.EdgesGeometry(new THREE.BoxGeometry(bx, this.bedSize[2], by));
    const box = new THREE.LineSegments(edge, new THREE.LineBasicMaterial({ color: ok ? 0x5fb070 : 0xe05a4a, transparent: true, opacity: 0.55 }));
    box.position.y = this.bedSize[2] / 2;
    this.bed.add(box);
    this._mark();
  }

  fit() {
    if (!this.mesh) return;
    const bs = this.mesh.geometry.boundingBox;
    const c = bs.getCenter(new THREE.Vector3());
    const r = bs.getSize(new THREE.Vector3()).length() / 2;
    this.target.copy(c);
    this.radius = (r / Math.sin((this.camera.fov * Math.PI) / 360)) * 1.18; // room for the toolbar
    this._mark();
  }

  setView(name) {
    const [x, y, z] = VIEWS[name] || VIEWS.iso;
    const d = new THREE.Vector3(x, z, -y).normalize(); // STL -> three axes
    this.theta = Math.atan2(d.x, d.z);
    this.phi = Math.acos(d.y);
    this.fit();
  }

  setWireframe(on) {
    this.material.wireframe = on;
    this._mark();
  }

  setColor(hex) {
    this.material.color.set(hex);
    this._mark();
  }

  setLight(v) {
    this.lightScale = v;
    this.key.intensity = 2.0 * v;
    this.hemi.intensity = 1.1 * v;
    this.rim.intensity = 0.8 * v;
    this._mark();
  }

  setAutoRotate(on) {
    this.autoRotate = on;
    if (on) this._mark();
  }

  snapshot() {
    this._render();
    return this.renderer.domElement.toDataURL("image/png");
  }
}
