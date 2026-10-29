// Pure helpers for playback: decode glTF accessors, interpolate result frames and place the
// supported arm in the 3D world (shoulder at [0, 1.4, 0], upper arm 0.34 m, forearm 0.29 m).
// Quaternions are glTF order [x, y, z, w].
export function readAccessor(doc, index, width) {
  const a = doc.accessors[index],
    v = doc.bufferViews[a.bufferView];
  const bytes = Uint8Array.from(atob(doc.buffers[v.buffer].uri.split(',')[1]), c => c.charCodeAt(0));
  const view = new DataView(bytes.buffer);
  return Array.from({ length: a.count }, (_, i) =>
    Array.from({ length: width }, (_, j) =>
      view.getFloat32((v.byteOffset || 0) + (a.byteOffset || 0) + (i * width + j) * 4, true),
    ),
  );
}
export function slerp(a, b, u) {
  let dot = a.reduce((v, x, i) => v + x * b[i], 0);
  if (dot < 0) {
    b = b.map(x => -x);
    dot = -dot;
  }
  let q;
  if (dot > 0.9995) {
    q = a.map((x, i) => (1 - u) * x + u * b[i]);
  } else {
    const angle = Math.acos(Math.min(1, dot));
    q = a.map((x, i) => (Math.sin((1 - u) * angle) * x + Math.sin(u * angle) * b[i]) / Math.sin(angle));
  }
  const n = Math.hypot(...q);
  return q.map(x => x / n);
}
function rigFrames(frames, t) {
  let lo = 0,
    hi = frames.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid;
  }
  const a = frames[lo],
    b = frames[hi];
  return [a, b, t >= b.t ? 1 : Math.max(0, (t - a.t) / (b.t - a.t))];
}
export function sampleRig(frames, t) {
  const [a, b, u] = rigFrames(frames, t);
  return a.rotations_xyzw.map((q, i) => slerp(q, b.rotations_xyzw[i], u));
}
export function sampleTranslation(frames, t) {
  const [a, b, u] = rigFrames(frames, t);
  return a.translation ? a.translation.map((x, i) => x + (b.translation[i] - x) * u) : null;
}
export function sampleFrames(frames, t) {
  let lo = 0,
    hi = frames.length - 1;
  while (lo + 1 < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid;
  }
  if (t >= frames.at(-1).t) return frames.at(-1);
  const a = frames[lo],
    b = frames[hi],
    u = Math.max(0, (t - a.t) / (b.t - a.t));
  const out = { ...a };
  for (const k of ['q', 'target', 'elbow', 'hand', 'target_elbow', 'target_hand'])
    if (a[k]) out[k] = a[k].map((x, i) => x + (b[k][i] - x) * u);
  if (a.rotations) {
    out.rotations = a.rotations.map((q, i) => slerp(q, b.rotations[i], u));
    Object.assign(out, quaternionArm(out.rotations));
    out.q = out.rotations.map(q => 2 * Math.atan2(q[2], q[3]));
  }
  return out;
}
function rotate(q, v) {
  const [x, y, z, w] = q;
  const t = [2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0])];
  return [
    v[0] + w * t[0] + y * t[2] - z * t[1],
    v[1] + w * t[1] + z * t[0] - x * t[2],
    v[2] + w * t[2] + x * t[1] - y * t[0],
  ];
}
export function quaternionArm(q) {
  const a = rotate(q[0], [0.34, 0, 0]);
  const b = rotate(q[0], rotate(q[1], [0.29, 0, 0]));
  return { elbow: [a[0], 1.4 + a[1], a[2]], hand: [a[0] + b[0], 1.4 + a[1] + b[1], a[2] + b[2]] };
}
// Planar results carry joint angles only; place them in the Z=0 plane of the 3D world.
export function planarArm(q) {
  const elbow = [0.34 * Math.cos(q[0]), 1.4 + 0.34 * Math.sin(q[0]), 0];
  return {
    elbow,
    hand: [elbow[0] + 0.29 * Math.cos(q[0] + q[1]), elbow[1] + 0.29 * Math.sin(q[0] + q[1]), 0],
  };
}
export function armPoints(f) {
  return f.elbow && f.hand ? { elbow: f.elbow, hand: f.hand } : planarArm(f.q);
}
export function targetPoints(f) {
  return f.target_elbow && f.target_hand
    ? { elbow: f.target_elbow, hand: f.target_hand }
    : planarArm(f.target);
}
