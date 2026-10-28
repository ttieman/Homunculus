"""Supported physical reach. SI units, right-handed X-right/Y-up/Z-out."""
from dataclasses import asdict, dataclass, replace
import math
import time
import mujoco
import numpy as np


@dataclass(frozen=True)
class Edit:
    duration: float = 4.0
    shoulder_deg: float = 65.0
    elbow_deg: float = -35.0
    strength: float = 1.0
    damping: float = 1.0
    obstacle: bool = True

    @classmethod
    def parse(cls, values):
        if not isinstance(values, dict) or set(values) - set(cls.__dataclass_fields__):
            raise ValueError('Unknown authoring fields')
        result = cls(**values)
        for key, lo, hi in [('duration', 2, 30), ('shoulder_deg', 5, 100),
                            ('elbow_deg', -100, 30), ('strength', .1, 2), ('damping', .2, 3)]:
            val = getattr(result, key)
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val) or not lo <= val <= hi:
                raise ValueError(f'{key} must be finite and within [{lo}, {hi}]')
        if type(result.obstacle) is not bool:
            raise ValueError('obstacle must be boolean')
        return result


def model_for(edit, captured=False):
    shoulder_range = '-2.8 2.8' if captured else '-.3 1.9'
    elbow_range = '-2.8 2.8' if captured else '-1.9 .8'
    obstacle = '<geom name="obstacle" type="box" pos=".47 1.65 0" size=".075 .12 .16" rgba=".9 .48 .2 1"/>' if edit.obstacle else ''
    return mujoco.MjModel.from_xml_string(f'''<mujoco model="Force Puppet supported arm">
      <compiler angle="radian"/>
      <option timestep="0.002" gravity="0 -9.81 0" integrator="implicitfast"/>
      <default><joint damping=".1" armature=".02"/><geom friction=".7 .01 .001"/></default>
      <worldbody>
        {obstacle}
        <body name="upper_arm" pos="0 1.4 0">
          <joint name="shoulder" type="hinge" axis="0 0 1" range="{shoulder_range}"/>
          <geom type="capsule" fromto="0 0 0 .34 0 0" size=".045" mass="1.4"/>
          <body name="forearm" pos=".34 0 0">
            <joint name="elbow" type="hinge" axis="0 0 1" range="{elbow_range}"/>
            <geom type="capsule" fromto="0 0 0 .29 0 0" size=".035" mass=".9"/>
            <site name="hand" pos=".29 0 0" size=".045"/>
          </body>
        </body>
      </worldbody>
      <actuator><motor joint="shoulder" ctrllimited="true" ctrlrange="-35 35"/>
        <motor joint="elbow" ctrllimited="true" ctrlrange="-20 20"/></actuator>
    </mujoco>''')


def reference(t, edit):
    # Authored fixture: ease from horizontal into a held reaching pose, then return.
    u = t / edit.duration
    x = min(max(u / .4, 0), 1) if u < .6 else min(max((1-u) / .4, 0), 1)
    blend = x*x*(3-2*x)
    return np.radians([edit.shoulder_deg, edit.elbow_deg]) * blend


def run(edit, motion=None):
    from spatial import SpatialMotion, run_spatial
    if isinstance(motion, SpatialMotion):
        return run_spatial(edit, motion)
    model = model_for(edit, captured=motion is not None)
    data = mujoco.MjData(model)
    if motion is not None:
        data.qpos[:] = motion.target(0,edit.duration)
    mujoco.mj_forward(model, data)
    if motion is not None and data.ncon:
        raise ValueError('Captured starting pose overlaps the obstacle; disable obstacle or trim the capture')
    frames, errors, torques = [], [], []
    contact_steps = saturated = 0
    penetration = 0.0
    started = time.perf_counter()
    steps = round(edit.duration / model.opt.timestep)
    for i in range(steps + 1):
        target = reference(data.time, edit) if motion is None else motion.target(data.time,edit.duration)
        # Ordinary PD + model gravity/bias compensation, NOT Tan et al.'s stable PD.
        desired = 90*edit.strength*(target-data.qpos) - 8*edit.damping*data.qvel + data.qfrc_bias
        torque = np.clip(desired, [-35, -20], [35, 20])
        if i % 10 == 0 or i == steps:
            frames.append({'t': float(data.time), 'q': data.qpos.tolist(), 'target': target.tolist(),
                           'hand': data.site_xpos[0].tolist(), 'contacts': int(data.ncon)})
        errors.append((target-data.qpos).copy())
        torques.append(torque.copy())
        contact_steps += int(data.ncon > 0)
        saturated += int(np.any(np.abs(desired-torque) > 1e-8))
        for c in data.contact:
            penetration = max(penetration, -float(c.dist))
        if i < steps:
            data.ctrl[:] = torque
            mujoco.mj_step(model, data)
            # Refresh Cartesian transforms to the post-step qpos before recording.
            mujoco.mj_forward(model, data)
        if not np.all(np.isfinite(data.qpos)) or any(w.number for w in data.warning):
            raise RuntimeError('Simulation became invalid or issued a MuJoCo warning')
    return {'schema': 1, 'source': 'original procedural reach fixture' if motion is None else 'imported '+motion.metadata['provenance']['kind']+' arm motion',
            'inference': 'NOT_RUN' if motion is None else motion.metadata['inference'],
            'capture': None if motion is None else motion.metadata,
            'assistance': 'fixed world shoulder; no balance controller', 'coordinates': 'RH, +Y up, metres, seconds, radians',
            'edit': asdict(edit), 'frames': frames,
            'metrics': {'tracking_rmse_deg': float(np.degrees(np.sqrt(np.mean(np.square(errors))))),
                        'contact_steps': contact_steps, 'max_penetration_m': penetration,
                        'saturated_fraction': saturated/(steps+1),
                        'peak_torque_Nm': np.max(np.abs(torques), axis=0).tolist(),
                        'simulation_wall_s': time.perf_counter()-started, 'steps': steps,
                        'mujoco': mujoco.__version__, 'timestep_s': float(model.opt.timestep)}}
