"""Bounded torque simulation of the supported spatial arm (MuJoCo), plus same-clip gain search."""

import hashlib
import json
import time
from dataclasses import asdict, replace
import numpy as np
import mujoco
from homunculus.animation import segments
from homunculus.animation.timeline import source_time
from homunculus.capture.spatial import matrix
from homunculus.contracts import object_value


def points(q):
    r = matrix(q[:4])
    e = np.array([0.0, 1.4, 0.0]) + r @ [0.34, 0, 0]
    h = e + r @ [0.29 * np.cos(q[4]), 0.29 * np.sin(q[4]), 0]
    return e.tolist(), h.tolist()


def run_spatial(edit, motion, physics=None, disturbance=None):
    motion.timeline.validate_motion(edit.duration)
    obstacle = '<geom type="box" pos=".47 1.65 0" size=".075 .12 .16"/>' if edit.obstacle else ''
    xml = f'''<mujoco><compiler angle="radian"/><option timestep=".002" gravity="0 -9.81 0" integrator="implicitfast"/>
    <default><joint damping=".1" armature=".02"/></default><worldbody>{obstacle}
    <body pos="0 1.4 0"><joint type="ball"/><geom type="capsule" fromto="0 0 0 .34 0 0" size=".045" mass="1.4"/>
    <body pos=".34 0 0"><joint type="hinge" axis="0 0 1" range="-.1 3.14"/><geom type="capsule" fromto="0 0 0 .29 0 0" size=".035" mass=".9"/></body>
    </body></worldbody></mujoco>'''
    default_physics = {
        'schema': 'homunculus.physics.v1',
        'xml': xml,
        'engine': 'MuJoCo ' + mujoco.__version__,
        'rig': 'spatial_arm_v1',
        'torque_limits_Nm': [35, 35, 35, 20],
        'stiffness_base': 90,
        'damping_base': 8,
        'lengths_m': [0.34, 0.29],
        'root_position': [0, 1.4, 0],
        'feasibility_limits': {'max_joint_limit_violation_rad': 0.01, 'max_penetration_m': 0.005},
    }
    physics = default_physics if physics is None else physics
    if (
        physics.get('schema') != 'homunculus.physics.v1'
        or physics.get('rig') != 'spatial_arm_v1'
        or physics.get('engine') != 'MuJoCo ' + mujoco.__version__
    ):
        raise ValueError('Incompatible physical asset configuration')
    if physics['lengths_m'] != [0.34, 0.29] or physics['root_position'] != [0, 1.4, 0]:
        raise ValueError('Unsupported asset rig proportions')
    model = mujoco.MjModel.from_xml_string(physics['xml'])
    if model.nq != 5 or model.nv != 4:
        raise ValueError('Asset must contain the supported arm')
    data = mujoco.MjData(model)
    data.qpos[:] = motion.target(0, edit.duration)
    mujoco.mj_forward(model, data)
    if data.ncon:
        raise ValueError('Initial pose overlaps obstacle')
    started = time.perf_counter()
    frames = []
    errors = []
    torques = []
    velocities = []
    saturated = contacts = 0
    penetration = 0.0
    limit = np.array(physics['torque_limits_Nm'], dtype=float)
    if limit.shape != (4,) or not np.isfinite(limit).all() or np.any(limit <= 0):
        raise ValueError('Invalid asset torque limits')
    peak_limit_violation = 0.0
    effort = 0.0
    peak_contact_force = 0.0
    steps = round(edit.duration / model.opt.timestep)
    impulse_step = -1
    impulse = np.zeros(4)
    if disturbance is not None:
        object_value(disturbance, 'disturbance')
        impulse = np.asarray(disturbance.get('joint_impulse_Nms'), dtype=float)
        when = disturbance.get('time_s')
        if (
            impulse.shape != (4,)
            or not np.isfinite(impulse).all()
            or np.max(np.abs(impulse)) > 1
            or not isinstance(when, (int, float))
            or not 0 <= when < edit.duration
        ):
            raise ValueError(
                'Disturbance requires time within clip and four bounded joint impulses (<=1 Nms)'
            )
        impulse_step = round(when / model.opt.timestep)
    timing = getattr(motion, 'timing', None)
    keys = motion.timeline.document['keyframes']
    for i in range(steps + 1):
        target = motion.target(data.time, edit.duration)
        error = np.zeros(4)
        mujoco.mj_differentiatePos(model, error, 1.0, data.qpos, target)
        # Segment gains are looked up at the source moment this output time shows.
        if timing and timing['segments']:
            s = source_time(keys, edit.duration, data.time)
            strength, damping = segments.gains(
                timing,
                data.time / edit.duration * motion.times[-1] if s is None else s,
                edit.strength,
                edit.damping,
            )
        else:
            strength, damping = edit.strength, edit.damping
        desired = (
            physics['stiffness_base'] * strength * error
            - physics['damping_base'] * damping * data.qvel
            + data.qfrc_bias
        )
        torque = np.clip(desired, -limit, limit)
        external = impulse / model.opt.timestep if i == impulse_step else np.zeros(4)
        errors.append(error.copy())
        torques.append(torque.copy())
        velocities.append(data.qvel.copy())
        violation = max(0.0, -0.1 - float(data.qpos[4]), float(data.qpos[4]) - 3.14)
        peak_limit_violation = max(peak_limit_violation, violation)
        if i < steps:
            effort += float(torque @ torque) * model.opt.timestep
        saturated += int(np.any(np.abs(desired) > limit))
        contacts += int(data.ncon > 0)
        forces = []
        contact_records = []
        for j, c in enumerate(data.contact):
            penetration = max(penetration, -float(c.dist))
            force = np.zeros(6)
            mujoco.mj_contactForce(model, data, j, force)
            forces.append(force.tolist())
            peak_contact_force = max(peak_contact_force, float(np.linalg.norm(force[:3])))
            contact_records.append(
                {
                    'geom_ids': [int(c.geom1), int(c.geom2)],
                    'position_m': c.pos.tolist(),
                    'contact_frame_rows': c.frame.reshape(3, 3).tolist(),
                    'wrench_local_N_Nm': force.tolist(),
                    'distance_m': float(c.dist),
                }
            )
        if i % 10 == 0 or i == steps:
            elbow = data.xpos[2].tolist()
            hand = (data.xpos[2] + data.xmat[2].reshape(3, 3) @ [0.29, 0, 0]).tolist()
            te, th = points(target)
            frames.append(
                {
                    't': float(data.time),
                    'q': data.qpos.tolist(),
                    'target': target.tolist(),
                    'elbow': elbow,
                    'hand': hand,
                    'target_elbow': te,
                    'target_hand': th,
                    'qvel': data.qvel.tolist(),
                    'external_torque_Nm': external.tolist(),
                    'torque_Nm': torque.tolist(),
                    'commanded_torque_Nm': desired.tolist(),
                    'previous_applied_torque_Nm': data.qfrc_applied.tolist(),
                    'error_rad': error.tolist(),
                    'root_position': [0, 1.4, 0],
                    'root_velocity': [0, 0, 0],
                    'center_of_mass': data.subtree_com[1].tolist(),
                    'elbow_limit_violation_rad': max(
                        0.0, -0.1 - float(data.qpos[4]), float(data.qpos[4]) - 3.14
                    ),
                    'strength': float(strength),
                    'damping': float(damping),
                    'contacts': int(data.ncon),
                    'contact_forces_local': forces,
                    'contact_events': contact_records,
                    'local_rotations_xyzw': [
                        data.qpos[[1, 2, 3, 0]].tolist(),
                        [0, 0, float(np.sin(data.qpos[4] / 2)), float(np.cos(data.qpos[4] / 2))],
                    ],
                }
            )
        if i < steps:
            data.qfrc_applied[:] = torque + external
            mujoco.mj_step(model, data)
            mujoco.mj_forward(model, data)
        if not np.isfinite(data.qpos).all() or any(w.number for w in data.warning):
            raise RuntimeError('Invalid spatial simulation')
    return {
        'schema': 1,
        'rig': 'spatial_arm_v1',
        'source': (
            'SAM observations' if motion.metadata['provenance']['kind'] == 'sam3d' else 'synthetic test'
        ),
        'inference': motion.metadata['inference'],
        'capture': motion.metadata,
        'assistance': 'fixed world shoulder; no full-body balance',
        'disturbance': disturbance,
        'physics_configuration': physics,
        'physics_sha256': hashlib.sha256(
            json.dumps(physics, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        'feasibility': {
            'passed': peak_limit_violation <= physics['feasibility_limits']['max_joint_limit_violation_rad']
            and penetration <= physics['feasibility_limits']['max_penetration_m'],
            'criteria': physics['feasibility_limits'],
            'balance': 'not applicable: fixed root',
            'foot_contact': 'not applicable: no feet',
        },
        'coordinates': 'RH +Y up, metres, seconds; shoulder quaternion wxyz + elbow radians',
        'edit': asdict(edit),
        'frames': frames,
        'metrics': {
            'tracking_rmse_deg': float(np.degrees(np.sqrt(np.mean(np.square(errors))))),
            'contact_steps': contacts,
            'max_penetration_m': penetration,
            'saturated_fraction': saturated / (steps + 1),
            'peak_torque_Nm': np.max(np.abs(torques), axis=0).tolist(),
            'motor_effort_Nm2_s': effort,
            'peak_joint_limit_violation_rad': peak_limit_violation,
            'peak_contact_force_N': peak_contact_force,
            'mean_squared_torque': float(np.mean(np.square(torques))),
            'peak_speed_rad_s': float(np.max(np.abs(velocities))),
            'simulation_wall_s': time.perf_counter() - started,
            'steps': steps,
            'timestep_s': float(model.opt.timestep),
            'mujoco': mujoco.__version__,
        },
    }


def synthesize(motion, edit):
    """Bounded, same-clip parameter search; not learned/generalized control."""
    settings = list(
        dict.fromkeys([(edit.strength, edit.damping), (1, 1), (0.7, 0.7), (1.4, 0.7), (1.8, 1), (1.4, 1.4)])
    )
    results = [run_spatial(replace(edit, strength=s, damping=d), motion) for s, d in settings]

    def score(r):
        m = r['metrics']
        return (
            m['tracking_rmse_deg']
            + 10 * m['saturated_fraction']
            + 0.002 * m['mean_squared_torque']
            + 1000 * m['max_penetration_m']
        )

    feasible = [i for i, r in enumerate(results) if r['feasibility']['passed']]
    selected = min(feasible, key=lambda i: score(results[i])) if feasible else 0
    # Never replace a current configuration with a worse scalar objective.
    if score(results[selected]) > score(results[0]):
        selected = 0
    return results[selected], {
        'method': 'same-clip PD gain search including current settings; no generalization claim',
        'selected': selected,
        'status': 'feasible' if results[selected]['feasibility']['passed'] else 'no_acceptable_improvement',
        'current_candidate': 0,
        'current_score': score(results[0]),
        'selected_score': score(results[selected]),
        'objective': 'RMSE degrees + 10*saturation + .002*mean squared torque + 1000*penetration metres',
        'candidates': [
            {'edit': r['edit'], 'metrics': r['metrics'], 'feasibility': r['feasibility'], 'score': score(r)}
            for r in results
        ],
    }
