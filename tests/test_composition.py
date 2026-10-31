import copy
import numpy as np
import pytest
from homunculus.animation.composition import compose, validate_options
from homunculus.retarget.character_glb import export_character_glb
from homunculus.retarget.rig import Rig, read_glb
from character_fixture import build


def track(angle=0, duration=2):
    rig = Rig(build(), 'fixture.glb')
    bones = ['pelvis', 'upper_arm.L', 'forearm.L', 'thigh.R']
    return rig, dict(
        schema='homunculus.retarget.v2',
        mode='body',
        side='L',
        view='front',
        bones=bones,
        nodes=[rig.index(b) for b in bones],
        mapping='test',
        note='test',
        translation_bone='pelvis',
        translation_node=rig.index('pelvis'),
        frames=[
            dict(
                t=t,
                rotations_xyzw=[[0, 0, np.sin(angle / 2), np.cos(angle / 2)]] * 4,
                translation=[0, 1 + angle, 0],
            )
            for t in [0, duration / 2, duration]
        ],
    )


def options(mode='mask', **kwargs):
    return dict(mode=mode, bones=['upper_arm.L', 'forearm.L'], rootMotion=False, blend=0.5, **kwargs)


def test_mask_omits_unselected_glb_channels_and_preserves_source():
    rig, base = track(0.5)
    before = copy.deepcopy(base)
    out = compose(base, options())
    assert base == before
    assert out['bones'] == ['upper_arm.L', 'forearm.L']
    assert 'translation_node' not in out
    doc, _ = read_glb(export_character_glb(rig, out))
    targets = [c['target'] for c in doc['animations'][0]['channels']]
    assert targets == [dict(node=rig.index(b), path='rotation') for b in out['bones']]


def test_layer_changes_only_selected_tracks_and_keeps_base_duration():
    _, a = track(0.2)
    _, b = track(1, 3)
    out = compose(a, options('layer'), b)
    assert out['frames'][-1]['t'] == 2
    for frame in out['frames']:
        np.testing.assert_allclose(frame['rotations_xyzw'][1:3], b['frames'][0]['rotations_xyzw'][1:3])
        np.testing.assert_allclose(frame['rotations_xyzw'][0], a['frames'][0]['rotations_xyzw'][0])
        np.testing.assert_allclose(frame['rotations_xyzw'][3], a['frames'][0]['rotations_xyzw'][3])
        np.testing.assert_allclose(frame['translation'], a['frames'][0]['translation'])


def test_sequence_duration_transition_endpoints_and_shortest_arc():
    _, a = track(0.2)
    _, b = track(1, 3)
    out = compose(a, options('sequence'), b)
    assert out['frames'][-1]['t'] == 4.5
    start = next(f for f in out['frames'] if f['t'] == 1.5)
    end = next(f for f in out['frames'] if f['t'] == 2)
    np.testing.assert_allclose(start['rotations_xyzw'][1], a['frames'][0]['rotations_xyzw'][1])
    np.testing.assert_allclose(end['rotations_xyzw'][1], b['frames'][0]['rotations_xyzw'][1])
    assert np.all(np.diff([f['t'] for f in out['frames']]) > 0)
    for f in b['frames']:
        f['rotations_xyzw'] = [(-np.array(q)).tolist() for q in a['frames'][0]['rotations_xyzw']]
    same = compose(a, options('sequence'), b)
    for f in same['frames']:
        np.testing.assert_allclose(f['rotations_xyzw'][1], a['frames'][0]['rotations_xyzw'][1], atol=1e-12)


@pytest.mark.parametrize(
    'bad',
    [
        dict(mode='oops'),
        dict(bones=[]),
        dict(bones=['upper_arm.L'] * 2),
        dict(bones=['unknown']),
        dict(blend=float('nan')),
        dict(blend=True),
        dict(rootMotion=1),
    ],
)
def test_invalid_compositions_rejected(bad):
    with pytest.raises(ValueError):
        validate_options({**options(), **bad})


def test_missing_secondary_and_excessive_overlap_rejected():
    _, a = track()
    with pytest.raises(ValueError):
        compose(a, options('layer'))
    with pytest.raises(ValueError):
        compose(a, {**options('sequence'), 'blend': 2}, a)


def test_root_translation_is_independently_selectable():
    _, a = track(0.2)
    out = compose(a, {**options(), 'bones': [], 'rootMotion': True})
    assert out['bones'] == [] and out['translation_node'] == a['translation_node']
    assert out['frames'][0]['translation'] == a['frames'][0]['translation']
