// 3D and sky previews with the vendored three.js. Each show* call returns a
// stop function; the page calls it before showing the next item so only one
// WebGL context and render loop is ever alive.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { HDRLoader } from "three/addons/loaders/HDRLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

function stage(box) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const w = box.clientWidth || 320;
  const h = box.clientHeight || 320;
  renderer.setSize(w, h);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  box.replaceChildren(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 2000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  let alive = true;
  const loop = () => {
    if (!alive) return;
    controls.update();
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  };
  const stop = () => {
    alive = false;
    controls.dispose();
    scene.traverse((o) => {
      if (o.geometry) o.geometry.dispose();
      const mats = o.material ? [].concat(o.material) : [];
      mats.forEach((m) => {
        Object.values(m).forEach((v) => v && v.isTexture && v.dispose());
        m.dispose();
      });
    });
    if (scene.background && scene.background.isTexture) scene.background.dispose();
    if (scene.environment) scene.environment.dispose();
    renderer.dispose();
    renderer.forceContextLoss();
  };
  return { renderer, scene, camera, controls, loop, stop };
}

function failed(box, err) {
  box.dataset.state = "error";
  const p = document.createElement("p");
  p.className = "none";
  p.textContent = `Could not show it: ${err && err.message ? err.message : err}`;
  box.replaceChildren(p);
}

export function showModel(box, url) {
  box.dataset.state = "loading";
  const s = stage(box);
  const pmrem = new THREE.PMREMGenerator(s.renderer);
  s.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  pmrem.dispose();
  s.scene.background = new THREE.Color(0x14161f);
  new GLTFLoader().load(
    url,
    (gltf) => {
      const root = gltf.scene;
      s.scene.add(root);
      const bounds = new THREE.Box3().setFromObject(root);
      const size = bounds.getSize(new THREE.Vector3()).length() || 1;
      const centre = bounds.getCenter(new THREE.Vector3());
      s.controls.target.copy(centre);
      s.camera.position.copy(centre).add(new THREE.Vector3(0.6, 0.4, 0.8).multiplyScalar(size));
      s.camera.near = size / 100;
      s.camera.far = size * 100;
      s.camera.updateProjectionMatrix();
      let meshes = 0;
      root.traverse((o) => { if (o.isMesh) meshes += 1; });
      box.dataset.meshes = String(meshes);
      box.dataset.state = "ready";
      s.loop();
    },
    undefined,
    (err) => failed(box, err),
  );
  return s.stop;
}

export function showSky(box, url) {
  box.dataset.state = "loading";
  const s = stage(box);
  s.camera.position.set(0, 0, 0.1);
  s.controls.enableZoom = false;
  s.controls.rotateSpeed = -0.3;
  new HDRLoader().load(
    url,
    (tex) => {
      tex.mapping = THREE.EquirectangularReflectionMapping;
      s.scene.background = tex;
      box.dataset.state = "ready";
      s.loop();
    },
    undefined,
    (err) => failed(box, err),
  );
  return s.stop;
}
