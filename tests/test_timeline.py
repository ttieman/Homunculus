import copy
import json
import numpy as np
import pytest
from timeline import Timeline, from_spatial, slerp


def reference():
    return from_spatial(np.array([0.,1.,3.]),np.array([[1,0,0,0,.2],[.7071067811865476,0,.7071067811865476,0,.8],[1,0,0,0,.2]]),{})


def test_slerp_shortest_arc_and_constant_angular_speed():
    a=[1,0,0,0]; b=[0,0,0,1]
    q=slerp(a,b,.25)
    assert np.allclose(q,[np.cos(np.pi/8),0,0,np.sin(np.pi/8)])
    assert np.allclose(slerp(a,[-1,0,0,0],.5),a)


def test_root_is_independent_and_serialization_deterministic():
    doc=reference().document; doc['poses']['pose-1']['rootPosition']=[2,2.4,0]
    a=Timeline(doc); b=Timeline(json.loads(json.dumps(doc)))
    assert a.sample(.5)==b.sample(.5)
    assert np.allclose(a.sample(.5)['rootPosition'],[1,1.9,0])
    assert a.sample(-1)==a.sample(0)
    assert a.sample(99)==a.sample(3)


def test_structured_edits_are_atomic_and_change_motion():
    original=reference()
    edited=original.edited([{'operation':'move_keyframe','targetId':'key-1','parameters':{'time':2}}])
    assert original.document['keyframes'][1]['time']==1
    assert edited.sample(.5)!=original.sample(.5)
    with pytest.raises(ValueError): original.edited([{'operation':'move_keyframe','targetId':'key-1','parameters':{'time':4}}])
    with pytest.raises(ValueError): original.edited([{'operation':'execute','parameters':{}}])


@pytest.mark.parametrize('bad',['skeleton','pose_skeleton','quaternion','ordering','pose_reference'])
def test_rejects_invalid_timeline(bad):
    d=reference().document
    if bad=='skeleton':d['skeletonId']='other'
    if bad=='pose_skeleton':d['poses']['pose-0']['skeletonId']='other'
    if bad=='quaternion':d['poses']['pose-0']['rotations_wxyz'][0]=[0,0,0,0]
    if bad=='ordering':d['keyframes'][1]['time']=0
    if bad=='pose_reference':d['keyframes'][1]['poseId']='missing'
    with pytest.raises(ValueError):Timeline(d)
