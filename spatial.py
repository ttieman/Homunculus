"""SAM directions -> supported spatial arm -> bounded torque simulation.

Shoulder twist is a bend-plane convention, not observed anatomical twist.
"""
import hashlib
import json
from dataclasses import dataclass, asdict, replace
import numpy as np
import mujoco
import time
from contracts import MAX_FRAMES, object_value


def matrix(q):
    out = np.zeros(9)
    mujoco.mju_quat2Mat(out, np.asarray(q, dtype=float))
    return out.reshape(3, 3)


def hinge_angle(q):
    # q and -q represent the same rotation; wrap the hinge coordinate.
    return float((2*np.arctan2(q[3],q[0])+np.pi)%(2*np.pi)-np.pi)


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
        return np.r_[shoulder,hinge_angle(elbow)]



def prepare_spatial(bundle):
    object_value(bundle,'capture')
    if bundle.get('schema') != 'homunculus.observations.v1':
        raise ValueError('Expected observations v1')
    provenance = object_value(bundle.get('provenance', {}),'capture.provenance')
    if provenance.get('kind') not in ('sam3d', 'synthetic_test') or any(not isinstance(provenance.get(k), str) or not provenance[k] for k in ('model','revision','video_sha256')):
        raise ValueError('Missing capture provenance')
    frames = bundle.get('frames', [])
    if not isinstance(frames,list) or not 3 <= len(frames) <= MAX_FRAMES: raise ValueError(f'Require 3–{MAX_FRAMES} frames')
    for i,f in enumerate(frames): object_value(f,f'capture.frames[{i}]')
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
    # Full-body captures keep fast raw arm steps as a warning; the smoothed reference below still enforces 720 deg/s.
    jumps=[round(float(times[i+1]),3) for i in np.flatnonzero(speed>np.radians(720))]
    if jumps and 'body_keypoints' not in bundle: raise ValueError('Pose discontinuity exceeds 720 deg/s; inspect source')
    raw=poses.copy()
    for i,t in enumerate(times[1:-1],1):
        neighbors=raw[np.abs(times-t)<=.09].copy()
        neighbors[neighbors[:,:4]@raw[i,:4]<0,:4]*=-1
        poses[i]=neighbors.mean(axis=0); poses[i,:4]/=np.linalg.norm(poses[i,:4])
    motion = SpatialMotion(times,poses,{'provenance':provenance,'source_duration_s':float(times[-1]),
        'bundle_sha256':hashlib.sha256(json.dumps(bundle,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'mapping':'spatial_arm_v1; fixed shoulder, normalized lengths, bend-plane twist convention',
        'smoothing':'90 ms quaternion hemisphere mean, normalized; endpoints preserved',
        'near_straight_frames':singular,'missing_frames':0,'raw_arm_jumps_over_720_deg_s_at':jumps,'max_angular_speed_deg_s':float(np.degrees(max(speed))),
        'inference':'SAM_RECONSTRUCTION_UNVERIFIED_ACCURACY' if provenance['kind']=='sam3d' else 'NOT_RUN_SYNTHETIC_TEST'})
    from quality import capture_quality
    motion.metadata['capture_quality']=capture_quality(bundle)
    from timeline import Timeline, from_spatial
    motion.timeline=Timeline(bundle['reference_animation']) if 'reference_animation' in bundle else from_spatial(times,poses,motion.metadata)
    for pose in motion.timeline.document['poses'].values():
        if not np.allclose(pose['rootPosition'],[0,1.4,0]): raise ValueError('Supported-arm physics requires the fixed shoulder root; root motion is preview-only')
        elbow=np.array(pose['rotations_wxyz'][1])
        if np.linalg.norm(elbow[1:3])>1e-6 or not -.1<=hinge_angle(elbow)<=3.14: raise ValueError('Elbow pose exceeds rig hinge limits')
    motion.times=motion.timeline.times
    motion.metadata['capture_max_angular_speed_deg_s']=motion.metadata.pop('max_angular_speed_deg_s')
    motion.metadata['reference_diagnostics']=motion.timeline.validate_motion()
    motion.metadata['source_duration_s']=float(motion.times[-1])
    return motion



def run_spatial(edit, motion, physics=None, disturbance=None):
    motion.timeline.validate_motion(edit.duration)
    obstacle='<geom type="box" pos=".47 1.65 0" size=".075 .12 .16"/>' if edit.obstacle else ''
    xml=f'''<mujoco><compiler angle="radian"/><option timestep=".002" gravity="0 -9.81 0" integrator="implicitfast"/>
    <default><joint damping=".1" armature=".02"/></default><worldbody>{obstacle}
    <body pos="0 1.4 0"><joint type="ball"/><geom type="capsule" fromto="0 0 0 .34 0 0" size=".045" mass="1.4"/>
    <body pos=".34 0 0"><joint type="hinge" axis="0 0 1" range="-.1 3.14"/><geom type="capsule" fromto="0 0 0 .29 0 0" size=".035" mass=".9"/></body>
    </body></worldbody></mujoco>'''
    default_physics={'schema':'homunculus.physics.v1','xml':xml,'engine':'MuJoCo '+mujoco.__version__,
        'rig':'spatial_arm_v1','torque_limits_Nm':[35,35,35,20],'stiffness_base':90,'damping_base':8,
        'lengths_m':[.34,.29],'root_position':[0,1.4,0],
        'feasibility_limits':{'max_joint_limit_violation_rad':.01,'max_penetration_m':.005}}
    physics=default_physics if physics is None else physics
    if physics.get('schema')!='homunculus.physics.v1' or physics.get('rig')!='spatial_arm_v1' or physics.get('engine')!='MuJoCo '+mujoco.__version__: raise ValueError('Incompatible physical asset configuration')
    if physics['lengths_m']!=[.34,.29] or physics['root_position']!=[0,1.4,0]: raise ValueError('Unsupported asset rig proportions')
    model=mujoco.MjModel.from_xml_string(physics['xml'])
    if model.nq!=5 or model.nv!=4: raise ValueError('Asset must contain the supported arm')
    data=mujoco.MjData(model); data.qpos[:]=motion.target(0,edit.duration); mujoco.mj_forward(model,data)
    if data.ncon: raise ValueError('Initial pose overlaps obstacle')
    started=time.perf_counter(); frames=[]; errors=[]; torques=[]; velocities=[]; saturated=contacts=0; penetration=0.; limit=np.array(physics['torque_limits_Nm'],dtype=float)
    if limit.shape!=(4,) or not np.isfinite(limit).all() or np.any(limit<=0): raise ValueError('Invalid asset torque limits')
    peak_limit_violation=0.; effort=0.; peak_contact_force=0.
    steps=round(edit.duration/model.opt.timestep)
    impulse_step=-1;impulse=np.zeros(4)
    if disturbance is not None:
        object_value(disturbance,'disturbance')
        impulse=np.asarray(disturbance.get('joint_impulse_Nms'),dtype=float)
        when=disturbance.get('time_s')
        if impulse.shape!=(4,) or not np.isfinite(impulse).all() or np.max(np.abs(impulse))>1 or not isinstance(when,(int,float)) or not 0<=when<edit.duration: raise ValueError('Disturbance requires time within clip and four bounded joint impulses (<=1 Nms)')
        impulse_step=round(when/model.opt.timestep)
    for i in range(steps+1):
        target=motion.target(data.time,edit.duration); error=np.zeros(4)
        mujoco.mj_differentiatePos(model,error,1.,data.qpos,target)
        desired=physics['stiffness_base']*edit.strength*error-physics['damping_base']*edit.damping*data.qvel+data.qfrc_bias
        torque=np.clip(desired,-limit,limit)
        external=impulse/model.opt.timestep if i==impulse_step else np.zeros(4)
        errors.append(error.copy()); torques.append(torque.copy()); velocities.append(data.qvel.copy())
        violation=max(0.,-.1-float(data.qpos[4]),float(data.qpos[4])-3.14)
        peak_limit_violation=max(peak_limit_violation,violation)
        if i<steps: effort+=float(torque@torque)*model.opt.timestep
        saturated+=int(np.any(np.abs(desired)>limit)); contacts+=int(data.ncon>0)
        forces=[];contact_records=[]
        for j,c in enumerate(data.contact):
            penetration=max(penetration,-float(c.dist)); force=np.zeros(6); mujoco.mj_contactForce(model,data,j,force); forces.append(force.tolist())
            peak_contact_force=max(peak_contact_force,float(np.linalg.norm(force[:3])))
            contact_records.append({'geom_ids':[int(c.geom1),int(c.geom2)],'position_m':c.pos.tolist(),'contact_frame_rows':c.frame.reshape(3,3).tolist(),'wrench_local_N_Nm':force.tolist(),'distance_m':float(c.dist)})
        if i%10==0 or i==steps:
            elbow=data.xpos[2].tolist();hand=(data.xpos[2]+data.xmat[2].reshape(3,3)@[.29,0,0]).tolist(); te,th=points(target)
            frames.append({'t':float(data.time),'q':data.qpos.tolist(),'target':target.tolist(),'elbow':elbow,'hand':hand,
                'target_elbow':te,'target_hand':th,'qvel':data.qvel.tolist(),'external_torque_Nm':external.tolist(),'torque_Nm':torque.tolist(),'commanded_torque_Nm':desired.tolist(),'previous_applied_torque_Nm':data.qfrc_applied.tolist(),'error_rad':error.tolist(),
                'root_position':[0,1.4,0],'root_velocity':[0,0,0],'center_of_mass':data.subtree_com[1].tolist(),
                'elbow_limit_violation_rad':max(0.,-.1-float(data.qpos[4]),float(data.qpos[4])-3.14),
                'contacts':int(data.ncon),'contact_forces_local':forces,'contact_events':contact_records,
                'local_rotations_xyzw':[data.qpos[[1,2,3,0]].tolist(),[0,0,float(np.sin(data.qpos[4]/2)),float(np.cos(data.qpos[4]/2))]]})
        if i<steps:
            data.qfrc_applied[:]=torque+external; mujoco.mj_step(model,data); mujoco.mj_forward(model,data)
        if not np.isfinite(data.qpos).all() or any(w.number for w in data.warning): raise RuntimeError('Invalid spatial simulation')
    return {'schema':1,'rig':'spatial_arm_v1','source':'SAM observations' if motion.metadata['provenance']['kind']=='sam3d' else 'synthetic test',
        'inference':motion.metadata['inference'],'capture':motion.metadata,'assistance':'fixed world shoulder; no full-body balance',
        'disturbance':disturbance,'physics_configuration':physics,'physics_sha256':hashlib.sha256(json.dumps(physics,sort_keys=True,allow_nan=False).encode()).hexdigest(),
        'feasibility':{'passed':peak_limit_violation<=physics['feasibility_limits']['max_joint_limit_violation_rad'] and penetration<=physics['feasibility_limits']['max_penetration_m'],'criteria':physics['feasibility_limits'],'balance':'not applicable: fixed root','foot_contact':'not applicable: no feet'},
        'coordinates':'RH +Y up, metres, seconds; shoulder quaternion wxyz + elbow radians','edit':asdict(edit),'frames':frames,
        'metrics':{'tracking_rmse_deg':float(np.degrees(np.sqrt(np.mean(np.square(errors))))),'contact_steps':contacts,
        'max_penetration_m':penetration,'saturated_fraction':saturated/(steps+1),'peak_torque_Nm':np.max(np.abs(torques),axis=0).tolist(),
        'motor_effort_Nm2_s':effort,'peak_joint_limit_violation_rad':peak_limit_violation,'peak_contact_force_N':peak_contact_force,
        'mean_squared_torque':float(np.mean(np.square(torques))),'peak_speed_rad_s':float(np.max(np.abs(velocities))),
        'simulation_wall_s':time.perf_counter()-started,'steps':steps,'timestep_s':float(model.opt.timestep),'mujoco':mujoco.__version__}}


def synthesize(motion, edit):
    """Bounded, same-clip parameter search; not learned/generalized control."""
    settings=list(dict.fromkeys([(edit.strength,edit.damping),(1,1),(.7,.7),(1.4,.7),(1.8,1),(1.4,1.4)]))
    results=[run_spatial(replace(edit,strength=s,damping=d),motion) for s,d in settings]
    def score(r):
        m=r['metrics']; return m['tracking_rmse_deg']+10*m['saturated_fraction']+.002*m['mean_squared_torque']+1000*m['max_penetration_m']
    feasible=[i for i,r in enumerate(results) if r['feasibility']['passed']]
    selected=min(feasible,key=lambda i:score(results[i])) if feasible else 0
    # Never replace a current configuration with a worse scalar objective.
    if score(results[selected])>score(results[0]): selected=0
    return results[selected], {'method':'same-clip PD gain search including current settings; no generalization claim','selected':selected,
        'status':'feasible' if results[selected]['feasibility']['passed'] else 'no_acceptable_improvement',
        'current_candidate':0,'current_score':score(results[0]),'selected_score':score(results[selected]),
        'objective':'RMSE degrees + 10*saturation + .002*mean squared torque + 1000*penetration metres',
        'candidates':[{'edit':r['edit'],'metrics':r['metrics'],'feasibility':r['feasibility'],'score':score(r)} for r in results]}
