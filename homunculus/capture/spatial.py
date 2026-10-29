"""SAM arm observations -> smoothed spatial-arm reference (SpatialMotion) for physics.

Shoulder twist is a bend-plane convention, not observed anatomical twist.
"""

import hashlib
import json
from dataclasses import dataclass
import numpy as np
import mujoco
from homunculus.animation import segments
from homunculus.animation.timeline import Timeline, from_spatial
from homunculus.capture.quality import capture_quality
from homunculus.contracts import MAX_FRAMES, object_value


def matrix(q):
    out = np.zeros(9)
    mujoco.mju_quat2Mat(out, np.asarray(q, dtype=float))
    return out.reshape(3, 3)


def hinge_angle(q):
    # q and -q represent the same rotation; wrap the hinge coordinate.
    return float((2 * np.arctan2(q[3], q[0]) + np.pi) % (2 * np.pi) - np.pi)


@dataclass
class SpatialMotion:
    times: np.ndarray
    poses: np.ndarray
    metadata: dict
    timeline: object = None

    def target(self, t, duration):
        t = np.clip(t / duration, 0, 1) * self.times[-1]
        pose = self.timeline.sample(t)
        shoulder, elbow = pose['rotations_wxyz']
        return np.r_[shoulder, hinge_angle(elbow)]


def prepare_spatial(bundle):
    object_value(bundle, 'capture')
    if bundle.get('schema') != 'homunculus.observations.v1':
        raise ValueError('Expected observations v1')
    provenance = object_value(bundle.get('provenance', {}), 'capture.provenance')
    if provenance.get('kind') not in ('sam3d', 'synthetic_test') or any(
        not isinstance(provenance.get(k), str) or not provenance[k]
        for k in ('model', 'revision', 'video_sha256')
    ):
        raise ValueError('Missing capture provenance')
    frames = bundle.get('frames', [])
    if not isinstance(frames, list) or not 3 <= len(frames) <= MAX_FRAMES:
        raise ValueError(f'Require 3–{MAX_FRAMES} frames')
    for i, f in enumerate(frames):
        object_value(f, f'capture.frames[{i}]')
    basis = np.asarray(bundle.get('basis'), dtype=float)
    if (
        basis.shape != (3, 3)
        or not np.isfinite(basis).all()
        or not np.allclose(basis @ basis.T, np.eye(3), atol=1e-5)
        or not np.isclose(np.linalg.det(basis), 1)
    ):
        raise ValueError('Invalid coordinate basis')
    times = np.array([f['t'] for f in frames], dtype=float)
    times -= times[0]
    if (
        not np.isfinite(times).all()
        or np.any(np.diff(times) <= 0)
        or np.max(np.diff(times)) > 0.251
        or not 2 <= times[-1] <= 30
    ):
        raise ValueError('Require ordered 2–30 second capture with gaps <=250 ms')
    poses = []
    singular = 0
    for f in frames:
        p = np.asarray(f.get('arm'), dtype=float)
        if p.shape != (3, 3) or not np.isfinite(p).all():
            raise ValueError('Spatial capture requires finite poses; trim missing estimates')
        v = np.diff(p, axis=0) @ basis.T
        lengths = np.linalg.norm(v, axis=1)
        if np.min(lengths) < 1e-6:
            raise ValueError('Degenerate segment')
        x, fore = v / lengths[:, None]
        bend = np.arccos(np.clip(x @ fore, -1, 1))
        y = fore - x * (x @ fore)
        if np.linalg.norm(y) < 0.08:
            singular += 1
            previous = matrix(poses[-1][:4])[:, 1] if poses else np.eye(3)[np.argmin(np.abs(x))]
            y = previous - x * (previous @ x)
            if np.linalg.norm(y) < 1e-6:
                y = np.cross(x, np.eye(3)[np.argmin(np.abs(x))])
        y /= np.linalg.norm(y)
        z = np.cross(x, y)
        q = np.zeros(4)
        mujoco.mju_mat2Quat(q, np.column_stack((x, y, z)).ravel())
        if poses and q @ poses[-1][:4] < 0:
            q = -q
        poses.append(np.r_[q, bend])
    poses = np.array(poses)
    delta = 2 * np.arccos(np.clip(np.abs(np.sum(poses[1:, :4] * poses[:-1, :4], axis=1)), 0, 1))
    speed = np.maximum(delta, np.abs(np.diff(poses[:, 4]))) / np.diff(times)
    # Full-body captures keep fast raw arm steps as a warning; the smoothed reference below still enforces 720 deg/s.
    jumps = [round(float(times[i + 1]), 3) for i in np.flatnonzero(speed > np.radians(720))]
    if jumps and 'body_keypoints' not in bundle:
        raise ValueError('Pose discontinuity exceeds 720 deg/s; inspect source')
    raw = poses.copy()
    for i, t in enumerate(times[1:-1], 1):
        neighbors = raw[np.abs(times - t) <= 0.09].copy()
        neighbors[neighbors[:, :4] @ raw[i, :4] < 0, :4] *= -1
        poses[i] = neighbors.mean(axis=0)
        poses[i, :4] /= np.linalg.norm(poses[i, :4])
    motion = SpatialMotion(
        times,
        poses,
        {
            'provenance': provenance,
            'source_duration_s': float(times[-1]),
            'bundle_sha256': hashlib.sha256(
                json.dumps(bundle, sort_keys=True, allow_nan=False).encode()
            ).hexdigest(),
            'mapping': 'spatial_arm_v1; fixed shoulder, normalized lengths, bend-plane twist convention',
            'smoothing': '90 ms quaternion hemisphere mean, normalized; endpoints preserved',
            'near_straight_frames': singular,
            'missing_frames': 0,
            'raw_arm_jumps_over_720_deg_s_at': jumps,
            'max_angular_speed_deg_s': float(np.degrees(max(speed))),
            'inference': (
                'SAM_RECONSTRUCTION_UNVERIFIED_ACCURACY'
                if provenance['kind'] == 'sam3d'
                else 'NOT_RUN_SYNTHETIC_TEST'
            ),
        },
    )
    motion.metadata['capture_quality'] = capture_quality(bundle)
    motion.timeline = (
        Timeline(bundle['reference_animation'])
        if 'reference_animation' in bundle
        else from_spatial(times, poses, motion.metadata)
    )
    for pose in motion.timeline.document['poses'].values():
        if not np.allclose(pose['rootPosition'], [0, 1.4, 0]):
            raise ValueError(
                'Supported-arm physics requires the fixed shoulder root; root motion is preview-only'
            )
        elbow = np.array(pose['rotations_wxyz'][1])
        if np.linalg.norm(elbow[1:3]) > 1e-6 or not -0.1 <= hinge_angle(elbow) <= 3.14:
            raise ValueError('Elbow pose exceeds rig hinge limits')
    motion.times = motion.timeline.times
    motion.metadata['capture_max_angular_speed_deg_s'] = motion.metadata.pop('max_angular_speed_deg_s')
    motion.metadata['reference_diagnostics'] = motion.timeline.validate_motion()
    motion.metadata['source_duration_s'] = float(motion.times[-1])
    motion.timing = segments.validate(bundle['timing'], float(times[-1])) if 'timing' in bundle else None
    motion.metadata['segments'] = segments.describe(motion.timing)
    return motion
