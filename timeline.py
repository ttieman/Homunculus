"""Deterministic local-quaternion animation, separate from capture and physics."""
import copy
import numpy as np
from contracts import MAX_FRAMES, number, object_value

SKELETON = 'homunculus.supported-arm.v1'


def slerp(a,b,u):
    a=np.asarray(a,dtype=float); b=np.asarray(b,dtype=float)
    a=a/np.linalg.norm(a); b=b/np.linalg.norm(b)
    dot=float(a@b)
    if dot<0: b=-b; dot=-dot
    if dot>.9995:
        q=(1-u)*a+u*b
        return q/np.linalg.norm(q)
    angle=np.arccos(np.clip(dot,-1,1))
    return (np.sin((1-u)*angle)*a+np.sin(u*angle)*b)/np.sin(angle)


class Timeline:
    def __init__(self,document):
        object_value(document,'reference')
        self.document=copy.deepcopy(document)
        if document.get('schema')!='homunculus.reference.v1' or document.get('skeletonId')!=SKELETON:
            raise ValueError('Unsupported reference schema or mismatched skeleton')
        poses=document.get('poses'); keys=document.get('keyframes')
        if not isinstance(poses,dict) or not isinstance(keys,list) or not 3<=len(keys)<=MAX_FRAMES:
            raise ValueError(f'Reference requires a pose library and 3–{MAX_FRAMES} keys')
        ids=[]; times=[]
        for key in keys:
            object_value(key,'keyframe')
            if not isinstance(key.get('id'),str) or not key['id']: raise ValueError('Keyframe ID must be a nonempty string')
            if not isinstance(key.get('poseId'),str): raise ValueError('poseId must be a string')
            ids.append(key['id']); times.append(number(key['time'],'keyframe.time'))
            if key.get('interpolation') not in ('linear','smoothstep','hold') or key.get('poseId') not in poses:
                raise ValueError('Invalid key interpolation or pose reference')
        self.times=np.asarray(times,dtype=float)
        if len(set(ids))!=len(ids) or not np.isfinite(self.times).all() or self.times[0]!=0 or np.any(np.diff(self.times)<=0) or not 2<=self.times[-1]<=30:
            raise ValueError('Key IDs must be unique, times ordered from zero, duration 2–30 s')
        for pose in poses.values():
            object_value(pose,'pose')
            root=np.asarray(pose.get('rootPosition'),dtype=float); q=np.asarray(pose.get('rotations_wxyz'),dtype=float)
            if root.shape!=(3,) or q.shape!=(2,4) or not np.isfinite(root).all() or not np.isfinite(q).all() or not np.allclose(np.linalg.norm(q,axis=1),1,atol=1e-5):
                raise ValueError('Pose requires finite root and two normalized local quaternions')
            if pose.get('skeletonId')!=SKELETON: raise ValueError('Mismatched pose skeleton')

    def validate_motion(self, duration=None, limit_deg_s=720):
        scale=(self.times[-1]/duration) if duration is not None else 1.
        peaks=[]
        keys=self.document['keyframes']; library=self.document['poses']
        for i,(a,b) in enumerate(zip(keys,keys[1:])):
            qa=np.array(library[a['poseId']]['rotations_wxyz']); qb=np.array(library[b['poseId']]['rotations_wxyz'])
            distance=2*np.arccos(np.clip(np.abs(np.sum(qa*qb,axis=1)),0,1))
            if a['interpolation']=='hold' and np.max(distance)>1e-6:
                raise ValueError('Hold boundary changes pose discontinuously; duplicate the held pose then add a transition')
            multiplier=1.5 if a['interpolation']=='smoothstep' else 1.
            peaks.append(float(np.degrees(max(distance))/(self.times[i+1]-self.times[i])*multiplier*scale))
        peak=max(peaks)
        if peak>limit_deg_s: raise ValueError(f'Edited reference exceeds {limit_deg_s} degrees/second ({peak:.1f})')
        return {'max_angular_speed_deg_s':peak,'evaluated_duration_s':float(duration or self.times[-1])}

    def sample(self,t):
        if not np.isfinite(t): raise ValueError('Nonfinite sample time')
        t=float(np.clip(t,0,self.times[-1])); i=min(max(np.searchsorted(self.times,t,side='right')-1,0),len(self.times)-2)
        keys=self.document['keyframes']; a=self.document['poses'][keys[i]['poseId']]; b=self.document['poses'][keys[i+1]['poseId']]
        u=(t-self.times[i])/(self.times[i+1]-self.times[i]); mode=keys[i]['interpolation']
        if mode=='smoothstep': u=u*u*(3-2*u)
        elif mode=='hold': u=float(u>=1)
        return {'rootPosition':((1-u)*np.array(a['rootPosition'])+u*np.array(b['rootPosition'])).tolist(),
                'rotations_wxyz':[slerp(x,y,u).tolist() for x,y in zip(a['rotations_wxyz'],b['rotations_wxyz'])]}

    def edited(self,commands):
        if not isinstance(commands,list) or not 1<=len(commands)<=50: raise ValueError('Require 1–50 structured operations')
        doc=copy.deepcopy(self.document)
        for cmd in commands:
            object_value(cmd,'command')
            object_value(cmd.get('parameters'),'command.parameters')
            if set(cmd)-{'operation','targetId','parameters'}: raise ValueError('Unknown command fields')
            op=cmd['operation']; params=cmd['parameters']
            if op=='set_duration':
                if set(params)!={'seconds'}: raise ValueError('Expected seconds')
                scale=number(params['seconds'],'seconds')/doc['keyframes'][-1]['time']
                for k in doc['keyframes']: k['time']*=scale
            elif op in ('move_keyframe','set_interpolation'):
                matches=[k for k in doc['keyframes'] if k['id']==cmd.get('targetId')]
                if len(matches)!=1: raise ValueError('Unknown keyframe ID')
                field='time' if op=='move_keyframe' else 'interpolation'
                if set(params)!={field}: raise ValueError('Unexpected command parameters')
                matches[0][field]=params[field]
            else: raise ValueError('Unsupported animation operation')
        return Timeline(doc)


def from_spatial(times,poses,metadata):
    library={}; keys=[]
    for i,(t,q) in enumerate(zip(times,poses)):
        pid=f'pose-{i}'
        library[pid]={'id':pid,'skeletonId':SKELETON,'rootPosition':[0,1.4,0],
            'rotations_wxyz':[q[:4].tolist(),[float(np.cos(q[4]/2)),0,0,float(np.sin(q[4]/2))]]}
        keys.append({'id':f'key-{i}','time':float(t),'sourceTime':float(t),'poseId':pid,'interpolation':'linear'})
    return Timeline({'schema':'homunculus.reference.v1','skeletonId':SKELETON,'poses':library,'keyframes':keys,'metadata':metadata})
