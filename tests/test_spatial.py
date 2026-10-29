import copy
import numpy as np
import pytest
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import run_spatial, synthesize, points
from homunculus.physics.settings import Edit
from homunculus.export.gltf import export_gltf, replay_gltf


def bundle():
    frames=[]
    for t in np.linspace(0,3,46):
        yaw=.6*np.sin(t); q=np.array([np.cos(yaw/2),0,np.sin(yaw/2),0,.8+.2*np.sin(t)])
        e,h=points(q)
        frames.append({'t':float(t),'arm':[[0,1.4,0],e,h]})
    return {'schema':'homunculus.observations.v1','retargeting':'spatial_arm_v1','basis':np.eye(3).tolist(),
            'provenance':{'kind':'synthetic_test','model':'analytic','revision':'1','video_sha256':'none'},'frames':frames}


def test_spatial_mapping_and_export():
    b=bundle(); m=prepare_spatial(b)
    for i in (0,-1):
        e,h=points(m.poses[i]); assert np.allclose([e,h],b['frames'][i]['arm'][1:])
    r=run_spatial(Edit(duration=3,obstacle=False),m)
    assert r['metrics']['tracking_rmse_deg']<10
    assert np.max(np.abs(np.array(replay_gltf(export_gltf(r)))-[f['hand'] for f in r['frames']]))<1e-6
    assert all(len(f['torque_Nm'])==4 and len(f['qvel'])==4 for f in r['frames'])
    assert not np.allclose([f['hand'] for f in r['frames']],[f['target_hand'] for f in r['frames']])
    corrupted=export_gltf(r); corrupted['nodes'][1]['translation'][0]+=.1
    assert np.max(np.abs(np.array(replay_gltf(corrupted))-[f['hand'] for f in r['frames']]))>.01


def test_search_retains_baseline_and_never_worsens_objective():
    r,report=synthesize(prepare_spatial(bundle()),Edit(duration=3,obstacle=False))
    assert len(report['candidates'])==5
    assert report['candidates'][report['selected']]['score']<=report['candidates'][0]['score']
    assert r['metrics']['max_penetration_m']==0


@pytest.mark.parametrize('problem',['gap','nan','basis','missing','degenerate'])
def test_reject_bad_observations(problem):
    b=bundle()
    if problem=='gap': b['frames'][2]['t']=1
    if problem=='nan': b['frames'][1]['arm'][0][0]=float('nan')
    if problem=='basis': b['basis'][0][0]=-1
    if problem=='missing': b['frames'][1]['arm']=None
    if problem=='degenerate': b['frames'][1]['arm'][1]=b['frames'][1]['arm'][0]
    with pytest.raises(ValueError): prepare_spatial(b)


def test_spatial_contact_changes_motion():
    b=bundle()
    for f in b['frames']:
        a=.8*f['t']/3
        q=[np.cos(a/2),0,0,np.sin(a/2),.1]
        e,h=points(q);f['arm']=[[0,1.4,0],e,h]
    m=prepare_spatial(b)
    free=run_spatial(Edit(duration=3,obstacle=False),m)
    blocked=run_spatial(Edit(duration=3,obstacle=True),m)
    assert blocked['metrics']['contact_steps']>0
    assert blocked['metrics']['tracking_rmse_deg']>free['metrics']['tracking_rmse_deg']
    assert any(f['contact_forces_local'] for f in blocked['frames'])
    assert np.max(np.abs(np.array([f['hand'] for f in free['frames']])-[f['hand'] for f in blocked['frames']]))>.01
