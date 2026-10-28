// The exo soldier: the VRM character, the fitted suit from task 104 attached
// bone by bone, the dress faces the suit replaces hidden, and the Quaternius
// Universal Animation Library retargeted onto the VRM normalised bones.
// Procedural overlays (carry, slam, slide lean, broken arms, fists) sit on
// top of the clips.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "three-vrm";
import { tintUndersuit } from "../js/suit.js";

const ANIM_URL = "/shared/assets/animations/universal_animation_library/AnimationLibrary_Godot_Standard.gltf";

// Quaternius (Rigify DEF bones, T-pose rest, facing +Z) to VRM humanoid.
const SRC_TO_VRM = {
  "DEF-hips": "hips",
  "DEF-spine.001": "spine",
  "DEF-spine.002": "chest",
  "DEF-spine.003": "upperChest",
  "DEF-neck": "neck",
  "DEF-head": "head",
  "DEF-shoulder.L": "leftShoulder",
  "DEF-upper_arm.L": "leftUpperArm",
  "DEF-forearm.L": "leftLowerArm",
  "DEF-hand.L": "leftHand",
  "DEF-shoulder.R": "rightShoulder",
  "DEF-upper_arm.R": "rightUpperArm",
  "DEF-forearm.R": "rightLowerArm",
  "DEF-hand.R": "rightHand",
  "DEF-thigh.L": "leftUpperLeg",
  "DEF-shin.L": "leftLowerLeg",
  "DEF-foot.L": "leftFoot",
  "DEF-toe.L": "leftToes",
  "DEF-thigh.R": "rightUpperLeg",
  "DEF-shin.R": "rightLowerLeg",
  "DEF-foot.R": "rightFoot",
  "DEF-toe.R": "rightToes",
};

// Game state to clip, and the speed (m/s) each loop was authored at, so the
// feet keep up with the derived speeds.
const CLIPS = {
  idle: { name: "Idle_Loop" },
  walk: { name: "Walk_Loop", mps: 1.4 },
  run: { name: "Jog_Fwd_Loop", mps: 3.4 },
  sprint: { name: "Sprint_Loop", mps: 6.0 },
  jump: { name: "Jump_Start", once: true },
  air: { name: "Jump_Loop" },
  land: { name: "Jump_Land", once: true },
  slide: { name: "Crouch_Idle_Loop" },
  punch: { name: "Punch_Jab", once: true },
  punch2: { name: "Punch_Cross", once: true },
};

const ARM_BONES = ["leftUpperArm", "rightUpperArm", "leftLowerArm", "rightLowerArm", "leftHand", "rightHand"];
const FINGERS = ["Index", "Middle", "Ring", "Little"].flatMap((f) =>
  ["Proximal", "Intermediate", "Distal"].flatMap((p) => [`left${f}${p}`, `right${f}${p}`]),
);

const loader = new GLTFLoader();
loader.register((parser) => new VRMLoaderPlugin(parser));

const _q = new THREE.Quaternion();
const _q2 = new THREE.Quaternion();
const _e = new THREE.Euler();
const _v = new THREE.Vector3();

// Euler angles (degrees) in the body frame (+Z forward, +X left) to a
// normalised-bone quaternion; VRM 0.x bones face the other way, so flip.
function bodyQuat(vrm0, x, y, z, out = new THREE.Quaternion()) {
  _e.set((x * Math.PI) / 180, (y * Math.PI) / 180, (z * Math.PI) / 180, "XYZ");
  out.setFromEuler(_e);
  if (vrm0) {
    out.x = -out.x;
    out.z = -out.z;
  }
  return out;
}

export async function loadCharacter(url, suitInfo, report) {
  const gltf = await loader.loadAsync(url);
  const vrm = gltf.userData.vrm;
  const vrm0 = vrm.meta?.metaVersion === "0";
  if (vrm0) VRMUtils.rotateVRM0(vrm);
  VRMUtils.removeUnnecessaryVertices(gltf.scene);
  vrm.scene.traverse((o) => {
    if (o.isMesh) {
      o.frustumCulled = false;
      o.castShadow = true;
    }
  });
  vrm.scene.updateMatrixWorld(true);
  const info = { vrm0, suit: null, hidden_faces: 0, materials: [] };
  vrm.scene.traverse((o) => {
    if (!o.isMesh) return;
    for (const m of [o.material].flat()) if (m && !info.materials.includes(m.name)) info.materials.push(m.name);
  });

  if (suitInfo) {
    try {
      info.suit = await attachSuit(vrm, suitInfo);
      info.hidden_faces = hideDress(vrm, suitInfo.sidecar.hide_rule);
      tintUndersuit(vrm, suitInfo.sidecar);
    } catch (err) {
      report(`Suit not attached: ${err.message}`);
      info.suit = null;
    }
  }

  const root = new THREE.Group();
  root.add(vrm.scene);
  const ch = new Character(vrm, root, info);
  try {
    await ch.loadClips();
  } catch (err) {
    report(`Animations not loaded, using poses only: ${err.message}`);
  }
  return ch;
}

async function attachSuit(vrm, { glbUrl, sidecar }) {
  const gltf = await new GLTFLoader().loadAsync(glbUrl);
  const suit = gltf.scene;
  suit.updateMatrixWorld(true);
  const parts = [];
  suit.traverse((o) => {
    if (o.userData && o.userData.bone) parts.push(o);
  });
  if (!parts.length) {
    // No extras survived: fall back to the sidecar's part list by name.
    for (const p of sidecar.parts || []) {
      const o = suit.getObjectByName(p.name);
      if (o) {
        o.userData.bone = p.bone;
        parts.push(o);
      }
    }
  }
  let attached = 0;
  for (const o of parts) {
    const bone = vrm.humanoid.getRawBoneNode(o.userData.bone);
    if (!bone) continue;
    bone.attach(o);
    attached += 1;
    o.traverse((m) => {
      if (m.isMesh) {
        m.castShadow = true;
        m.frustumCulled = false;
        m.userData.suit = true;
      }
    });
  }
  const helmet = (sidecar.parts || []).some((p) => p.part === "helmet");
  if (helmet) {
    vrm.scene.traverse((o) => {
      if (/hair/i.test(o.name) && o.isMesh) o.visible = false;
    });
  }
  return { attached, parts: parts.length, helmet };
}

// Hide the dress faces the sidecar's hide rule names: dominant joint a
// skirt or sleeve joint, an arm bone, the hips or one of extra_dominant (the
// torso bones the shells cover), or a mean arm skin weight of 0.3 or more
// (the sleeve root). Returns how many faces went.
function hideDress(vrm, rule) {
  if (!rule) return 0;
  const arm = new Set(ARM_BONES.map((n) => vrm.humanoid.getRawBoneNode(n)).filter(Boolean));
  const hips = vrm.humanoid.getRawBoneNode("hips");
  const extra = new Set();
  for (const n of rule.extra_dominant || []) {
    const b = vrm.humanoid.getRawBoneNode(n) || vrm.scene.getObjectByName(n);
    if (b) extra.add(b);
  }
  const armWeight = rule.hide_face_if_arm_weight ? 0.3 : Infinity;
  const want = rule.material;
  let hidden = 0;
  vrm.scene.traverse((o) => {
    if (!o.isSkinnedMesh) return;
    const mats = [o.material].flat();
    if (!mats.some((m) => m && m.name && (m.name === want || m.name.startsWith(want)))) return;
    const g = o.geometry;
    const idx = g.index;
    const si = g.attributes.skinIndex;
    const sw = g.attributes.skinWeight;
    if (!idx || !si || !sw) return;
    const bones = o.skeleton.bones;
    const keep = [];
    const sum = new Map();
    for (let f = 0; f < idx.count; f += 3) {
      sum.clear();
      let onArm = 0;
      for (let k = 0; k < 3; k++) {
        const v = idx.getX(f + k);
        for (let j = 0; j < 4; j++) {
          const w = sw.getComponent(v, j);
          if (w > 0) {
            const b = si.getComponent(v, j);
            sum.set(b, (sum.get(b) || 0) + w);
            if (arm.has(bones[b])) onArm += w;
          }
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
        bone === hips ||
        extra.has(bone) ||
        onArm / 3 >= armWeight;
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

class Character {
  constructor(vrm, root, info) {
    this.vrm = vrm;
    this.root = root;
    this.info = info;
    this.vrm0 = info.vrm0;
    this.mixer = new THREE.AnimationMixer(vrm.scene);
    this.actions = {};
    this.state = null;
    this.stateT = 0;
    this.punchFlip = false;
    this.cloaked = false;
    this.saved = new Map();
    this.bones = {};
    for (const n of [...Object.values(SRC_TO_VRM), ...FINGERS]) {
      const node = vrm.humanoid.getNormalizedBoneNode(n);
      if (node) this.bones[n] = node;
    }
    this.cloakMat = new THREE.MeshStandardMaterial({
      color: 0x8fdcff,
      emissive: 0x1a6080,
      transparent: true,
      opacity: 0.16,
      depthWrite: false,
      roughness: 0.2,
      metalness: 0.6,
    });
  }

  async loadClips() {
    const gltf = await new GLTFLoader().loadAsync(ANIM_URL);
    const src = gltf.scene;
    src.updateMatrixWorld(true);
    const clean = (n) => THREE.PropertyBinding.sanitizeNodeName(n);
    const map = {};
    for (const [k, v] of Object.entries(SRC_TO_VRM)) map[clean(k)] = v;
    // The hips track is in the armature's frame, which is Z-up under a
    // rotated root, so heights are read in world space through the parent.
    const srcHips = src.getObjectByName(clean("DEF-hips"));
    const srcHipsY = srcHips.getWorldPosition(_v).y;
    const srcParent = srcHips.parent.matrixWorld;
    const hipsRest = this.bones.hips.position.clone();
    const byName = Object.fromEntries(gltf.animations.map((c) => [c.name, c]));
    const restInv = new THREE.Quaternion();
    const parentRest = new THREE.Quaternion();
    for (const [key, def] of Object.entries(CLIPS)) {
      const clip = byName[def.name];
      if (!clip) continue;
      const tracks = [];
      for (const tr of clip.tracks) {
        const [node, prop] = tr.name.split(".");
        const vrmBone = map[node];
        const target = vrmBone && this.bones[vrmBone];
        if (!target) continue;
        const srcNode = src.getObjectByName(node);
        if (prop === "quaternion") {
          srcNode.getWorldQuaternion(restInv).invert();
          srcNode.parent.getWorldQuaternion(parentRest);
          const vals = tr.values.slice();
          for (let i = 0; i < vals.length; i += 4) {
            _q.fromArray(vals, i).premultiply(parentRest).multiply(restInv);
            _q.toArray(vals, i);
          }
          if (this.vrm0) for (let i = 0; i < vals.length; i += 2) vals[i] = -vals[i];
          tracks.push(new THREE.QuaternionKeyframeTrack(`${target.name}.quaternion`, tr.times, vals));
        } else if (prop === "position" && vrmBone === "hips") {
          // In place: keep the bob and the crouch, drop the travel.
          const vals = tr.values.slice();
          for (let i = 0; i < vals.length; i += 3) {
            vals[i] = hipsRest.x;
            _v.fromArray(vals, i).applyMatrix4(srcParent);
            vals[i + 1] = hipsRest.y * (_v.y / srcHipsY);
            vals[i + 2] = hipsRest.z;
          }
          tracks.push(new THREE.VectorKeyframeTrack(`${target.name}.position`, tr.times, vals));
        }
      }
      const out = new THREE.AnimationClip(key, clip.duration, tracks);
      const act = this.mixer.clipAction(out);
      if (def.once) {
        act.setLoop(THREE.LoopOnce, 1);
        act.clampWhenFinished = true;
      }
      this.actions[key] = act;
    }
    this.play("idle", 0);
  }

  play(key, fade = 0.18) {
    const next = this.actions[key];
    if (!next || this.state === key) return;
    const prev = this.state && this.actions[this.state];
    next.reset();
    next.enabled = true;
    next.setEffectiveTimeScale(1);
    next.setEffectiveWeight(1);
    next.play();
    if (prev && fade > 0) prev.crossFadeTo(next, fade, false);
    else if (prev) prev.stop();
    this.state = key;
    this.stateT = 0;
  }

  setCloak(on) {
    if (on === this.cloaked) return;
    this.cloaked = on;
    this.vrm.scene.traverse((o) => {
      if (!o.isMesh) return;
      if (on) {
        this.saved.set(o, o.material);
        o.material = Array.isArray(o.material) ? o.material.map(() => this.cloakMat) : this.cloakMat;
        o.castShadow = false;
      } else if (this.saved.has(o)) {
        o.material = this.saved.get(o);
        o.castShadow = true;
      }
    });
    if (!on) this.saved.clear();
  }

  // Pick the clip from the sim's player state and pose the bones.
  update(p, stats, t, dt) {
    const speed = Math.hypot(p.vx, p.vz);
    let key;
    if (p.slamming) key = "air";
    else if (p.sliding) key = "slide";
    else if (t - p.punched < 0.35 && !p.held) key = this.state === "punch" || this.state === "punch2" ? this.state : this.punchFlip ? "punch2" : "punch";
    else if (!p.onGround) key = p.vy > 0.5 && this.stateT < 0.35 && this.state === "jump" ? "jump" : p.vy > 1 && this.state !== "air" ? "jump" : "air";
    else if (t - p.landedAt < 0.18) key = "land";
    else if (p.dashT > 0 || speed > 0.82 * stats.move.sprint_mps) key = "sprint";
    else if (speed > 2.0) key = "run";
    else if (speed > 0.25) key = "walk";
    else key = "idle";
    if ((key === "punch" || key === "punch2") && this.state !== key) this.punchFlip = !this.punchFlip;
    if (!this.actions[key]) key = this.actions.idle ? "idle" : null;
    if (key) this.play(key, key === "punch" || key === "punch2" ? 0.06 : 0.16);
    this.stateT += dt;
    const def = CLIPS[this.state];
    const act = this.actions[this.state];
    if (act && def && def.mps) act.setEffectiveTimeScale(Math.min(1.8, Math.max(0.6, speed / def.mps)));
    this.mixer.update(dt);
    this.overlay(p, t);
    this.root.position.set(p.x, p.y, p.z);
    this.root.rotation.y = p.yaw;
    this.setCloak(p.mode === "cloak");
    this.vrm.update(dt);
  }

  set(name, x, y, z, mix = 1) {
    const b = this.bones[name];
    if (!b) return;
    bodyQuat(this.vrm0, x, y, z, _q2);
    if (mix >= 1) b.quaternion.copy(_q2);
    else b.quaternion.slerp(_q2, mix);
  }

  turn(name, x, y, z) {
    const b = this.bones[name];
    if (!b) return;
    b.quaternion.premultiply(bodyQuat(this.vrm0, x, y, z, _q2));
  }

  overlay(p, t) {
    const noClips = !this.actions.idle;
    if (noClips) this.proceduralBase(p, t);
    // Fists: curl the fingers (the clips leave VRM hands flat).
    for (const f of FINGERS) this.set(f, 0, 0, f.startsWith("left") ? -65 : 65);
    if (p.armsBroken) {
      this.set("leftUpperArm", 0, 0, -78);
      this.set("rightUpperArm", 0, 0, 78);
      this.set("leftLowerArm", 0, 0, -5);
      this.set("rightLowerArm", 0, 0, 5);
      this.turn("spine", 12, 0, 0);
    } else if (p.held) {
      // Arms forward and a little down, elbows bent, crate in front.
      this.set("leftUpperArm", 0, -70, -30);
      this.set("rightUpperArm", 0, 70, 30);
      this.set("leftLowerArm", 0, -15, 0);
      this.set("rightLowerArm", 0, 15, 0);
    }
    if (p.slamming) {
      this.turn("spine", 25, 0, 0);
      this.set("leftUpperArm", 0, -20, -55);
      this.set("rightUpperArm", 0, 20, 55);
    }
    if (p.sliding) {
      // Lean back into the slide: mostly the spine, a little at the hips, so
      // the crouched legs stay low.
      this.turn("hips", -8, 0, 0);
      this.turn("spine", -20, 0, 0);
    }
    if (p.dashT > 0) this.turn("spine", 18, 0, 0);
  }

  // Poses only, for when the clip library is missing.
  proceduralBase(p, t) {
    const speed = Math.hypot(p.vx, p.vz);
    const w = Math.min(1, speed / 4);
    const ph = t * (4 + speed);
    const s = Math.sin(ph) * 40 * w;
    this.set("leftUpperLeg", s, 0, 0);
    this.set("rightUpperLeg", -s, 0, 0);
    this.set("leftLowerLeg", -Math.max(0, -s) * 1.2, 0, 0);
    this.set("rightLowerLeg", -Math.max(0, s) * 1.2, 0, 0);
    this.set("leftUpperArm", -s * 0.8, 0, -70);
    this.set("rightUpperArm", s * 0.8, 0, 70);
    if (!p.onGround) {
      this.set("leftUpperLeg", -30, 0, 0);
      this.set("leftLowerLeg", 50, 0, 0);
    }
  }
}
