from dataclasses import asdict, replace
import copy
import json
import numpy as np
import pytest
from puppet import Edit, run
from exporter import export_gltf, replay_gltf
from meta import propose


@pytest.fixture(scope='module')
def pair():
    return run(Edit(obstacle=False)), run(Edit())


def test_clean_tracking_and_obstacle_response(pair):
    clean, blocked = pair
    assert clean['metrics']['contact_steps'] == 0
    assert clean['metrics']['tracking_rmse_deg'] < 5  # visibly recognizable clean reach
    assert blocked['metrics']['contact_steps'] > 100
    assert blocked['frames'][0]['contacts'] == 0  # no starting overlap
    assert 0 < blocked['metrics']['max_penetration_m'] < .005  # < 1/7 of smallest link radius
    assert blocked['metrics']['tracking_rmse_deg'] > clean['metrics']['tracking_rmse_deg'] + 5
    assert np.max(np.linalg.norm(np.array([f['hand'] for f in clean['frames']])-
                                 np.array([f['hand'] for f in blocked['frames']]),axis=1)) > .1
    assert np.all(np.array(blocked['metrics']['peak_torque_Nm']) <= [35,20])


def test_export_replay_actual_motion_not_targets(pair):
    result = pair[1]
    document = json.loads(json.dumps(export_gltf(result)))
    replay = np.array(replay_gltf(document))
    physical = np.array([f['hand'] for f in result['frames']])
    assert np.max(np.abs(replay-physical)) < 1e-6  # float32 export precision budget
    changed = copy.deepcopy(document)
    changed['nodes'][1]['translation'][0] += .01
    assert np.max(np.abs(np.array(replay_gltf(changed))-physical)) > .005
    target_export = copy.deepcopy(result)
    for f in target_export['frames']:
        f['q'] = f['target']
    assert np.max(np.abs(np.array(replay_gltf(export_gltf(target_export)))-physical)) > .1


def test_reproducible_edit_and_undo(pair):
    original = Edit()
    edited = replace(original,duration=6,strength=.4,obstacle=False)
    changed = run(edited)
    restored = run(original)
    assert changed['frames'][-1]['t'] == pytest.approx(6)
    assert restored['frames'] == pair[1]['frames']
    assert changed['frames'][-1]['t'] != pair[1]['frames'][-1]['t']


@pytest.mark.parametrize('values',[{'strength':float('nan')},{'strength':True},{'duration':100},
    {'obstacle':'false'},{'arbitrary_code':'print(1)'},{'shoulder_deg':-500},[],{'elbow_deg':None}])
def test_invalid_edits(values):
    with pytest.raises(ValueError):
        Edit.parse(values)


def test_missing_meta_is_explicit(monkeypatch):
    monkeypatch.setattr('meta.configured_key',lambda: '')
    with pytest.raises(RuntimeError,match='BLOCKED'):
        propose('slower',Edit())


def test_adapter_contract_only_not_live_model(monkeypatch):
    # A network fixture exercises parsing, not model correctness or account access.
    monkeypatch.setenv('MODEL_API_KEY','test-only')
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self):
            return json.dumps({'id':'fixture','choices':[{'message':{'tool_calls':[{'function':{
                'name':'propose_edit','arguments':json.dumps(asdict(replace(Edit(),duration=6)))}}]}}]}).encode()
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k: Response())
    assert propose('slower',Edit())['edit']['duration'] == 6


@pytest.mark.parametrize('strength,damping',[(.1,.2),(.1,3),(2,.2),(2,3)])
def test_control_extremes_stay_finite(strength,damping):
    result = run(Edit(duration=2,shoulder_deg=100,elbow_deg=-100,strength=strength,damping=damping))
    assert np.all(np.isfinite([f['q'] for f in result['frames']]))
    assert np.all(np.array(result['metrics']['peak_torque_Nm']) <= [35,20])
