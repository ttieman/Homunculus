import copy
import numpy as np
import pytest
from homunculus.animation import segments
from homunculus.editor.commands import validate_command
from homunculus.physics.settings import Edit
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import run_spatial
from test_spatial import bundle

EDIT = Edit(duration=3, obstacle=False)


def timed(*segs):
    b = bundle()
    b['timing'] = {'schema': segments.SCHEMA, 'segments': list(segs)}
    return b


@pytest.mark.parametrize(
    'seg,message',
    [
        ({'id': 'a', 'start': 1, 'end': 4, 'strength': 0.5}, 'within'),
        ({'id': 'a', 'start': 1, 'end': 2}, 'strength and/or damping'),
        ({'id': 'a', 'start': 1, 'end': 2, 'strength': 3}, 'strength must be'),
        ({'id': 'a', 'start': 1, 'end': 2, 'damping': 0.5, 'blend': 0.6}, 'blend'),
        ({'id': 'a', 'start': 1, 'end': 2, 'damping': 0.5, 'curve': 'bounce'}, 'curve'),
        ({'id': 'a', 'start': 1, 'end': 2, 'damping': 0.5, 'speed': 2}, 'unknown fields'),
    ],
)
def test_rejects_invalid_segments(seg, message):
    with pytest.raises(ValueError, match=message):
        segments.validate({'schema': segments.SCHEMA, 'segments': [seg]}, 3)


def test_rejects_overlap_and_planar_timing():
    with pytest.raises(ValueError, match='overlap'):
        segments.validate(
            {
                'schema': segments.SCHEMA,
                'segments': [
                    {'id': 'a', 'start': 0, 'end': 2, 'strength': 0.5},
                    {'id': 'b', 'start': 1.5, 'end': 3, 'strength': 0.5},
                ],
            },
            3,
        )
    from homunculus.capture.prepare import prepare

    planar = bundle()
    planar.pop('retargeting')
    planar['timing'] = segments.empty()
    with pytest.raises(ValueError, match='spatial'):
        prepare(planar)


def test_gains_hold_inside_and_blend_along_the_curve():
    doc = segments.validate(
        {
            'schema': segments.SCHEMA,
            'segments': [{'id': 'a', 'start': 1, 'end': 2, 'strength': 0.5, 'blend': 0.2, 'curve': 'linear'}],
        },
        3,
    )
    assert segments.gains(doc, 0.5, 1, 1) == (1, 1)
    assert segments.gains(doc, 1.5, 1, 1) == (0.5, 1)  # damping untouched: the segment only sets strength
    assert segments.gains(doc, 1.1, 1, 1)[0] == pytest.approx(0.75)
    assert segments.gains(doc, 1.9, 1, 1)[0] == pytest.approx(0.75)
    for name, curve in segments.CURVES.items():
        assert curve(0) == pytest.approx(0, abs=1e-3) and curve(1) == pytest.approx(1), name


def test_empty_layer_reproduces_the_unsegmented_result():
    base = run_spatial(EDIT, prepare_spatial(bundle()))
    empty = run_spatial(EDIT, prepare_spatial(timed()))
    assert [f['q'] for f in empty['frames']] == [f['q'] for f in base['frames']]


def test_segment_changes_physics_only_from_its_start():
    base = run_spatial(EDIT, prepare_spatial(bundle()))
    weak = run_spatial(
        EDIT,
        prepare_spatial(timed({'id': 'loose', 'start': 1.5, 'end': 2.5, 'strength': 0.2, 'damping': 0.3})),
    )
    before = [i for i, f in enumerate(base['frames']) if f['t'] < 1.5 - 1e-9]
    inside = [i for i, f in enumerate(base['frames']) if 1.6 <= f['t'] <= 2.4]
    assert all(
        weak['frames'][i]['q'] == base['frames'][i]['q'] for i in before
    )  # causal: nothing changes earlier
    assert {weak['frames'][i]['strength'] for i in inside} == {0.2} and {
        weak['frames'][i]['damping'] for i in inside
    } == {0.3}
    drift = lambda r: np.mean([np.abs(r['frames'][i]['error_rad']).sum() for i in inside])
    assert drift(weak) > 1.4 * drift(base)  # slow synthetic reach: ~1.6x more lag with a fifth of the gain
    assert weak['capture']['segments'][0]['id'] == 'loose'


def test_apply_replaces_by_id_and_clears():
    doc = segments.apply(
        None, {'operation': 'set', 'segment': {'id': 'a', 'start': 0, 'end': 1, 'strength': 0.5}}, 3
    )
    doc = segments.apply(
        doc, {'operation': 'set', 'segment': {'id': 'b', 'start': 2, 'end': 3, 'damping': 2}}, 3
    )
    doc = segments.apply(
        doc, {'operation': 'set', 'segment': {'id': 'a', 'start': 0.5, 'end': 1.5, 'strength': 0.7}}, 3
    )
    assert [(s['id'], s['start']) for s in doc['segments']] == [('a', 0.5), ('b', 2)]
    assert (
        segments.apply(copy.deepcopy(doc), {'operation': 'clear', 'ids': ['a']}, 3)['segments'][0]['id']
        == 'b'
    )
    assert segments.apply(doc, {'operation': 'clear'}, 3)['segments'] == []


def test_segment_commands_validate():
    validate_command(
        'set_segment',
        {'id': 'draw', 'start': 1, 'end': 2.5, 'strength': 0.6, 'blend': 0.2, 'curve': 'expo_out'},
    )
    validate_command('clear_segments', {})
    for bad in (
        {'id': 'x', 'start': 1},
        {'id': 'x', 'start': 0, 'end': 1, 'curve': 'bounce'},
        {'id': 'x', 'start': 0, 'end': 1, 'strength': 5},
    ):
        with pytest.raises(ValueError):
            validate_command('set_segment', bad)
