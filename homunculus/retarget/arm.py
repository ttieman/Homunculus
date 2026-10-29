"""Retarget the supported-arm physics result onto the character's arm (no body keypoints).

The puppet frame is the camera frame (X image-right, Y up, Z toward the camera), so
the mapping depends on how the person stood in the recording (VIEWS):
- front: the person faces the camera. Identity: image-right is the character's
  left (+X), toward-camera is its forward (+Z). Default for 3D (spatial) captures.
- side: side-on reach. Puppet +X (the reach) is the character's forward and +Z
  points away from the body on the captured side. Default for planar captures and
  the procedural demo, which are side-on by construction.
Only segment directions transfer; the character
keeps its own proportions. The upper-arm roll is chosen so the elbow bends about
the upper arm's local X axis (the rig's hinge); with a straight arm the previous
bend plane is kept. The rest of the body stays in its rest pose.
"""

import math

import numpy as np
from homunculus.retarget.geometry import mat_q, qinv, qmat, qmul, unit

CHAIN = ('shoulder', 'upper_arm', 'forearm', 'hand')

STRAIGHT_SIN = math.sin(math.radians(2))


def side_of(result):
    return 'L' if (result.get('capture') or {}).get('provenance', {}).get('side') == 'left' else 'R'


VIEWS = {
    'front': 'person faces the camera: image-right -> character left (+X), toward camera -> forward (+Z)',
    'side': 'side-on: puppet +X reach -> character forward (+Z), puppet +Z -> outward on the captured side',
}


def default_view(result):
    return 'front' if result.get('rig') == 'spatial_arm_v1' else 'side'


def mapping(side, view):
    """3x3 matrix M with character = M @ puppet (a rotation, or a mirror for side-on left arms)."""
    if view == 'front':
        return np.eye(3)
    if view != 'side':
        raise ValueError(f'Unknown recording view {view!r}; use one of {sorted(VIEWS)}')
    return np.array([[0, 0, 1 if side == 'L' else -1], [0, 1, 0], [1, 0, 0]], dtype=float)


def to_character(v, side, view='side'):
    """Puppet direction -> character direction (see module docstring)."""
    return mapping(side, view) @ np.asarray(v, dtype=float)


def puppet_arm(frame):
    if 'elbow' in frame and 'hand' in frame:
        return np.array(frame['elbow'], dtype=float), np.array(frame['hand'], dtype=float)
    a, b = frame['q'][0], frame['q'][0] + frame['q'][1]
    elbow = np.array([0.34 * math.cos(a), 1.4 + 0.34 * math.sin(a), 0])
    return elbow, elbow + [0.29 * math.cos(b), 0.29 * math.sin(b), 0]


def retarget(result, rig, side=None, view=None):
    side = side or side_of(result)
    view = view or default_view(result)
    to_char = mapping(side, view)
    shoulder, upper, fore = (rig.index(f'{b}.{side}') for b in CHAIN[:3])
    shoulder_world = rig.rest_world(shoulder)[1]
    inv_shoulder = qinv(shoulder_world)
    root = np.array([0, 1.4, 0])
    directions = []
    for frame in result['frames']:
        elbow, hand = puppet_arm(frame)
        directions.append(
            (unit(to_char @ (elbow - root), 'upper arm'), unit(to_char @ (hand - elbow), 'forearm'))
        )
    # Seed the bend plane from the first visibly bent frame (else the most bent one; rest +Z if never bent).
    bend = qmat(rig.rest_world(upper)[1])[:, 2]
    perpendiculars = [d2 - np.dot(d2, d1) * d1 for d1, d2 in directions]
    sizes = [np.linalg.norm(v) for v in perpendiculars]
    seed = next((i for i, n in enumerate(sizes) if n > STRAIGHT_SIN), int(np.argmax(sizes)))
    if sizes[seed] > 1e-9:
        bend = perpendiculars[seed] / sizes[seed]
    previous = None
    frames = []
    for frame, (d1, d2) in zip(result['frames'], directions):
        perpendicular = d2 - np.dot(d2, d1) * d1
        if np.linalg.norm(perpendicular) > STRAIGHT_SIN:
            bend = perpendicular / np.linalg.norm(perpendicular)
        else:
            bend = bend - np.dot(bend, d1) * d1
            if np.linalg.norm(bend) < 1e-6:  # bend plane lost exactly along the arm; pick any normal
                bend = np.cross(d1, [1, 0, 0] if abs(d1[0]) < 0.9 else [0, 0, 1])
            bend /= np.linalg.norm(bend)
        x = np.cross(d1, bend)
        world_upper = mat_q(np.column_stack([x, d1, bend]))
        local_upper = qmul(inv_shoulder, world_upper)
        # Signed hinge angle in the bend plane; slightly negative only inside the straight-arm zone.
        angle = math.atan2(float(np.dot(d2, bend)), float(np.dot(d2, d1)))
        local_fore = np.array([math.sin(angle / 2), 0, 0, math.cos(angle / 2)])
        if previous is not None and np.dot(previous, local_upper) < 0:
            local_upper = -local_upper  # keep the quaternion hemisphere continuous for LINEAR sampling
        previous = local_upper
        frames.append({'t': float(frame['t']), 'rotations_xyzw': [local_upper.tolist(), local_fore.tolist()]})
    return {
        'schema': 'homunculus.retarget.v1',
        'character': rig.source,
        'side': side,
        'bones': [rig.document['nodes'][upper]['name'], rig.document['nodes'][fore]['name']],
        'nodes': [upper, fore],
        'view': view,
        'mapping': VIEWS[view],
        'character_to_puppet': to_char.T.tolist(),
        'note': 'Arm segment directions only; character proportions and rest body pose are kept.',
        'frames': frames,
    }
