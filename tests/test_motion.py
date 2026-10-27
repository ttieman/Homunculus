import copy
import json
import numpy as np
import pytest
from motion import prepare
from puppet import Edit, run
from exporter import export_gltf, replay_gltf


def sample_bundle():
    frames=[]
    for t in np.linspace(0,4,61):
        a=-.7+.9*np.sin(t*np.pi/4)**2
        b=-.4*np.sin(t*np.pi/4)**2
        shoulder=np.array([1+t*.03,2,3])
        elbow=shoulder+2*np.array([np.cos(a),np.sin(a),0])
        wrist=elbow+1.5*np.array([np.cos(a+b),np.sin(a+b),0])
        frames.append({'t':float(t),'arm':[shoulder.tolist(),elbow.tolist(),wrist.tolist()]})
    return {'schema':'homunculus.observations.v1','basis':np.eye(3).tolist(),'frames':frames,
        'provenance':{'kind':'synthetic_test','model':'analytical arm fixture, no inference',
                      'revision':'1','video_sha256':'not-a-real-video'}}


def test_mapping_discards_translation_and_scale():
    bundle=sample_bundle();motion=prepare(bundle)
    assert np.allclose(motion.angles[0],[-.7,0],atol=1e-12)
    assert np.allclose(motion.angles[30],[.2,-.4],atol=1e-12)
    assert np.allclose(motion.target(3,6),motion.angles[30])
    changed=copy.deepcopy(bundle)
    for f in changed['frames']: f['arm']=(np.array(f['arm'])*.04+12).tolist()
    assert np.allclose(prepare(changed).angles,motion.angles)


def test_basis_conversion():
    bundle=sample_bundle();basis=np.diag([1,-1,-1])
    for f in bundle['frames']: f['arm']=(np.array(f['arm'])@basis).tolist()
    bundle['basis']=basis.tolist()
    assert np.allclose(prepare(bundle).angles,prepare(sample_bundle()).angles)


def test_missing_short_gap_is_explicit():
    bundle=sample_bundle();bundle['frames'][10]['arm']=None
    assert prepare(bundle).metadata['missing_frames']==1
    for i in range(10,15): bundle['frames'][i]['arm']=None
    with pytest.raises(ValueError,match='gap'): prepare(bundle)


@pytest.mark.parametrize('fault',['plane','nan','time','reflection','endpoint','degenerate','limits','jump'])
def test_bad_observations_rejected(fault):
    b=sample_bundle()
    if fault=='plane': b['frames'][20]['arm'][2][2]+=10
    if fault=='nan': b['frames'][20]['arm'][2][0]=float('nan')
    if fault=='time': b['frames'][20]['t']=b['frames'][19]['t']
    if fault=='reflection': b['basis'][2][2]=-1
    if fault=='endpoint': b['frames'][0]['arm']=None
    if fault=='degenerate': b['frames'][20]['arm'][2]=b['frames'][20]['arm'][1]
    if fault=='limits':
        for f in b['frames']: f['arm']=[[0,0,0],[-1,.01,0],[-2,.02,0]]
    if fault=='jump': b['frames'][20]['arm']=[[0,0,0],[0,1,0],[0,2,0]]
    with pytest.raises(ValueError): prepare(b)


def test_capture_drives_physics_and_export():
    bundle=sample_bundle();motion=prepare(bundle)
    result=run(Edit(duration=6,obstacle=False),motion)
    assert result['frames'][0]['q']==pytest.approx([-.7,0])
    assert result['inference']=='NOT_RUN_SYNTHETIC_TEST'
    assert result['frames'][150]['target']==pytest.approx([.2,-.4])
    assert result['metrics']['tracking_rmse_deg']<5
    gltf=export_gltf(result)
    assert gltf['extras']['capture']['bundle_sha256']==motion.metadata['bundle_sha256']
    assert np.max(np.abs(np.array(replay_gltf(gltf))-np.array([f['hand'] for f in result['frames']])))<1e-6
    again=run(Edit(duration=6,obstacle=False),motion)
    assert again['frames']==result['frames']


def test_imported_sam_label_is_not_a_local_inference_claim():
    b=sample_bundle();b['provenance']['kind']='sam3d'
    assert prepare(b).metadata['inference']=='IMPORTED_UNVERIFIED'


def test_captured_trajectory_is_blocked_by_real_contact():
    b=sample_bundle()
    for f in b['frames']:
        a=.8*np.sin(f['t']*np.pi/4)**2
        elbow=np.array([np.cos(a),np.sin(a),0])
        f['arm']=[[0,0,0],elbow.tolist(),(2*elbow).tolist()]
    motion=prepare(b)
    clean=run(Edit(obstacle=False),motion)
    blocked=run(Edit(),motion)
    assert clean['metrics']['contact_steps']==0
    assert blocked['metrics']['contact_steps']>100
    assert blocked['metrics']['tracking_rmse_deg']>clean['metrics']['tracking_rmse_deg']+5
    assert blocked['metrics']['max_penetration_m']<.005


def test_initial_obstacle_overlap_rejected():
    b=sample_bundle()
    arm=[[0,0,0],[np.cos(.4),np.sin(.4),0],[2*np.cos(.4),2*np.sin(.4),0]]
    for f in b['frames']: f['arm']=arm
    with pytest.raises(ValueError,match='starting pose overlaps'):
        run(Edit(),prepare(b))
