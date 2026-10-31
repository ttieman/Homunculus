"""Full-skeleton retarget: SAM 3D Body keypoints -> every bone of a stickman-contract rig.

Each animated bone has an aim (segment direction) and a roll reference, both written
as expressions over named keypoints (BONES). The same expressions are evaluated on
keypoints read off the character's own rest pose, so a bone's world rotation is

    R_world = frame(target aim, target ref) @ frame(rest aim, rest ref).T @ R_rest_world

which turns the rest pose into the observed pose with directions matched exactly and
roll matched as well as the reference allows. Local rotations follow from the
animated parent chain. Proportions are the character's own.

Kinematic only: the captured arm keeps its MuJoCo result (its directions replace that
arm's keypoints before retargeting); the rest of the body is not simulated. The body
stays in place: the pelvis keeps its rest X/Z and rises or drops with the observed
hip height above the lowest leg point, scaled to the character's leg length.

Coordinates: capture keypoints use the capture's basis (X image-right, Y up, Z toward
the camera). The character faces +Z with its left side on +X, so a person facing the
camera maps with the identity; turning away from the camera shows as pelvis yaw.
"""

import numpy as np

from homunculus.retarget.geometry import mat_q, qmat, unit
from homunculus.animation.timeline import source_time

# Official SAM 3D Body (MHR70) keypoint names, facebookresearch/sam-3d-body
# sam_3d_body/metadata/mhr70.py at b5c765a. Captures carry their own list; lookups are by name.
MHR70 = (
    [
        'nose',
        'left-eye',
        'right-eye',
        'left-ear',
        'right-ear',
        'left-shoulder',
        'right-shoulder',
        'left-elbow',
        'right-elbow',
        'left-hip',
        'right-hip',
        'left-knee',
        'right-knee',
        'left-ankle',
        'right-ankle',
        'left-big-toe-tip',
        'left-small-toe-tip',
        'left-heel',
        'right-big-toe-tip',
        'right-small-toe-tip',
        'right-heel',
    ]
    + [f'right-{f}' for f in ('thumb-tip', 'thumb-first-joint', 'thumb-second-joint', 'thumb-third-joint')]
    + [
        f'right-{d}-{p}'
        for d in ('index', 'middle', 'ring', 'pinky')
        for p in ('tip', 'first-joint', 'second-joint', 'third-joint')
    ]
    + ['right-wrist']
    + [f'left-{f}' for f in ('thumb-tip', 'thumb-first-joint', 'thumb-second-joint', 'thumb-third-joint')]
    + [
        f'left-{d}-{p}'
        for d in ('index', 'middle', 'ring', 'pinky')
        for p in ('tip', 'first-joint', 'second-joint', 'third-joint')
    ]
    + [
        'left-wrist',
        'left-olecranon',
        'right-olecranon',
        'left-cubital-fossa',
        'right-cubital-fossa',
        'left-acromion',
        'right-acromion',
        'neck',
    ]
)
assert len(MHR70) == 70

SIDES = {'L': 'left', 'R': 'right'}
FINGERS = [
    f'{d}-{p}'
    for d in ('index', 'middle', 'ring', 'pinky')
    for p in ('first-joint', 'second-joint', 'third-joint')
]
REQUIRED = (
    ['nose', 'left-ear', 'right-ear', 'neck']
    + [
        f'{s}-{p}'
        for s in ('left', 'right')
        for p in ('shoulder', 'elbow', 'wrist', 'hip', 'knee', 'ankle', 'big-toe-tip', 'small-toe-tip')
    ]
    + [f'{s}-{f}' for s in ('left', 'right') for f in FINGERS]
)
LEG_POINTS = [
    f'{s}-{p}' for s in ('left', 'right') for p in ('knee', 'ankle', 'heel', 'big-toe-tip', 'small-toe-tip')
]

# Animated bones, parents before children: (bone, aim from, aim to | vector, roll reference).
# Names with a side placeholder {s} expand to L/R; points with {p} expand to left/right.
BONES = [
    ('pelvis', 'mid_hip', 'neck', 'hip_line'),
    ('spine', 'mid_hip', 'neck', 'torso_line'),
    ('chest', 'mid_hip', 'neck', 'shoulder_line'),
    ('neck', 'neck', 'mid_ear', 'ear_line'),
    ('head', None, 'head_up', 'ear_line'),
]
for _s in 'LR':
    _p = SIDES[_s]
    BONES += [
        (f'shoulder.{_s}', 'neck', f'{_p}-shoulder', 'torso_forward'),
        (f'upper_arm.{_s}', f'{_p}-shoulder', f'{_p}-elbow', f'{_p}_elbow_hinge'),
        (f'forearm.{_s}', f'{_p}-elbow', f'{_p}-wrist', f'{_p}_elbow_hinge'),
        (f'hand.{_s}', f'{_p}-wrist', f'{_p}_hand', f'{_p}_elbow_hinge'),
    ]
for _s in 'LR':
    _p = SIDES[_s]
    BONES += [
        (f'thigh.{_s}', f'{_p}-hip', f'{_p}-knee', f'{_p}_knee_hinge'),
        (f'shin.{_s}', f'{_p}-knee', f'{_p}-ankle', f'{_p}_knee_hinge'),
        (f'foot.{_s}', f'{_p}-ankle', f'{_p}_toe', f'{_p}_knee_hinge'),
    ]
BODY_BONES = [b[0] for b in BONES]
HINGES = {f'{p}_elbow_hinge': (f'{p}-shoulder', f'{p}-elbow', f'{p}-wrist') for p in SIDES.values()}
HINGES.update({f'{p}_knee_hinge': (f'{p}-hip', f'{p}-knee', f'{p}-ankle') for p in SIDES.values()})
SMOOTH_SIGMA_S = 0.08  # comparable to the arm path's 90 ms window at SAM's ~13-15 Hz


def body_track(capture):
    """Validated (times from 0, points F x N x 3 in capture basis, names) or None if absent."""
    names = capture.get('body_keypoints')
    if names is None:
        return None
    if (
        not isinstance(names, list)
        or not 1 <= len(names) <= 256
        or not all(isinstance(n, str) for n in names)
        or len(set(names)) != len(names)
    ):
        raise ValueError('body_keypoints must be a list of unique names')
    missing = [n for n in REQUIRED if n not in names]
    if missing:
        raise ValueError('Body keypoints are missing ' + ', '.join(missing[:6]))
    basis = np.asarray(capture.get('basis'), dtype=float)
    frames = capture.get('frames', [])
    if not isinstance(frames, list) or len(frames) < 3:
        raise ValueError('Body track needs at least 3 frames')
    points, times = [], []
    for i, frame in enumerate(frames):
        p = np.asarray(frame.get('body'), dtype=float)
        if p.shape != (len(names), 3) or not np.isfinite(p).all():
            raise ValueError(f'capture.frames[{i}].body must be finite {len(names)}x3 keypoints')
        points.append(p @ basis.T)
        times.append(float(frame['t']))
    times = np.asarray(times) - times[0]
    if np.any(np.diff(times) <= 0):
        raise ValueError('Body frames must be strictly ordered in time')
    return times, np.asarray(points), list(names)


def smooth(times, points, sigma=SMOOTH_SIGMA_S):
    """Gaussian time smoothing of every keypoint (nonuniform sample times allowed)."""
    out = np.empty_like(points)
    for i, t in enumerate(times):
        w = np.exp(-0.5 * ((times - t) / sigma) ** 2)
        w[np.abs(times - t) > 3 * sigma] = 0
        out[i] = np.tensordot(w / w.sum(), points, axes=1)
    return out


def derive(p):
    """Add the derived points and vectors BONES refer to (in place); returns p."""

    def mid(a, b):
        return (p[a] + p[b]) / 2

    for side in SIDES.values():
        p.setdefault(
            f'{side}_hand',
            np.mean([p[f'{side}-{f}'] for f in FINGERS], axis=0) if f'{side}-{FINGERS[0]}' in p else None,
        )
        p.setdefault(
            f'{side}_toe',
            mid(f'{side}-big-toe-tip', f'{side}-small-toe-tip') if f'{side}-big-toe-tip' in p else None,
        )
    p['mid_hip'] = mid('left-hip', 'right-hip')
    p.setdefault('mid_ear', mid('left-ear', 'right-ear'))
    p['hip_line'] = p['left-hip'] - p['right-hip']
    p['shoulder_line'] = p['left-shoulder'] - p['right-shoulder']
    p['torso_line'] = unit(p['hip_line'], 'hip line') + unit(p['shoulder_line'], 'shoulder line')
    p['ear_line'] = p['left-ear'] - p['right-ear']
    up = p['neck'] - p['mid_hip']
    p['torso_forward'] = np.cross(p['shoulder_line'], up)
    p['head_up'] = np.cross(p['nose'] - p['mid_ear'], p['ear_line'])
    return p


def axes(aim, ref, fallback):
    """Orthonormal frame with columns [x, aim, ref projected off aim]."""
    y = unit(aim, 'bone aim')
    z = ref - np.dot(ref, y) * y
    if np.linalg.norm(z) < 1e-4 * max(np.linalg.norm(ref), 1e-9):
        z = fallback - np.dot(fallback, y) * y
        if np.linalg.norm(z) < 1e-9:
            z = np.cross(y, [1, 0, 0] if abs(y[0]) < 0.9 else [0, 0, 1])
    z = z / np.linalg.norm(z)
    return np.column_stack([np.cross(y, z), y, z])


def aim_of(p, bone):
    _, start, end, _ = bone
    return p[end] if start is None else p[end] - p[start]


def rest_points(rig):
    """Keypoints read off the character's rest pose, in character space."""
    world = {}

    def pos(name):
        if name not in world:
            world[name] = rig.rest_world(rig.index(name))
        return world[name][0]

    def along(name, length):
        t, r = rig.rest_world(rig.index(name))
        return t + qmat(r) @ [0, length, 0]

    p = {}
    for s, side in SIDES.items():
        p[f'{side}-hip'] = pos(f'thigh.{s}')
        p[f'{side}-knee'] = pos(f'shin.{s}')
        p[f'{side}-ankle'] = pos(f'foot.{s}')
        p[f'{side}_toe'] = along(f'toe.{s}', 0.1)
        p[f'{side}-shoulder'] = pos(f'upper_arm.{s}')
        p[f'{side}-elbow'] = pos(f'forearm.{s}')
        p[f'{side}-wrist'] = pos(f'hand.{s}')
        p[f'{side}_hand'] = along(f'hand.{s}', 0.08)
    p['neck'] = pos('neck')
    # Contract: rest head is upright, facing +Z with the character's left on +X.
    p['mid_ear'] = along('head', 0.2)
    p['left-ear'] = p['mid_ear'] + [0.15, 0, 0]
    p['right-ear'] = p['mid_ear'] - [0.15, 0, 0]
    p['nose'] = p['mid_ear'] + [0, 0, 0.15]
    return derive(p)


def hinge_series(points, name, rest):
    """Per-frame limb bend normal, continuous through straight-limb frames."""
    a, b, c = HINGES[name]
    raw = [np.cross(p[b] - p[a], p[c] - p[b]) for p in points]
    sizes = [
        np.linalg.norm(v) / max(np.linalg.norm(p[b] - p[a]) * np.linalg.norm(p[c] - p[b]), 1e-12)
        for v, p in zip(raw, points)
    ]
    seed = next((i for i, s in enumerate(sizes) if s > np.sin(np.radians(2))), int(np.argmax(sizes)))
    previous = raw[seed] / np.linalg.norm(raw[seed]) if sizes[seed] > 1e-9 else rest
    out = []
    for v, s in zip(raw, sizes):
        if s > np.sin(np.radians(2)):
            previous = v / np.linalg.norm(v)
        out.append(previous)
    return out


def check_rig(rig):
    for bone in BODY_BONES + ['root', 'toe.L', 'toe.R']:
        rig.index(bone)
    root_t, root_r = rig.rest_world(rig.index('root'))
    if not np.allclose(root_t, 0, atol=1e-4) or not np.allclose(np.abs(root_r), [0, 0, 0, 1], atol=1e-4):
        raise ValueError('Full-body retarget requires the root bone at the origin with no rotation')
    if rig.parent.get(rig.index('pelvis')) != rig.index('root'):
        raise ValueError('pelvis must be a child of root')


def leg_length(p, side):
    return np.linalg.norm(p[f'{side}-knee'] - p[f'{side}-hip']) + np.linalg.norm(
        p[f'{side}-ankle'] - p[f'{side}-knee']
    )


def retarget_body(result, rig, capture, keys=None, sigma=SMOOTH_SIGMA_S, physics_arm=False):
    """Every bone of the rig, sampled at the result's frame times. keys: the timeline keyframes used.
    physics_arm: drive the captured arm from the physics result instead of the capture."""
    check_rig(rig)
    track = body_track(capture)
    if track is None:
        raise ValueError('Capture has no body keypoints')
    times, raw, names = track
    pts = smooth(times, raw, sigma) if sigma > 0 else raw
    index = {n: i for i, n in enumerate(names)}
    frames = result['frames']
    duration = float(result['edit']['duration'])
    side = 'L' if (capture.get('provenance') or {}).get('side') == 'left' else 'R'
    arm = SIDES[side]

    # Body keypoints at each result frame (linear in source time), optionally with the physics arm substituted.
    sampled = []
    for frame in frames:
        st = source_time(keys, duration, frame['t']) if keys else None
        st = float(np.clip(st if st is not None else frame['t'] / duration * times[-1], 0, times[-1]))
        i = min(max(np.searchsorted(times, st, side='right') - 1, 0), len(times) - 2)
        u = (st - times[i]) / (times[i + 1] - times[i])
        q = (1 - u) * pts[i] + u * pts[i + 1]
        p = {n: q[index[n]] for n in REQUIRED + [n for n in LEG_POINTS if n in index]}
        derive(p)
        if physics_arm and 'elbow' in frame and 'hand' in frame:
            d1 = unit(np.asarray(frame['elbow']) - [0, 1.4, 0], 'physics upper arm')
            d2 = unit(np.asarray(frame['hand']) - np.asarray(frame['elbow']), 'physics forearm')
            shoulder, elbow, wrist = p[f'{arm}-shoulder'], p[f'{arm}-elbow'], p[f'{arm}-wrist']
            new_elbow = shoulder + d1 * np.linalg.norm(elbow - shoulder)
            new_wrist = new_elbow + d2 * np.linalg.norm(wrist - elbow)
            p[f'{arm}_hand'] = p[f'{arm}_hand'] + (new_wrist - wrist)
            p[f'{arm}-elbow'], p[f'{arm}-wrist'] = new_elbow, new_wrist
        p['_floor'] = min(p[n][1] for n in LEG_POINTS if n in p)
        sampled.append(p)

    rest = rest_points(rig)
    for name, (a, b, c) in HINGES.items():
        rest[name] = unit(np.cross(rest[b] - rest[a], rest[c] - rest[b]), f'rest {name}')
        for p, h in zip(sampled, hinge_series(sampled, name, rest[name])):
            p[name] = h

    node = {b: rig.index(b) for b in BODY_BONES}
    rest_world = {b: qmat(rig.rest_world(node[b])[1]) for b in BODY_BONES}
    rest_frames = {bone[0]: axes(aim_of(rest, bone), rest[bone[3]], rest[bone[3]]) for bone in BONES}
    parent_of = {b: rig.parent[node[b]] for b in BODY_BONES}
    by_node = {node[b]: b for b in BODY_BONES}

    # Standing hip height: leg length plus ankle height (heel distance, else 8% of the leg).
    def standing(p, leg):
        heels = [np.linalg.norm(p[f'{s}-ankle'] - p[f'{s}-heel']) for s in SIDES.values() if f'{s}-heel' in p]
        return leg * (1.08 if not heels else 1) + (np.mean(heels) if heels else 0)

    human_hip = np.median(
        [standing(p, (leg_length(p, 'left') + leg_length(p, 'right')) / 2) for p in sampled]
    )
    pelvis_rest = rig.local(node['pelvis'])[0]
    scale = float(pelvis_rest[1]) / human_hip  # contract: floor at the root, y = 0

    out, previous_ref = [], {}
    previous_q = {}
    for frame_, p in zip(frames, sampled):
        world, rotations = {}, []
        for bone in BONES:
            name = bone[0]
            ref = p[bone[3]]
            target = axes(aim_of(p, bone), ref, previous_ref.get(name, rest_frames[name][:, 2]))
            previous_ref[name] = target[:, 2]
            world[name] = target @ rest_frames[name].T @ rest_world[name]
            parent = parent_of[name]
            if parent in by_node:
                parent_world = world[by_node[parent]]
            else:
                parent_world = qmat(rig.rest_world(parent)[1])
            local = mat_q(parent_world.T @ world[name])
            if name in previous_q and np.dot(previous_q[name], local) < 0:
                local = -local
            previous_q[name] = local
            rotations.append(local.tolist())
        height = (p['mid_hip'][1] - p['_floor']) * scale
        out.append(
            {
                't': float(frame_['t']),
                'rotations_xyzw': rotations,
                'translation': [float(pelvis_rest[0]), float(height), float(pelvis_rest[2])],
            }
        )
    return {
        'schema': 'homunculus.retarget.v2',
        'mode': 'body',
        'physics_arm': physics_arm,
        'character': rig.source,
        'side': side,
        'bones': BODY_BONES,
        'nodes': [node[b] for b in BODY_BONES],
        'translation_bone': 'pelvis',
        'translation_node': node['pelvis'],
        'view': 'front',
        'mapping': 'camera frame: person facing the camera faces the character forward (+Z)',
        'character_to_puppet': np.eye(3).tolist(),
        'leg_scale': float(scale),
        'note': (
            'Kinematic full-body retarget from SAM keypoints; '
            + (
                'the captured arm uses the physics result. '
                if physics_arm
                else 'the captured arm follows the recording. '
            )
            + 'In place: pelvis height from hips above the lowest leg point. No foot IK or contact cleanup.'
        ),
        'frames': out,
    }
