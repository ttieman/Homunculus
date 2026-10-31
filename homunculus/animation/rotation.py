"""One absolute character-space rotation, baked after retargeting and composition.

Pitch X, then yaw Y, then roll Z; positive angles follow the right-hand rule.
The pivot is the first pelvis position. Local child rotations remain untouched.
"""

import copy
import math

import numpy as np

from homunculus.retarget.geometry import mat_q, qmat

AXES = ('pitch', 'yaw', 'roll')


def rotation_values(value=None):
    if value is None:
        value = {}
    if not isinstance(value, dict) or set(value) - set(AXES):
        raise ValueError('Animation rotation must contain only pitch, yaw and roll')
    out = {}
    for axis in AXES:
        angle = value.get(axis, 0)
        if (
            isinstance(angle, bool)
            or not isinstance(angle, (int, float))
            or not math.isfinite(angle)
            or not -180 <= angle <= 180
        ):
            raise ValueError(f'Animation {axis} must be a finite angle from -180 to 180 degrees')
        out[axis] = float(angle)
    return out


def rotation_matrix(value=None):
    x, y, z = np.radians(list(rotation_values(value).values()))
    cx, sx, cy, sy, cz, sz = np.cos(x), np.sin(x), np.cos(y), np.sin(y), np.cos(z), np.sin(z)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def apply_rotation(retargeted, rig, value=None):
    angles = rotation_values(value)
    if not any(angles.values()):
        return retargeted
    out = copy.deepcopy(retargeted)
    pelvis = rig.index('pelvis')
    for node in out['nodes']:
        ancestor = node
        while ancestor != pelvis and ancestor in rig.parent:
            ancestor = rig.parent[ancestor]
        if ancestor != pelvis:
            raise ValueError('Animation rotation requires all tracks under the pelvis')
    parent = rig.parent.get(pelvis)
    parent_rotation = qmat(rig.rest_world(parent)[1]) if parent is not None else np.eye(3)
    local_rotation = parent_rotation.T @ rotation_matrix(angles) @ parent_rotation
    rest_position, rest_rotation, _ = rig.local(pelvis)
    if 'pelvis' not in out['bones']:
        out['bones'].insert(0, 'pelvis')
        out['nodes'].insert(0, pelvis)
        for frame in out['frames']:
            frame['rotations_xyzw'].insert(0, rest_rotation.tolist())
    index = out['bones'].index('pelvis')
    has_translation = out.get('translation_node') is not None
    if has_translation and out['translation_node'] != pelvis:
        raise ValueError('Animation rotation requires pelvis translation')
    pivot = np.asarray(out['frames'][0]['translation'] if has_translation else rest_position)
    previous = None
    for frame in out['frames']:
        q = mat_q(local_rotation @ qmat(frame['rotations_xyzw'][index]))
        if previous is not None and np.dot(q, previous) < 0:
            q = -q
        frame['rotations_xyzw'][index] = q.tolist()
        previous = q
        if has_translation:
            frame['translation'] = (
                pivot + local_rotation @ (np.asarray(frame['translation']) - pivot)
            ).tolist()
    out['animation_rotation'] = angles
    out['rotation_pivot'] = 'first pelvis position'
    out[
        'note'
    ] += ' Whole-character rotation after composition; pivot at starting hips; no ground/contact correction.'
    return out
