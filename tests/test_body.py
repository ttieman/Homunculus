import copy
import json

import numpy as np
import pytest

from homunculus.retarget import body
from homunculus.retarget.body import BODY_BONES, MHR70, retarget_body
from homunculus.retarget.character import Rig, export_character_glb, qmat, qmul, read_glb, replay_pose
from character_fixture import build
from homunculus.physics.settings import Edit
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import run_spatial
from test_spatial import bundle

BASIS = np.array([[1.0, 0, 0], [0, -1, 0], [0, 0, -1]])  # SAM camera axes -> puppet, as in real captures


def axis_angle(axis, angle):
    axis = np.asarray(axis, float) / np.linalg.norm(axis)
    return np.r_[axis * np.sin(angle / 2), np.cos(angle / 2)]


@pytest.fixture(scope='module')
def rig():
    return Rig(build(), 'test-character.glb')


def hinge_in(rig, limb, bone):
    """Rest bend normal of a limb (three joint names), expressed in a bone's local frame."""
    a, b, c = (rig.rest_world(rig.index(n))[0] for n in limb)
    n = np.cross(b - a, c - b)
    n /= np.linalg.norm(n)
    return qmat(rig.rest_world(rig.index(bone))[1]).T @ n


def pose_at(rig, t):
    """Local rotations for a smooth, physically consistent full-body motion at time t.

    Spine/chest only twist about the torso axis and the head follows the neck, so the
    keypoint-defined aims are exact; elbows/knees/ankles bend about their rest hinges.
    """
    s = np.sin(2 * np.pi * t / 3)
    c = np.cos(2 * np.pi * t / 3)
    q = {}
    q['pelvis'] = qmul(axis_angle([0, 1, 0], 0.5 * s), axis_angle([1, 0, 0.3], 0.25 * c))
    q['spine'] = axis_angle([0, 1, 0], 0.2 * s)
    q['chest'] = axis_angle([0, 1, 0], 0.2 * s)
    q['neck'] = axis_angle([1, 0, 0.4], 0.35 * c)
    for side, sx, phase in (('L', 1, 0), ('R', -1, 1.3)):
        sp, cp = np.sin(2 * np.pi * t / 3 + phase), np.cos(2 * np.pi * t / 3 + phase)
        q[f'upper_arm.{side}'] = qmul(
            axis_angle([0, 0, sx], -0.9 - 0.6 * sp), axis_angle([0, 1, 0], 0.5 * cp)
        )
        arm = (f'upper_arm.{side}', f'forearm.{side}', f'hand.{side}')
        q[f'forearm.{side}'] = axis_angle(hinge_in(rig, arm, f'forearm.{side}'), 0.8 + 0.6 * sp)
        q[f'thigh.{side}'] = qmul(
            axis_angle([1, 0, 0.2 * sx], -0.6 - 0.5 * sp), axis_angle([0, 1, 0], 0.2 * cp)
        )
        leg = (f'thigh.{side}', f'shin.{side}', f'foot.{side}')
        q[f'shin.{side}'] = axis_angle(hinge_in(rig, leg, f'shin.{side}'), 0.5 + 0.5 * cp)
        q[f'foot.{side}'] = axis_angle(
            hinge_in(rig, leg, f'foot.{side}'), 0.2 * sp
        )  # ankle flexes about the knee axis
    return q


def fk(rig, deltas, pelvis_y):
    """World positions/rotations with each listed bone's rest local rotation followed by its delta."""
    nodes = rig.document['nodes']
    out = {}
    roots = [i for i in range(len(nodes)) if i not in rig.parent]
    stack = [(i, np.zeros(3), np.array([0, 0, 0, 1.0])) for i in roots]
    while stack:
        i, pt, pr = stack.pop()
        t, r, _ = rig.local(i)
        name = nodes[i].get('name')
        if name in deltas:
            r = qmul(r, deltas[name])
        if name == 'pelvis':
            t = np.array([t[0], pelvis_y, t[2]])
        wt, wr = pt + qmat(pr) @ t, qmul(pr, r)
        out[name] = (wt, wr)
        stack.extend((c, wt, wr) for c in nodes[i].get('children', []))
    return out


def keypoints(rig, world):
    """The 70 MHR keypoints a perfect observer would report for this posed rig (character space)."""
    pos = {n: world[n][0] for n in world}
    rot = {n: qmat(world[n][1]) for n in world}
    rest_rot = {n: qmat(rig.rest_world(rig.index(n))[1]) for n in world if n in rig.names}
    along = lambda n, length: pos[n] + rot[n] @ [0, length, 0]
    p = {}
    for s, side in (('L', 'left'), ('R', 'right')):
        p[f'{side}-hip'] = pos[f'thigh.{s}']
        p[f'{side}-knee'] = pos[f'shin.{s}']
        p[f'{side}-ankle'] = pos[f'foot.{s}']
        heel_local = rest_rot[f'foot.{s}'].T @ [0, -0.12, 0]
        p[f'{side}-heel'] = pos[f'foot.{s}'] + rot[f'foot.{s}'] @ heel_local
        toe = along(f'toe.{s}', 0.1)
        lateral = rot[f'toe.{s}'] @ [0.03, 0, 0]
        p[f'{side}-big-toe-tip'] = toe + lateral
        p[f'{side}-small-toe-tip'] = toe - lateral
        p[f'{side}-shoulder'] = pos[f'upper_arm.{s}']
        p[f'{side}-elbow'] = pos[f'forearm.{s}']
        p[f'{side}-wrist'] = pos[f'hand.{s}']
        hand = along(f'hand.{s}', 0.08)
        offsets = [rot[f'hand.{s}'] @ v for v in ([0.02, 0, 0], [-0.02, 0, 0], [0, 0, 0.02], [0, 0, -0.02])]
        for k, finger in enumerate(body.FINGERS):
            p[f'{side}-{finger}'] = hand + offsets[k % 4]
        for extra in (
            'thumb-tip',
            'thumb-first-joint',
            'thumb-second-joint',
            'thumb-third-joint',
            'index-tip',
            'middle-tip',
            'ring-tip',
            'pinky-tip',
            'eye',
            'olecranon',
            'cubital-fossa',
            'acromion',
        ):
            p.setdefault(f'{side}-{extra}', pos[f'hand.{s}'] if 'eye' not in extra else along('head', 0.25))
    p['neck'] = pos['neck']
    mid_ear = along('head', 0.2)
    head = rot['head']
    p['left-ear'] = mid_ear + head @ [0.15, 0, 0]
    p['right-ear'] = mid_ear - head @ [0.15, 0, 0]
    p['nose'] = mid_ear + head @ [0, 0, 0.15]
    return np.array([p[n] for n in MHR70])


def synthetic_capture(rig, seconds=3.0, hz=10, side='left', floor_shift=0.0):
    capture = bundle()
    frames = []
    truth = []
    arm = ('shoulder', 'elbow', 'wrist')
    for k in range(int(round(seconds * hz)) + 1):
        t = k / hz
        deltas = pose_at(rig, t)
        world = fk(rig, deltas, 0.0)
        pts = keypoints(rig, world)
        floor = min(pts[MHR70.index(n)][1] for n in body.LEG_POINTS)
        world = fk(rig, deltas, -floor)
        pts = keypoints(rig, world) + [0, floor_shift, 0]
        native = pts @ BASIS  # inverse of puppet = BASIS @ native
        frames.append(
            {
                't': t,
                'frame_index': k,
                'arm': [native[MHR70.index(f'{side}-{j}')].tolist() for j in arm],
                'body': native.tolist(),
            }
        )
        truth.append({'t': t, 'deltas': deltas, 'world': world, 'pelvis_y': -floor})
    capture['frames'] = frames
    capture['basis'] = BASIS.tolist()
    capture['body_keypoints'] = list(MHR70)
    capture['provenance']['side'] = side
    capture.pop('reference_animation', None)
    return capture, truth


@pytest.fixture(scope='module')
def scenario(rig):
    capture, truth = synthetic_capture(rig)
    motion = prepare_spatial(capture)
    result = run_spatial(Edit(duration=3, obstacle=False), motion)
    retargeted = retarget_body(result, rig, capture, motion.timeline.document['keyframes'], sigma=0)
    return capture, truth, result, retargeted


def quat_angle(a, b):
    return np.degrees(2 * np.arccos(min(1.0, abs(float(np.dot(a, b))))))


def coinciding(result_frames, truth):
    index = {round(f['t'], 6): i for i, f in enumerate(result_frames)}
    return [(index[round(tr['t'], 6)], tr) for tr in truth if round(tr['t'], 6) in index]


def test_uncaptured_bones_recover_the_exact_pose(rig, scenario):
    capture, truth, result, retargeted = scenario
    pairs = coinciding(retargeted['frames'], truth)
    assert len(pairs) >= 25
    worst = {}
    for i, tr in pairs:
        for b, q in zip(retargeted['bones'], retargeted['frames'][i]['rotations_xyzw']):
            if b in ('upper_arm.L', 'forearm.L', 'hand.L'):
                continue  # the captured arm comes from physics, checked separately
            expected = qmul(rig.local(rig.index(b))[1], tr['deltas'].get(b, [0, 0, 0, 1]))
            worst[b] = max(worst.get(b, 0), quat_angle(q, expected))
    assert max(worst.values()) < 0.05, {k: round(v, 4) for k, v in worst.items() if v >= 0.05}


def test_captured_arm_follows_physics_directions(rig, scenario):
    capture, truth, result, _ = scenario
    retargeted = retarget_body(
        result,
        rig,
        capture,
        prepare_spatial(capture).timeline.document['keyframes'],
        sigma=0,
        physics_arm=True,
    )
    glb = export_character_glb(rig, retargeted)
    times, world = replay_pose(glb)
    worst = 0
    for k, frame in enumerate(result['frames']):
        d1 = np.asarray(frame['elbow']) - [0, 1.4, 0]
        d2 = np.asarray(frame['hand']) - frame['elbow']
        u = world['forearm.L'][k] - world['upper_arm.L'][k]
        f = world['hand.L'][k] - world['forearm.L'][k]
        for a, b in ((u, d1), (f, d2)):
            worst = max(
                worst,
                np.degrees(np.arccos(np.clip(np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b), -1, 1))),
            )
    assert worst < 0.05


def test_captured_arm_follows_the_capture_by_default(rig, scenario):
    capture, truth, result, retargeted = scenario
    physics = retarget_body(
        result,
        rig,
        capture,
        prepare_spatial(capture).timeline.document['keyframes'],
        sigma=0,
        physics_arm=True,
    )
    arm = [retargeted['bones'].index(b) for b in ('upper_arm.L', 'forearm.L')]
    differs = any(
        not np.allclose(a['rotations_xyzw'][i], b['rotations_xyzw'][i], atol=1e-6)
        for a, b in zip(retargeted['frames'], physics['frames'])
        for i in arm
    )
    assert differs  # the default arm is the observed one, not the physics substitution


def test_export_replays_every_joint_and_the_pelvis_height(rig, scenario):
    capture, truth, result, retargeted = scenario
    glb = export_character_glb(rig, retargeted, {'note': 'test'})
    doc, _ = read_glb(glb)
    channels = doc['animations'][0]['channels']
    assert len(channels) == len(BODY_BONES) + 1 and doc['animations'][0]['name'] == 'Homunculus_Body'
    assert doc['extras']['homunculus']['mode'] == 'body'
    times, world = replay_pose(glb)
    scale = retargeted['leg_scale']
    assert scale == pytest.approx(0.9 / (0.41176 + 0.37179 + 0.12), rel=2e-3)
    for i, tr in coinciding(retargeted['frames'], truth):
        assert world['pelvis'][i][1] == pytest.approx(tr['pelvis_y'] * scale, abs=1e-5)
        assert world['pelvis'][i][[0, 2]] == pytest.approx([0, 0], abs=1e-6)  # in place
        # every uncaptured joint position relative to the pelvis matches the truth (scaled pelvis aside)
        for name in ('head', 'hand.R', 'toe.L', 'toe.R', 'shoulder.L', 'neck'):
            expected = tr['world'][name][0] - tr['world']['pelvis'][0]
            assert world[name][i] - world['pelvis'][i] == pytest.approx(expected, abs=2e-4), name


def test_floor_offset_and_camera_height_do_not_change_the_pose(rig):
    capture, _ = synthetic_capture(rig, floor_shift=0.75)
    motion = prepare_spatial(capture)
    result = run_spatial(Edit(duration=3, obstacle=False), motion)
    shifted = retarget_body(result, rig, capture, motion.timeline.document['keyframes'], sigma=0)
    capture, _ = synthetic_capture(rig)
    base = retarget_body(result, rig, capture, motion.timeline.document['keyframes'], sigma=0)
    for a, b in zip(shifted['frames'], base['frames']):
        assert a['translation'] == pytest.approx(b['translation'], abs=1e-9)
        assert np.allclose(a['rotations_xyzw'], b['rotations_xyzw'], atol=1e-9)


def test_retiming_follows_the_timeline_source_times(rig, scenario):
    capture, truth, result, _ = scenario
    keys = copy.deepcopy(prepare_spatial(capture).timeline.document['keyframes'])
    slow = run_spatial(Edit(duration=6, obstacle=False), prepare_spatial(capture))
    retimed = retarget_body(slow, rig, capture, keys, sigma=0)
    base = retarget_body(result, rig, capture, keys, sigma=0)
    by_time = {round(f['t'], 6): f for f in base['frames']}
    compared = 0
    for f in retimed['frames'][::25]:
        same = by_time.get(round(f['t'] / 2, 6))
        if same is None:
            continue
        neck = BODY_BONES.index('neck')
        assert quat_angle(f['rotations_xyzw'][neck], same['rotations_xyzw'][neck]) < 1e-3
        compared += 1
    assert compared >= 5


def test_smoothing_reduces_keypoint_jitter():
    rng = np.random.default_rng(3)
    times = np.arange(0, 3, 1 / 15)
    clean = np.stack([np.sin(times)[:, None] * np.ones((1, 3))] * 4, axis=1)
    noisy = clean + rng.normal(0, 0.02, clean.shape)
    assert np.abs(body.smooth(times, noisy) - clean).mean() < 0.75 * np.abs(noisy - clean).mean()
    assert np.abs(body.smooth(times, clean) - clean)[3:-3].max() < 0.005  # a 1 rad/s motion is not flattened


def test_rejects_malformed_body_tracks(rig, scenario):
    capture = copy.deepcopy(scenario[0])
    capture['frames'][4]['body'] = capture['frames'][4]['body'][:-1]
    with pytest.raises(ValueError, match='finite 70x3'):
        body.body_track(capture)
    capture = copy.deepcopy(scenario[0])
    capture['body_keypoints'] = [n for n in MHR70 if n != 'left-knee'] + ['extra']
    with pytest.raises(ValueError, match='missing left-knee'):
        body.body_track(capture)
    assert body.body_track({k: v for k, v in scenario[0].items() if k != 'body_keypoints'}) is None


def test_mhr70_names_match_the_official_metadata_shape():
    assert (
        len(set(MHR70)) == 70
        and MHR70[69] == 'neck'
        and MHR70[41] == 'right-wrist'
        and MHR70[62] == 'left-wrist'
    )
    assert all(n in MHR70 for n in body.REQUIRED)


def test_add_body_backfills_from_preserved_npz(tmp_path, scenario):
    from scripts import add_body

    capture = copy.deepcopy(scenario[0])
    expected = [f.pop('body') for f in capture['frames']]
    capture.pop('body_keypoints')
    for frame, points in zip(capture['frames'], expected):
        extra = np.vstack([points, np.zeros((3, 3))])  # SAM may return more than the 70 named points
        np.savez_compressed(
            tmp_path / f"raw-{frame['frame_index']:06d}.npz", pred_keypoints_3d=extra, pred_cam_t=np.zeros(3)
        )
    (tmp_path / 'capture.json').write_text(json.dumps(capture))
    out = add_body.add_body(tmp_path)
    assert out['body_keypoints'] == MHR70
    assert np.allclose([f['body'] for f in out['frames']], expected)
    (tmp_path / 'raw-000003.npz').unlink()
    with pytest.raises(ValueError, match='raw-000003'):
        add_body.add_body(tmp_path)


def test_server_retargets_the_whole_body_when_the_capture_has_it(rig, scenario):
    import base64
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    from homunculus.editor.server import Handler

    def post(base, route, data):
        request = urllib.request.Request(
            base + route, data=json.dumps(data).encode(), headers={'Content-Type': 'application/json'}
        )
        return json.load(urllib.request.urlopen(request))

    Handler.rig = rig
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        capture = scenario[0]
        assert post(base, '/api/capture/validate', {'capture': capture})['body_keypoints'] == 70
        payload = post(
            base, '/api/simulate', {'edit': {'duration': 3, 'obstacle': False}, 'capture': capture}
        )
        assert payload['result']['retarget']['mode'] == 'body'
        assert payload['result']['retarget']['bones'] == BODY_BONES
        times, world = replay_pose(base64.b64decode(payload['character_glb']))
        assert len(times) == len(payload['result']['frames'])
        arm_only = post(
            base,
            '/api/simulate',
            {'edit': {'duration': 3, 'obstacle': False}, 'capture': capture, 'body': False},
        )
        assert arm_only['result']['retarget'].get('mode', 'arm') == 'arm'
        assert arm_only['result']['retarget']['bones'] == ['upper_arm.L', 'forearm.L']
    finally:
        Handler.rig = None
        server.shutdown()
        server.server_close()
        worker.join()
