import copy
import json
import numpy as np
import pytest
from test_spatial import bundle
from spatial import prepare_spatial,run_spatial
from puppet import Edit
from assets import save_asset,replay_asset
from quality import capture_quality
from meta import propose_reference


def test_asset_round_trip_and_corruption_detection(tmp_path):
    b=bundle();m=prepare_spatial(b);r=run_spatial(Edit(duration=3,obstacle=False),m)
    folder=tmp_path/'asset';profile=save_asset(folder,b,m,r,{})
    report=replay_asset(folder)
    assert report['passed'] and report['position_error_m']==0 and report['torque_error_Nm']==0
    assert profile['validation']['capture_accuracy']=='not measured'
    physics=json.loads((folder/'physics.json').read_text());physics['torque_limits_Nm'][0]=1
    (folder/'physics.json').write_text(json.dumps(physics))
    with pytest.raises(ValueError,match='hash mismatch'):replay_asset(folder)


def test_quality_annotations_are_separate_from_tracking():
    b=bundle();b['provenance']['image_size_px']=[100,100]
    for f in b['frames']:f['arm_pixels']=[[10,10],[20,20],[110,30]]
    report=capture_quality(b)
    assert len(report['out_of_frame_timestamps'])==len(b['frames'])
    assert report['reprojection_accuracy']['status'].startswith('not measured')
    annotations={'schema':'homunculus.annotations.v1','video_sha256':b['provenance']['video_sha256'],
        'frames':[{'t':0,'condition':'synthetic-clear','arm_pixels':[[13,14],None,None]}]}
    assert capture_quality(b,annotations)['reprojection_accuracy']['by_condition']['synthetic-clear']['rmse_pixels']==5
    annotations['video_sha256']='wrong'
    with pytest.raises(ValueError,match='mismatch'):capture_quality(b,annotations)


def test_spatial_telemetry_effort_and_repeatability():
    m=prepare_spatial(bundle());edit=Edit(duration=3,obstacle=False)
    a=run_spatial(edit,m);b=run_spatial(edit,m)
    assert a['frames']==b['frames']
    assert a['metrics']['motor_effort_Nm2_s']>0
    assert a['feasibility']['passed']
    assert a['feasibility']['balance'].startswith('not applicable')
    assert np.all(np.array(a['metrics']['peak_torque_Nm'])<=[35,35,35,20])
    assert 'xml' in a['physics_configuration']


def test_bounded_disturbance_is_measurable_reproducible_and_recorded(tmp_path):
    b=bundle();m=prepare_spatial(b);edit=Edit(duration=3,obstacle=False)
    clean=run_spatial(edit,m)
    disturbance={'time_s':.6,'joint_impulse_Nms':[0,.05,0,0]}
    perturbed=run_spatial(edit,m,disturbance=disturbance)
    assert clean['frames'][0]==perturbed['frames'][0]
    assert np.max(np.abs(np.array([f['hand'] for f in clean['frames']])-[f['hand'] for f in perturbed['frames']]))>1e-5
    assert any(any(f['external_torque_Nm']) for f in perturbed['frames'])
    assert np.all(np.array(perturbed['metrics']['peak_torque_Nm'])<=[35,35,35,20])
    directory=tmp_path/'disturbed';save_asset(directory,b,m,perturbed,{})
    assert replay_asset(directory)['passed']


@pytest.mark.parametrize('operation',['valid','unsupported','unsafe'])
def test_timeline_model_adapter_validates_without_sending_poses(monkeypatch,operation):
    b=bundle();original=copy.deepcopy(b)
    monkeypatch.setattr('meta.configured_key',lambda:'test-only')
    command={'operation':'set_duration','parameters':{'seconds':6}}
    if operation=='unsupported':command={'operation':'apply_torque','parameters':{'force':100}}
    if operation=='unsafe':command={'operation':'move_keyframe','targetId':'key-1','parameters':{'time':.000001}}
    class Response:
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def read(self):return json.dumps({'id':'network-fixture','choices':[{'message':{'tool_calls':[{'function':{'name':'edit_timeline','arguments':json.dumps({'commands':[command]})}}]}}]}).encode()
    def request(req,**kwargs):
        sent=json.loads(req.data);context=json.loads(sent['messages'][1]['content'])
        assert set(context['animation'])=={'skeleton','duration','keyframes'}
        return Response()
    monkeypatch.setattr('urllib.request.urlopen',request)
    if operation=='valid':
        result=propose_reference('Twice as slow',b,Edit(duration=3,obstacle=False))
        assert result['edit']['duration']==6
        assert prepare_spatial(result['capture']).times[-1]==6
    else:
        with pytest.raises(ValueError):propose_reference('test',b,Edit(duration=3,obstacle=False))
    assert b==original
