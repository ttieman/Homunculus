// 3D viewport for the supported arm. World units are the physics units:
// metres, right-handed, +Y up, shoulder fixed at (0, 1.4, 0).
import * as THREE from '/vendor/three.js';

const SHOULDER = new THREE.Vector3(0, 1.4, 0);
const HOME = {position: new THREE.Vector3(2.05, 1.95, 3.0), target: new THREE.Vector3(.2, 1.02, -.05)};
const UP = new THREE.Vector3(0, 1, 0);
const COLORS = {sim: 0xb8f4b2, replay: 0xaacbff, target: 0x9eafaa, joint: 0xe1f6dc, body: 0x3d5353, obstacle: 0xd7945b};

function webglAvailable(canvas) {
  try { return !!(canvas.getContext('webgl2') || canvas.getContext('webgl')); } catch { return false; }
}

function material(color, extra = {}) {
  return new THREE.MeshStandardMaterial({color, roughness: .55, metalness: .05, ...extra});
}

// A capsule mesh that can be stretched between two points every frame.
function segment(radius, mat) {
  const mesh = new THREE.Mesh(new THREE.CapsuleGeometry(radius, 1, 6, 16), mat);
  mesh.castShadow = true;
  mesh.userData.radius = radius;
  return mesh;
}
const tmpA = new THREE.Vector3(), tmpB = new THREE.Vector3(), tmpDir = new THREE.Vector3();
function place(mesh, a, b) {
  tmpA.fromArray(a); tmpB.fromArray(b);
  tmpDir.subVectors(tmpB, tmpA);
  const length = tmpDir.length();
  mesh.visible = length > 1e-6;
  if (!mesh.visible) return;
  mesh.position.addVectors(tmpA, tmpB).multiplyScalar(.5);
  mesh.quaternion.setFromUnitVectors(UP, tmpDir.divideScalar(length));
  // Unscaled capsule spans 1 + 2r end to end; stretch it to the joint distance.
  mesh.scale.set(1, length / (1 + 2 * mesh.userData.radius), 1);
}

export function createStage(canvas) {
  if (!webglAvailable(canvas)) throw new Error('WebGL is unavailable in this browser; the 3D view cannot start.');
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  canvas.dataset.renderer = 'webgl';

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(38, 1, .05, 50);
  camera.position.copy(HOME.position);

  const controls = new THREE.OrbitControls(camera, canvas);
  controls.target.copy(HOME.target);
  controls.enableDamping = true;
  controls.dampingFactor = .09;
  controls.minDistance = .7;
  controls.maxDistance = 7;
  controls.maxPolarAngle = Math.PI * .58; // allow a slight look up from below the shoulder, never under the floor
  controls.update();
  canvas.addEventListener('dblclick', () => {
    camera.position.copy(HOME.position); controls.target.copy(HOME.target); controls.update();
  });

  scene.add(new THREE.HemisphereLight(0xdfeee6, 0x1a2326, 1.25));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(1.8, 4.2, 2.6);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  Object.assign(key.shadow.camera, {left: -2, right: 2, top: 2, bottom: -2, near: .5, far: 10});
  key.shadow.bias = -.0005;
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xa9c8ff, 1.6); // separates dark characters from the background
  rim.position.set(-2.2, 2.6, -2.4);
  scene.add(rim);

  // Floor: a grid for scale plus an invisible plane that only shows shadows.
  const grid = new THREE.GridHelper(4, 20, 0x4b5e5c, 0x2e3d3e);
  grid.position.set(.3, 0, 0);
  scene.add(grid);
  const floor = new THREE.Mesh(new THREE.CircleGeometry(2.2, 48), new THREE.ShadowMaterial({opacity: .32}));
  floor.rotation.x = -Math.PI / 2;
  floor.position.set(.3, .001, 0);
  floor.receiveShadow = true;
  scene.add(floor);

  // Fixed support: the post the shoulder hangs from.
  const steel = material(0x92a49a, {metalness: .4, roughness: .4});
  const post = segment(.02, steel); place(post, [0, 0, 0], [0, 1.4, 0]); scene.add(post);
  const base = new THREE.Mesh(new THREE.CylinderGeometry(.16, .18, .03, 32), steel);
  base.position.y = .015; base.receiveShadow = base.castShadow = true; scene.add(base);

  // Context silhouette is fixed scenery beside the shoulder, not a simulated body.
  const ghostBody = material(COLORS.body, {transparent: true, opacity: .55});
  const bodyZ = -.2;
  const torso = segment(.13, ghostBody); place(torso, [0, .86, bodyZ], [0, 1.36, bodyZ]);
  const head = new THREE.Mesh(new THREE.SphereGeometry(.11, 24, 16), ghostBody); head.position.set(0, 1.68, bodyZ); head.castShadow = true;
  const hipL = segment(.06, ghostBody); place(hipL, [.02, .82, bodyZ - .09], [.04, .06, bodyZ - .09]);
  const hipR = segment(.06, ghostBody); place(hipR, [-.02, .82, bodyZ + .09], [-.06, .06, bodyZ + .09]);
  const shoulderBar = segment(.05, ghostBody); place(shoulderBar, [0, 1.4, bodyZ - .14], [0, 1.4, -.02]);
  scene.add(torso, head, hipL, hipR, shoulderBar);

  // Obstacle (matches the MuJoCo geom: centre .47,1.65,0, half-size .075,.12,.16).
  const obstacleMat = material(COLORS.obstacle, {transparent: true, opacity: .38, emissive: 0x000000});
  const obstacle = new THREE.Group();
  const box = new THREE.Mesh(new THREE.BoxGeometry(.15, .24, .32), obstacleMat); box.castShadow = true;
  const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({color: COLORS.obstacle}));
  obstacle.add(box, edges); obstacle.position.set(.47, 1.65, 0);
  scene.add(obstacle);

  // Intended motion: translucent ghost arm.
  const targetMat = material(COLORS.target, {transparent: true, opacity: .28, depthWrite: false});
  const targetUpper = segment(.04, targetMat), targetFore = segment(.032, targetMat);
  const targetHand = new THREE.Mesh(new THREE.SphereGeometry(.04, 16, 12), targetMat);
  scene.add(targetUpper, targetFore, targetHand);

  // Physical (or replayed) arm.
  const armMat = material(COLORS.sim, {roughness: .45});
  const upper = segment(.045, armMat), fore = segment(.035, armMat);
  const jointMat = material(COLORS.joint, {roughness: .3});
  const shoulderJoint = new THREE.Mesh(new THREE.SphereGeometry(.058, 24, 16), material(0xe4e8cf, {roughness: .3}));
  shoulderJoint.position.copy(SHOULDER); shoulderJoint.castShadow = true;
  const elbowJoint = new THREE.Mesh(new THREE.SphereGeometry(.05, 20, 14), jointMat); elbowJoint.castShadow = true;
  const handJoint = new THREE.Mesh(new THREE.SphereGeometry(.05, 20, 14), armMat); handJoint.castShadow = true;
  scene.add(upper, fore, shoulderJoint, elbowJoint, handJoint);

  // Whole-clip hand path, plus a drop line to the floor so height reads in 3D.
  const pathMat = new THREE.MeshBasicMaterial({color: COLORS.sim, transparent: true, opacity: .45, depthWrite: false});
  const path = new THREE.Mesh(new THREE.BufferGeometry(), pathMat); path.visible = false; scene.add(path);
  const dropGeom = new THREE.BufferGeometry(); dropGeom.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(6), 3));
  const drop = new THREE.Line(dropGeom, new THREE.LineDashedMaterial({color: 0x7f948f, dashSize: .04, gapSize: .04, transparent: true, opacity: .6}));
  scene.add(drop);
  const shadowDot = new THREE.Mesh(new THREE.CircleGeometry(.03, 20), new THREE.MeshBasicMaterial({color: 0x9eafaa, transparent: true, opacity: .5, side: THREE.DoubleSide}));
  shadowDot.rotation.x = -Math.PI / 2; scene.add(shadowDot);

  // HTML label that follows the hand.
  const label = document.createElement('span');
  label.className = 'stage-label';
  canvas.parentElement.append(label);

  const armParts = [upper, fore, elbowJoint, handJoint, targetUpper, targetFore, targetHand, drop, shadowDot];
  for (const p of armParts) p.visible = false;

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      renderer.setPixelRatio(dpr); renderer.setSize(w, h, false);
      camera.aspect = w / h; camera.updateProjectionMatrix();
    }
  }

  // Optional game character (served by the local server; never bundled in this repo).
  const loader = new THREE.GLTFLoader();
  const character = {root: null, bones: {}, side: null, mixer: null, action: null};
  const sceneryBody = [torso, head, hipL, hipR, shoulderBar];
  const clean = name => name.replace(/[\[\]\.:\/]/g, ''); // GLTFLoader strips these from node names
  const bone = (name, side) => character.bones[clean(`${name}.${side}`)];
  const handWorld = new THREE.Vector3();
  function placeCharacter(side) {
    if (!character.root || character.side === side) return;
    character.side = side;
    // Character faces +Z; puppet +X is its forward, puppet +Z its captured side (mirror for the left arm).
    character.root.position.set(0, 0, 0);
    character.root.rotation.set(0, Math.PI / 2, 0);
    character.root.scale.set(side === 'L' ? -1 : 1, 1, 1);
    character.root.updateMatrixWorld(true);
    const shoulder = bone('upper_arm', side).getWorldPosition(new THREE.Vector3());
    character.root.position.set(-shoulder.x, 0, -shoulder.z); // shoulders share the vertical axis; feet stay on the floor
  }

  const projected = new THREE.Vector3();
  return {
    async loadCharacter(url) {
      const gltf = await loader.loadAsync(url);
      character.root = new THREE.Group();
      character.root.add(gltf.scene);
      gltf.scene.traverse(o => {
        if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; o.frustumCulled = false; }
        if (o.name) character.bones[o.name] = o;
      });
      for (const s of 'LR') for (const b of ['upper_arm', 'forearm', 'hand'])
        if (!bone(b, s)) throw new Error(`Character is missing ${b}.${s}`);
      character.mixer = new THREE.AnimationMixer(gltf.scene);
      scene.add(character.root);
      for (const p of sceneryBody) p.visible = false;
      armMat.transparent = true; armMat.opacity = .3; armMat.depthWrite = false;
      placeCharacter('R');
      canvas.dataset.character = 'loaded';
    },
    get hasCharacter() { return !!character.root; },
    async setReplayClip(buffer) {
      if (!character.root) return;
      character.action?.stop(); character.action = null;
      if (!buffer) return;
      const gltf = await loader.parseAsync(buffer, '');
      if (!gltf.animations.length) throw new Error('Exported character has no animation');
      character.action = character.mixer.clipAction(gltf.animations[0]);
      character.action.play();
    },
    setPath(points, replay = false) {
      path.geometry.dispose();
      const pts = (points || []).map(p => new THREE.Vector3(...p));
      path.visible = pts.length > 1;
      path.geometry = path.visible
        ? new THREE.TubeGeometry(new THREE.CatmullRomCurve3(pts), Math.min(pts.length * 2, 600), .007, 6, false)
        : new THREE.BufferGeometry();
      pathMat.color.setHex(replay ? COLORS.replay : COLORS.sim);
    },
    render(state) {
      resize();
      obstacle.visible = !!state.obstacle;
      obstacleMat.emissive.setHex(state.contact ? 0x6a2e08 : 0x000000);
      const arm = state.actual, target = state.target;
      const proxy = !!arm && (!character.root || !state.character || state.showPhysics);
      for (const p of armParts) p.visible = proxy;
      post.visible = base.visible = shoulderJoint.visible = !character.root?.visible || proxy;
      path.material.opacity = proxy || !character.root?.visible ? .45 : .25;
      drop.visible = shadowDot.visible = !!arm;
      if (arm) {
        const shoulder = SHOULDER.toArray();
        armMat.color.setHex(state.replay ? COLORS.replay : COLORS.sim);
        place(upper, shoulder, arm.elbow); place(fore, arm.elbow, arm.hand);
        elbowJoint.position.fromArray(arm.elbow); handJoint.position.fromArray(arm.hand);
        const pos = drop.geometry.attributes.position;
        pos.setXYZ(0, arm.hand[0], arm.hand[1], arm.hand[2]); pos.setXYZ(1, arm.hand[0], .002, arm.hand[2]); pos.needsUpdate = true;
        drop.computeLineDistances();
        shadowDot.position.set(arm.hand[0], .003, arm.hand[2]);
      }
      if (target && proxy) {
        place(targetUpper, SHOULDER.toArray(), target.elbow); place(targetFore, target.elbow, target.hand);
        targetHand.position.fromArray(target.hand);
      } else { targetUpper.visible = targetFore.visible = targetHand.visible = false; }
      if (!proxy) upper.visible = fore.visible = false; // place() re-shows segments it positions
      if (character.root) {
        const pose = state.character;
        character.root.visible = !!pose;
        if (pose) {
          placeCharacter(pose.side);
          if (pose.replayTime != null && character.action) {
            character.mixer.setTime(pose.replayTime);
          } else if (pose.rotations) {
            bone('upper_arm', pose.side).quaternion.fromArray(pose.rotations[0]);
            bone('forearm', pose.side).quaternion.fromArray(pose.rotations[1]);
          }
          character.root.updateMatrixWorld(true);
          bone('hand', pose.side).getWorldPosition(handWorld);
          const pos = drop.geometry.attributes.position;
          pos.setXYZ(0, handWorld.x, handWorld.y, handWorld.z); pos.setXYZ(1, handWorld.x, .002, handWorld.z); pos.needsUpdate = true;
          drop.computeLineDistances();
          shadowDot.position.set(handWorld.x, .003, handWorld.z);
        }
      }
      controls.update();
      renderer.render(scene, camera);
      if (arm && state.label) {
        projected.copy(character.root?.visible && !proxy ? handWorld : tmpA.fromArray(arm.hand)).project(camera);
        const visible = projected.z < 1;
        label.hidden = !visible;
        label.textContent = state.label;
        label.style.transform = `translate(${(projected.x * .5 + .5) * canvas.clientWidth + 16}px, ${(-projected.y * .5 + .5) * canvas.clientHeight - 7}px)`;
      } else label.hidden = true;
    },
  };
}
