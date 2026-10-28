"""Bounded joint-local edits of captured references; original observations retained."""
import copy
import numpy as np
from commands import validate_command
from spatial import prepare_spatial
from timeline import Timeline


def adjust(capture, arguments):
    validate_command('adjust_pose', arguments)
    if arguments['joint']=='elbow' and arguments['axis']!='z': raise ValueError('Elbow uses its local Z hinge axis')
    document=copy.deepcopy(prepare_spatial(capture).timeline.document)
    matches=[k for k in document['keyframes'] if k['id']==arguments['keyId']]
    if len(matches)!=1: raise ValueError('Unknown pose key ID')
    key=matches[0]; pose=copy.deepcopy(document['poses'][key['poseId']])
    joint=0 if arguments['joint']=='shoulder' else 1
    half=np.radians(arguments['degrees'])/2; delta=np.zeros(4);delta[0]=np.cos(half);delta[1+'xyz'.index(arguments['axis'])]=np.sin(half)
    a=np.array(pose['rotations_wxyz'][joint]);b=delta
    q=np.r_[a[0]*b[0]-a[1:]@b[1:],a[0]*b[1:]+b[0]*a[1:]+np.cross(a[1:],b[1:])]
    pose['rotations_wxyz'][joint]=(q/np.linalg.norm(q)).tolist()
    # Copy on write: duplicated hold poses must not modify other keys implicitly.
    pid='edited-'+key['id'];pose['id']=pid;document['poses'][pid]=pose;key['poseId']=pid
    timeline=Timeline(document);timeline.validate_motion()
    result=copy.deepcopy(capture);result['reference_animation']=timeline.document
    prepare_spatial(result)
    return result
