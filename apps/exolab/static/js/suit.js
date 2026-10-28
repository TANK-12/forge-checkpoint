// The person and the suit: a VRM character from the Forge character
// pipeline, the fitted suit GLB (Blender, task 104) attached bone by bone as
// its sidecar says, and the dress faces the suit replaces hidden by the
// sidecar's hide rule. The game's character.js does the same for its
// soldier plus animation clips, which the bench does not need.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "three-vrm";

const ARM_BONES = ["leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm", "leftHand", "rightHand"];

const vrmLoader = new GLTFLoader();
vrmLoader.register((parser) => new VRMLoaderPlugin(parser));

/** The VRM, turned to face +Z like the body frame the core uses. */
export async function loadPerson(url) {
  const gltf = await vrmLoader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error("not a VRM file");
  const vrm0 = vrm.meta?.metaVersion === "0";
  if (vrm0) VRMUtils.rotateVRM0(vrm);
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  vrm.scene.traverse((o) => {
    if (o.isMesh) o.frustumCulled = false;
  });
  vrm.scene.updateMatrixWorld(true);
  return { vrm, vrm0 };
}

export function disposePerson(person) {
  if (person?.vrm) VRMUtils.deepDispose(person.vrm.scene);
}

/** Attach every suit node to its humanoid bone while the VRM is at rest.
 *  Returns name -> node, so the page can tint a part by its load. */
export async function attachSuit(vrm, glbUrl, sidecar) {
  const gltf = await new GLTFLoader().loadAsync(glbUrl);
  const suit = gltf.scene;
  suit.updateMatrixWorld(true);
  let found = [];
  suit.traverse((o) => {
    if (o !== suit && o.userData?.bone) found.push([o, o.userData.bone]);
  });
  if (!found.length) {
    // The extras did not survive the export: use the sidecar's part list.
    found = (sidecar?.parts || [])
      .map((p) => [suit.getObjectByName(p.name), p.bone])
      .filter(([o]) => o);
  }
  const parts = new Map();
  for (const [o, boneName] of found) {
    const bone = vrm.humanoid.getRawBoneNode(boneName);
    if (!bone) continue;
    bone.attach(o);
    parts.set(o.name, o);
    o.traverse((m) => {
      if (!m.isMesh) return;
      m.frustumCulled = false;
      m.userData.suit = true;
    });
  }
  if ((sidecar?.parts || []).some((p) => p.part === "helmet")) {
    vrm.scene.traverse((o) => {
      if (o.isMesh && /hair/i.test(o.name)) o.visible = false;
    });
  }
  return parts;
}

/** Hide the dress faces the suit replaces: the sidecar's hide rule (skirt
 *  and sleeve joints, arm bones and hips by dominant skin joint, and faces
 *  mostly weighted to the arms). Returns how many faces went. */
export function hideDress(vrm, rule) {
  if (!rule) return 0;
  const node = (n) => vrm.humanoid.getRawBoneNode(n) || vrm.scene.getObjectByName(n);
  const arm = new Set((rule.arm_bones || ARM_BONES).map(node).filter(Boolean));
  // Bones whose faces sit under a torso shell on this suit (the bodice).
  const extra = new Set((rule.extra_dominant || []).map(node).filter(Boolean));
  const hips = vrm.humanoid.getRawBoneNode("hips");
  const want = rule.material;
  const armLimit = typeof rule.arm_weight_min === "number" ? rule.arm_weight_min : 0.3;
  let hidden = 0;
  vrm.scene.traverse((o) => {
    if (!o.isSkinnedMesh) return;
    const mats = [o.material].flat();
    if (!mats.some((m) => m && m.name && m.name.startsWith(want))) return;
    const g = o.geometry;
    const idx = g.index;
    const si = g.attributes.skinIndex;
    const sw = g.attributes.skinWeight;
    if (!idx || !si || !sw) return;
    const bones = o.skeleton.bones;
    const isArm = bones.map((b) => arm.has(b));
    const keep = [];
    const sum = new Map();
    for (let f = 0; f + 2 < idx.count; f += 3) {
      sum.clear();
      let armW = 0;
      for (let k = 0; k < 3; k++) {
        const v = idx.getX(f + k);
        for (let j = 0; j < 4; j++) {
          const w = sw.getComponent(v, j);
          if (w <= 0) continue;
          const b = si.getComponent(v, j);
          sum.set(b, (sum.get(b) || 0) + w);
          if (isArm[b]) armW += w;
        }
      }
      let best = -1;
      let bw = -1;
      for (const [b, w] of sum) {
        if (w > bw) {
          best = b;
          bw = w;
        }
      }
      const bone = bones[best];
      const name = bone ? bone.name : "";
      const hide =
        /Skirt/.test(name) ||
        /Sleeve/.test(name) ||
        arm.has(bone) ||
        extra.has(bone) ||
        bone === hips ||
        armW / 3 >= armLimit;
      if (hide) hidden += 1;
      else keep.push(idx.getX(f), idx.getX(f + 1), idx.getX(f + 2));
    }
    g.setIndex(keep);
    for (const grp of g.groups) {
      grp.start = 0;
      grp.count = keep.length;
    }
  });
  return hidden;
}

const DARK = [0.09, 0.1, 0.12];
const DARK_SHADE = [0.04, 0.045, 0.05];

const isSkin = (m) => m && /Body/.test(m.name) && /SKIN/i.test(m.name);

function darken(m) {
  if (m.color) m.color.setRGB(...DARK);
  if (m.shadeColorFactor) m.shadeColorFactor.setRGB(...DARK_SHADE);
}

/** Dress the body skin as the sidecar's skin field says: undersuit true
 *  tints all skin below the face black (the full suit); a cover moves the
 *  skin faces in a height band round the cover bone into dark shorts (the
 *  light suit), so arms and legs stay bare. Runs once per body (a second
 *  call gives the first answer); a cover it cannot make is named on the
 *  console. Returns true when the skin went under an undersuit. */
export function tintUndersuit(vrm, sidecar) {
  const done = vrm.scene.userData.exolabSkin;
  if (done) return done.undersuit;
  const skin = sidecar?.skin || {};
  const undersuit = skin.undersuit === true;
  vrm.scene.userData.exolabSkin = { undersuit };
  if (undersuit) {
    vrm.scene.traverse((o) => {
      if (o.isMesh) for (const m of [o.material].flat()) if (isSkin(m)) darken(m);
    });
  } else if (skin.cover) {
    vrm.scene.userData.exolabSkin.shorts = coverSkin(vrm, skin.cover);
  }
  if (skin.closed_helmet === true) vrm.scene.userData.exolabSkin.helmet = closeHelmet(vrm);
  return undersuit;
}

// The character's own head: face, eyes, brows, mouth and hair (VRoid names).
const HEAD_MAT = /_(FACE|EYE|HAIR)(_|\b)|Face_\d+_SKIN/i;

/** The pilot in a closed helmet: hides the character's face and hair and
 *  fits a carbon helmet with a cyan visor round where the face was, on the
 *  head bone. The helmet's size comes from the face's own bounds at rest.
 *  Returns how many head meshes it hid (0 and a console warning when the
 *  body has no head bone). */
function closeHelmet(vrm) {
  const head = vrm.humanoid.getRawBoneNode("head");
  if (!head) {
    console.warn("exolab: no closed helmet: the body has no head bone");
    return 0;
  }
  const face = new THREE.Box3();
  const hidden = [];
  vrm.scene.updateMatrixWorld(true);
  vrm.scene.traverse((o) => {
    if (!o.isMesh || !o.visible || ![o.material].flat().some((m) => HEAD_MAT.test(m?.name || ""))) return;
    hidden.push(o);
    if (![o.material].flat().some((m) => /HAIR/i.test(m?.name || ""))) face.expandByObject(o);
  });
  for (const o of hidden) o.visible = false;
  const at = new THREE.Vector3();
  const size = new THREE.Vector3(0.16, 0.2, 0.16);
  if (face.isEmpty()) head.getWorldPosition(at).add(new THREE.Vector3(0, 0.09, 0));
  else face.getCenter(at), face.getSize(size);
  // A skull runs further back than the face: the shell sits a little behind
  // and above the face's centre, a touch wider than it.
  const r = new THREE.Vector3(size.x * 0.62 + 0.01, size.y * 0.6 + 0.01, Math.max(size.z * 0.8, size.x * 0.62) + 0.01);
  at.add(new THREE.Vector3(0, size.y * 0.06, -r.z * 0.25));
  const helmet = new THREE.Group();
  helmet.name = "exolab_helmet";
  const shell = new THREE.Mesh(
    new THREE.SphereGeometry(1, 40, 24),
    new THREE.MeshStandardMaterial({ color: 0x15181d, metalness: 0.45, roughness: 0.42 }),
  );
  shell.scale.copy(r);
  // The visor: a band across the front at eye height, just proud of the shell.
  const visor = new THREE.Mesh(
    new THREE.SphereGeometry(1, 40, 8, Math.PI / 2 - 0.95, 1.9, 1.3, 0.34),
    new THREE.MeshStandardMaterial({ color: 0x0b2630, emissive: 0x2aa9c9, emissiveIntensity: 0.7, metalness: 0.2, roughness: 0.15 }),
  );
  visor.scale.copy(r).multiplyScalar(1.03);
  helmet.add(shell, visor);
  helmet.position.copy(at);
  vrm.scene.add(helmet);
  helmet.updateMatrixWorld(true);
  head.attach(helmet);
  return hidden.length;
}

const COVER_MAX_M = 3; // a band edge further than this from the bone was typed in mm

/** Split the cover band off each skin mesh into a dark twin that shares
 *  its vertices and skeleton: the faces whose centre at rest lies from
 *  from_m to to_m metres above the cover bone (below when negative), so the
 *  hem runs straight round each thigh. Returns how many skin faces moved
 *  (each once, though an outline material draws it twice); the console
 *  names a cover it refuses, one that moves nothing and one that takes
 *  more than half the skin. */
function coverSkin(vrm, cover) {
  const bone = vrm.humanoid.getRawBoneNode(cover.bone || "hips");
  const lo = cover.from_m;
  const hi = cover.to_m;
  const metres = (x) => typeof x === "number" && Number.isFinite(x) && Math.abs(x) <= COVER_MAX_M;
  if (!bone || !metres(lo) || !metres(hi) || lo >= hi) {
    console.warn(`exolab: no shorts: the cover needs a body bone and from_m below to_m, numbers in metres within ${COVER_MAX_M} m of the bone`, cover);
    return 0;
  }
  const meshes = [];
  vrm.scene.traverse((o) => {
    if (o.isSkinnedMesh && [o.material].flat().some(isSkin)) meshes.push(o);
  });
  const at = new THREE.Vector3();
  const p = new THREE.Vector3();
  let moved = 0;
  let skin = 0;
  let cut = 0; // meshes the band was tried on
  for (const o of meshes) {
    const g = o.geometry;
    const idx = g.index;
    const pos = g.attributes.position;
    // Heights in the bind pose: the bone where its inverse bind matrix
    // puts it, each vertex through the mesh's bind matrix.
    const bi = o.skeleton.bones.indexOf(bone);
    if (!idx || !pos || bi < 0) {
      console.warn(`exolab: no shorts on ${o.name}: ${bi < 0 ? `${bone.name} is not in its skeleton` : "the mesh has no face list"}`);
      continue;
    }
    cut += 1;
    at.setFromMatrixPosition(o.skeleton.boneInverses[bi].clone().invert());
    const y0 = at.y + lo;
    const y1 = at.y + hi;
    const yOf = (v) => p.fromBufferAttribute(pos, v).applyMatrix4(o.bindMatrix).y;
    // Only skin faces move: a mesh with several materials keeps the others,
    // and each material's faces stay one group in both meshes.
    const mats = [o.material].flat();
    const groups = g.groups.length ? g.groups : [{ start: 0, count: idx.count, materialIndex: 0 }];
    const keep = [];
    const shorts = [];
    const keepGroups = [];
    const shortGroups = [];
    const skinFaces = new Set();
    const shortFaces = new Set();
    for (const grp of groups) {
      const [k0, s0] = [keep.length, shorts.length];
      const split = isSkin(Array.isArray(o.material) ? mats[grp.materialIndex] : o.material);
      const end = Math.min(grp.start + grp.count, idx.count);
      for (let f = grp.start; f + 2 < end; f += 3) {
        const a = idx.getX(f);
        const b = idx.getX(f + 1);
        const c = idx.getX(f + 2);
        const y = split ? (yOf(a) + yOf(b) + yOf(c)) / 3 : NaN;
        const inBand = y >= y0 && y <= y1;
        (inBand ? shorts : keep).push(a, b, c);
        if (split) skinFaces.add(`${a},${b},${c}`);
        if (inBand) shortFaces.add(`${a},${b},${c}`);
      }
      keepGroups.push([k0, keep.length - k0, grp.materialIndex]);
      shortGroups.push([s0, shorts.length - s0, grp.materialIndex]);
    }
    skin += skinFaces.size;
    if (!shorts.length) continue;
    const twin = new THREE.BufferGeometry();
    for (const [name, attr] of Object.entries(g.attributes)) twin.setAttribute(name, attr);
    twin.morphAttributes = g.morphAttributes;
    twin.morphTargetsRelative = g.morphTargetsRelative;
    twin.setIndex(shorts);
    g.setIndex(keep);
    if (g.groups.length) {
      g.clearGroups();
      for (const [st, n, mi] of keepGroups) if (n) g.addGroup(st, n, mi);
      for (const [st, n, mi] of shortGroups) if (n) twin.addGroup(st, n, mi);
    }
    const dark = mats.map((m) => {
      const c = m.clone();
      darken(c);
      return c;
    });
    const sm = new THREE.SkinnedMesh(twin, Array.isArray(o.material) ? dark : dark[0]);
    sm.name = `${o.name}_shorts`;
    sm.position.copy(o.position);
    sm.quaternion.copy(o.quaternion);
    sm.scale.copy(o.scale);
    sm.bindMode = o.bindMode;
    sm.bind(o.skeleton, o.bindMatrix.clone());
    sm.morphTargetInfluences = o.morphTargetInfluences;
    sm.morphTargetDictionary = o.morphTargetDictionary;
    sm.frustumCulled = o.frustumCulled;
    sm.castShadow = o.castShadow;
    sm.receiveShadow = o.receiveShadow;
    sm.renderOrder = o.renderOrder;
    o.parent.add(sm);
    moved += shortFaces.size;
  }
  if (!meshes.length) {
    console.warn("exolab: no shorts: the body has no skinned skin mesh", cover);
  } else if (!moved && cut) {
    console.warn(`exolab: no shorts: no skin face lies from ${lo} to ${hi} m about ${bone.name}`, cover);
  } else if (moved > skin / 2) {
    console.warn(`exolab: the shorts take ${moved} of ${skin} skin faces, more than half: is the band from_m ${lo} to to_m ${hi} right?`, cover);
  }
  return moved;
}

export { THREE };
