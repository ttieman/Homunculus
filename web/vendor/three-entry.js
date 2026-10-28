// Build input for web/vendor/three.js (run `npm run build:three`).
// Only the pieces the 3D stage uses are bundled, so the server stays offline-capable.
export {
  WebGLRenderer, Scene, PerspectiveCamera, Group, Mesh, Line, LineSegments, BufferGeometry,
  Float32BufferAttribute, CapsuleGeometry, TubeGeometry, CatmullRomCurve3, SphereGeometry, CylinderGeometry, BoxGeometry, CircleGeometry,
  EdgesGeometry, MeshStandardMaterial, MeshBasicMaterial, LineBasicMaterial, LineDashedMaterial,
  ShadowMaterial, HemisphereLight, DirectionalLight, GridHelper, Vector3, Quaternion, Color,
  PCFShadowMap, SRGBColorSpace, DoubleSide, AnimationMixer, LoopOnce,
} from 'three';
export { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
export { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
