"""SAM directions -> supported spatial arm -> bounded torque simulation.

Shoulder twist is a bend-plane convention, not observed anatomical twist.
"""
import hashlib
import json
from dataclasses import dataclass, asdict, replace
import numpy as np
import mujoco
import time


def matrix(q):
    out = np.zeros(9)
    mujoco.mju_quat2Mat(out, np.asarray(q, dtype=float))
    return out.reshape(3, 3)


def points(q):
    r = matrix(q[:4]); e = np.array([0., 1.4, 0.]) + r @ [.34, 0, 0]
    h = e + r @ [.29*np.cos(q[4]), .29*np.sin(q[4]), 0]
    return e.tolist(), h.tolist()


@dataclass
class SpatialMotion:
    times: np.ndarray
    poses: np.ndarray
    metadata: dict
    timeline: object = None

    def target(self, t, duration):
        t = np.clip(t/duration, 0, 1)*self.times[-1]
        pose=self.timeline.sample(t)
        shoulder,elbow=pose['rotations_wxyz']
        return np.r_[shoulder,2*np.arctan2(elbow[3],elbow[0])]



def prepare_spatial(bundle):
    if bundle.get('schema') != 'homunculus.observations.v1':
        raise ValueError('Expected observations v1')
    provenance = bundle.get('provenance', {})
    if provenance.get('kind') not in ('sam3d', 'synthetic_test') or any(not isinstance(provenance.get(k), str) or not provenance[k] for k in ('model','revision','video_sha256')):
        raise ValueError('Missing capture provenance')
    frames = bundle.get('frames', [])
    if not 3 <= len(frames) <= 601: raise ValueError('Require 3–601 frames')
    basis = np.asarray(bundle.get('basis'), dtype=float)
    if basis.shape != (3,3) or not np.isfinite(basis).all() or not np.allclose(basis@basis.T,np.eye(3),atol=1e-5) or not np.isclose(np.linalg.det(basis),1):
        raise ValueError('Invalid coordinate basis')
    times = np.array([f['t'] for f in frames], dtype=float); times -= times[0]
    if not np.isfinite(times).all() or np.any(np.diff(times)<=0) or np.max(np.diff(times))>.251 or not 2 <= times[-1] <= 30:
        raise ValueError('Require ordered 2–30 second capture with gaps <=250 ms')
    poses=[]; singular=0
    for f in frames:
        p=np.asarray(f.get('arm'),dtype=float)
        if p.shape != (3,3) or not np.isfinite(p).all(): raise ValueError('Spatial capture requires finite poses; trim missing estimates')
        v=np.diff(p,axis=0)@basis.T; lengths=np.linalg.norm(v,axis=1)
        if np.min(lengths)<1e-6: raise ValueError('Degenerate segment')
        x, fore=v/lengths[:,None]; bend=np.arccos(np.clip(x@fore,-1,1))
        y=fore-x*(x@fore)
        if np.linalg.norm(y)<.08:
            singular+=1
            previous=matrix(poses[-1][:4])[:,1] if poses else np.eye(3)[np.argmin(np.abs(x))]
            y=previous-x*(previous@x)
            if np.linalg.norm(y)<1e-6: y=np.cross(x,np.eye(3)[np.argmin(np.abs(x))])
        y/=np.linalg.norm(y); z=np.cross(x,y)
        q=np.zeros(4); mujoco.mju_mat2Quat(q,np.column_stack((x,y,z)).ravel())
        if poses and q@poses[-1][:4]<0: q=-q
        poses.append(np.r_[q,bend])
    poses=np.array(poses)
    delta=2*np.arccos(np.clip(np.abs(np.sum(poses[1:,:4]*poses[:-1,:4],axis=1)),0,1))
    speed=np.maximum(delta,np.abs(np.diff(poses[:,4])))/np.diff(times)
    if np.max(speed)>np.radians(720): raise ValueError('Pose discontinuity exceeds 720 deg/s; inspect source')
    raw=poses.copy()
    for i,t in enumerate(times[1:-1],1):
        neighbors=raw[np.abs(times-t)<=.09].copy()
        neighbors[neighbors[:,:4]@raw[i,:4]<0,:4]*=-1
        poses[i]=neighbors.mean(axis=0); poses[i,:4]/=np.linalg.norm(poses[i,:4])
    motion = SpatialMotion(times,poses,{'provenance':provenance,'source_duration_s':float(times[-1]),
        'bundle_sha256':hashlib.sha256(json.dumps(bundle,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'mapping':'spatial_arm_v1; fixed shoulder, normalized lengths, bend-plane twist convention',
        'smoothing':'90 ms quaternion hemisphere mean, normalized; endpoints preserved',
        'near_straight_frames':singular,'missing_frames':0,'max_angular_speed_deg_s':float(np.degrees(max(speed))),
        'inference':'SAM_RECONSTRUCTION_UNVERIFIED_ACCURACY' if provenance['kind']=='sam3d' else 'NOT_RUN_SYNTHETIC_TEST'})
    from timeline import Timeline, from_spatial
    motion.timeline=Timeline(bundle['reference_animation']) if 'reference_animation' in bundle else from_spatial(times,poses,motion.metadata)
    for pose in motion.timeline.document['poses'].values():
        if not np.allclose(pose['rootPosition'],[0,1.4,0]): raise ValueError('Supported-arm physics requires the fixed shoulder root; root motion is preview-only')
        elbow=np.array(pose['rotations_wxyz'][1])
        if np.linalg.norm(elbow[1:3])>1e-6 or not -.1<=2*np.arctan2(elbow[3],elbow[0])<=3.14: raise ValueError('Elbow pose exceeds rig hinge limits')
    motion.times=motion.timeline.times
    motion.metadata['source_duration_s']=float(motion.times[-1])
    return motion



def run_spatial(edit, motion):
    obstacle='<geom type="box" pos=".47 1.65 0" size=".075 .12 .16"/>' if edit.obstacle else ''
    model=mujoco.MjModel.from_xml_string(f'''<mujoco><compiler angle="radian"/><option timestep=".002" gravity="0 -9.81 0" integrator="implicitfast"/>
    <default><joint damping=".1" armature=".02"/></default><worldbody>{obstacle}
    <body pos="0 1.4 0"><joint type="ball"/><geom type="capsule" fromto="0 0 0 .34 0 0" size=".045" mass="1.4"/>
    <body pos=".34 0 0"><joint type="hinge" axis="0 0 1" range="-.1 3.14"/><geom type="capsule" fromto="0 0 0 .29 0 0" size=".035" mass=".9"/></body>
    </body></worldbody></mujoco>''')
    data=mujoco.MjData(model); data.qpos[:]=motion.target(0,edit.duration); mujoco.mj_forward(model,data)
    if data.ncon: raise ValueError('Initial pose overlaps obstacle')
    started=time.perf_counter(); frames=[]; errors=[]; torques=[]; velocities=[]; saturated=contacts=0; penetration=0.; limit=np.array([35,35,35,20])
    steps=round(edit.duration/.002)
    for i in range(steps+1):
        target=motion.target(data.time,edit.duration); error=np.zeros(4)
        mujoco.mj_differentiatePos(model,error,1.,data.qpos,target)
        desired=90*edit.strength*error-8*edit.damping*data.qvel+data.qfrc_bias
        torque=np.clip(desired,-limit,limit)
        errors.append(error.copy()); torques.append(torque.copy()); velocities.append(data.qvel.copy())
        saturated+=int(np.any(np.abs(desired)>limit)); contacts+=int(data.ncon>0)
        forces=[]
        for j,c in enumerate(data.contact):
            penetration=max(penetration,-float(c.dist)); force=np.zeros(6); mujoco.mj_contactForce(model,data,j,force); forces.append(force.tolist())
        if i%10==0 or i==steps:
            elbow,hand=points(data.qpos); te,th=points(target)
            frames.append({'t':float(data.time),'q':data.qpos.tolist(),'target':target.tolist(),'elbow':elbow,'hand':hand,
                'target_elbow':te,'target_hand':th,'qvel':data.qvel.tolist(),'torque_Nm':torque.tolist(),'commanded_torque_Nm':desired.tolist(),'previous_applied_torque_Nm':data.qfrc_applied.tolist(),'error_rad':error.tolist(),
                'root_position':[0,1.4,0],'root_velocity':[0,0,0],'center_of_mass':data.subtree_com[1].tolist(),
                'elbow_limit_violation_rad':max(0.,-.1-float(data.qpos[4]),float(data.qpos[4])-3.14),
                'contacts':int(data.ncon),'contact_forces_local':forces,
                'local_rotations_xyzw':[data.qpos[[1,2,3,0]].tolist(),[0,0,float(np.sin(data.qpos[4]/2)),float(np.cos(data.qpos[4]/2))]]})
        if i<steps:
            data.qfrc_applied[:]=torque; mujoco.mj_step(model,data); mujoco.mj_forward(model,data)
        if not np.isfinite(data.qpos).all() or any(w.number for w in data.warning): raise RuntimeError('Invalid spatial simulation')
    return {'schema':1,'rig':'spatial_arm_v1','source':'SAM observations' if motion.metadata['provenance']['kind']=='sam3d' else 'synthetic test',
        'inference':motion.metadata['inference'],'capture':motion.metadata,'assistance':'fixed world shoulder; no full-body balance',
        'coordinates':'RH +Y up, metres, seconds; shoulder quaternion wxyz + elbow radians','edit':asdict(edit),'frames':frames,
        'metrics':{'tracking_rmse_deg':float(np.degrees(np.sqrt(np.mean(np.square(errors))))),'contact_steps':contacts,
        'max_penetration_m':penetration,'saturated_fraction':saturated/(steps+1),'peak_torque_Nm':np.max(np.abs(torques),axis=0).tolist(),
        'mean_squared_torque':float(np.mean(np.square(torques))),'peak_speed_rad_s':float(np.max(np.abs(velocities))),
        'simulation_wall_s':time.perf_counter()-started,'steps':steps,'timestep_s':.002,'mujoco':mujoco.__version__}}


def synthesize(motion, edit):
    """Bounded, same-clip parameter search; not learned/generalized control."""
    results=[run_spatial(replace(edit,strength=s,damping=d),motion) for s,d in [(1,1),(.7,.7),(1.4,.7),(1.8,1),(1.4,1.4)]]
    def score(r):
        m=r['metrics']; return m['tracking_rmse_deg']+10*m['saturated_fraction']+.002*m['mean_squared_torque']+1000*m['max_penetration_m']
    selected=min(range(len(results)),key=lambda i:score(results[i]))
    return results[selected], {'method':'5 candidate same-clip PD gain search; no generalization claim','selected':selected,
        'objective':'RMSE degrees + 10*saturation + .002*mean squared torque + 1000*penetration metres',
        'candidates':[{'edit':r['edit'],'metrics':r['metrics'],'score':score(r)} for r in results]}
