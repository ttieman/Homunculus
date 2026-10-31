import copy

import numpy as np
import pytest

from character_fixture import build
from homunculus.animation.composition import compose
from homunculus.animation.rotation import apply_rotation, rotation_matrix, rotation_values
from homunculus.editor.commands import validate_command
from homunculus.retarget.character_glb import export_character_glb, replay_pose
from homunculus.retarget.rig import Rig, read_glb
from test_body import rig, scenario  # shared synthetic body fixture, no personal media


@pytest.mark.parametrize(
    'angles',
    [
        {'pitch': -30},
        {'yaw': 90},
        {'roll': 45},
        {'pitch': -30, 'yaw': 53, 'roll': 18},
    ],
)
def test_export_rotates_every_joint_about_starting_hips(rig, scenario, angles):
    original = scenario[-1]
    saved = copy.deepcopy(original)
    rotated = apply_rotation(original, rig, angles)
    t0, before = replay_pose(export_character_glb(rig, original))
    t1, after = replay_pose(export_character_glb(rig, rotated))
    assert np.array_equal(t0, t1)
    pivot = before['pelvis'][0]
    matrix = rotation_matrix(angles)
    for bone in original['bones']:
        expected = pivot + (before[bone] - pivot) @ matrix.T
        np.testing.assert_allclose(after[bone], expected, atol=8e-7)
    assert original == saved
    doc, _ = read_glb(export_character_glb(rig, rotated))
    assert doc['extras']['homunculus']['animation_rotation'] == rotation_values(angles)


def test_zero_is_exact_and_setting_an_angle_does_not_accumulate(rig, scenario):
    original = scenario[-1]
    assert apply_rotation(original, rig, {}) is original
    assert apply_rotation(original, rig, {'pitch': 0, 'yaw': 0, 'roll': 0}) is original
    assert apply_rotation(original, rig, {'pitch': -30}) == apply_rotation(original, rig, {'pitch': -30})


def test_rotation_applies_after_mask_and_adds_required_pelvis_track(rig, scenario):
    masked = compose(scenario[-1], {'mode': 'mask', 'bones': ['forearm.L'], 'rootMotion': False})
    rotated = apply_rotation(masked, rig, {'yaw': 90})
    assert rotated['bones'] == ['pelvis', 'forearm.L']
    assert len(rotated['frames'][0]['rotations_xyzw']) == 2
    t0, before = replay_pose(export_character_glb(rig, masked))
    t1, after = replay_pose(export_character_glb(rig, rotated))
    pivot = before['pelvis'][0]
    for bone in scenario[-1]['bones']:
        np.testing.assert_allclose(
            after[bone], pivot + (before[bone] - pivot) @ rotation_matrix({'yaw': 90}).T, atol=8e-7
        )


@pytest.mark.parametrize(
    'invalid',
    [[], '30', {'x': 3}, {'pitch': True}, {'yaw': 181}, {'roll': float('nan')}, {'pitch': float('inf')}],
)
def test_invalid_rotation_is_rejected(invalid):
    with pytest.raises(ValueError):
        rotation_values(invalid)


def test_shared_command_exposes_degrees_and_rejects_invalid_values():
    assert validate_command('set_animation_rotation', {'pitch': -29.7}) == {'pitch': -29.7}
    for invalid in [{'yaw': 200}, {'roll': True}, {'pitch': float('nan')}, {'rotation': [1, 2, 3]}]:
        with pytest.raises(ValueError):
            validate_command('set_animation_rotation', invalid)


def test_world_axes_with_a_rotated_rig_parent(scenario):
    from homunculus.retarget.geometry import mat_q

    rig = Rig(build())
    pelvis = rig.index('pelvis')
    parent = rig.parent[pelvis]
    rig.document['nodes'][parent]['rotation'] = mat_q(rotation_matrix({'yaw': 35})).tolist()
    original = scenario[-1]
    t0, before = replay_pose(export_character_glb(rig, original))
    rotated = apply_rotation(original, rig, {'pitch': -30, 'roll': 15})
    t1, after = replay_pose(export_character_glb(rig, rotated))
    pivot = before['pelvis'][0]
    for bone in original['bones']:
        expected = pivot + (before[bone] - pivot) @ rotation_matrix({'pitch': -30, 'roll': 15}).T
        np.testing.assert_allclose(after[bone], expected, atol=1e-6)
