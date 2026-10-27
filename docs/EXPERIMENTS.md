# Experiment 001 — supported reach

Measured locally 2026-10-26/27; Windows, Python 3.13.1, MuJoCo 3.17.0,
NumPy 2.5.4. No GPU inference, remote-controller run or training performed.

Commands: `python -m pytest -q`; `python measure.py` using the isolated venv.
Original source motion is `puppet.reference`. Geometry, mass, constraints and
controller parameters are in `puppet.model_for` and `puppet.run`. No external
motion dataset or game asset is used. See `evidence/summary.json` for raw metrics.

| Case | Tracking RMS, degrees | Contact samples | Maximum penetration | Simulation wall time | Export maximum component error |
|---|---:|---:|---:|---:|---:|
| Clean 4 s reach | 2.8583 | 0 | 0 mm | 128 ms | 6.27e-8 m |
| Obstructed 4 s reach | 21.3422 | 1507 | 2.4944 mm | 138 ms | 2.20e-8 m |
| Slow/loose 6 s reach | 4.6585 | 0 | 0 mm | 178 ms | 5.78e-8 m |

Timing is one observed CPU run, not a statistical benchmark. Simulation uses
2 ms fixed steps, exporting every 10 steps (50 Hz) and the terminal sample.
Motion is metre-based, right-handed Y-up, planar about the Z axis. Internally
angles are radians, user controls degrees, actuator torques Nm.

## What passed

- **PASS:** 17 local tests. Clean tracking, actual obstacle-induced deviation,
  no initial obstacle overlap, torque bounds, four strength/damping extremes,
  invalid inputs, explicit missing access, deterministic repeated/undone settings.
- **PASS:** independently decoded glTF rotation buffers reproduce simulated hand
  positions within 1 micrometre at sampled times. The check is sensitive to a
  deliberately corrupted joint offset and to replacing physical motion by targets.
- **PASS:** manual duration/obstacle controls visibly changed the browser result.
- **PASS:** isolated browser check restored 4 seconds, obstacle enabled and the
  original 21.34-degree error through Undo; replay switched to decoded glTF buffers.
  Asking Spark without credentials visibly reported BLOCKED and applied no edit.
  Desktop and narrow-panel layouts were visually inspected; editor.png records
  the supported arm at the contact portion of the clip.
- **PASS:** adapter parsing with a clearly identified network fixture. This tests
  software contracts only, not Spark's quality or response behaviour.

## Control findings

Ordinary PD with dynamics bias compensation and bounded motors was sufficient
for this supported arm. It is not an implementation of Tan et al.'s Stable PD.
The fixture absorbs root reactions. There is no free root or balance policy.
Blocked tracking error is expected: the target asks the body to cross an obstacle.
The shoulder saturates for ~57.5% of samples in the blocked case. That is useful
diagnostic evidence, not proof of an acceptable final character performance.

An initial obstacle placement overlapped the horizontal forearm by 25 mm. The
fixture was corrected before baseline measurement; the test now checks that the
initial sample has no contact. Final contact begins around 0.54 seconds.

## Status by layer

| Layer | Status | Evidence / next step |
|---|---|---|
| Conventional physical control | PASS, bounded slice | Contact and clean-reference tests |
| Manual editing | PASS | Deterministic changes and replay |
| Muse Spark inference | BLOCKED | User has not configured API access |
| SAM 3D reference reconstruction | BLOCKED | No gated weights/access or source recording |
| PHC / MaskedMimic original runtime | NOT RUN | Compatibility and release-contract inspection only |
| glTF export/replay | PASS, sampled transforms | Independent decoder and corruption controls |
| Full-body balance / retargeting | NOT IMPLEMENTED | Requires a separate controller/mapping experiment |
| Actual Bevy game playback | UNVERIFIED | Existing game loader inspected; no clip loaded there |

## Remaining limitations

The visible arm is articulated rigid geometry, not a skinned full-body character.
The glTF excludes the obstacle and does not transfer adaptive physics control.
Export fidelity is checked at sample times; subframe interpolation/contact
fidelity and external DCC/game playback are not yet measured. The UI replays a
completed bake rather than running an interactive physics loop. Controls affect
the whole clip. Sessions can be saved but not reimported. Undo history is in memory.
API configuration status only checks whether a variable is present, not entitlement.

The Linux worker was actively serving another model request during repeated
checks. No service was interrupted. Its completion is a prerequisite for GPU
takeover, as requested by the user. Missing Meta access remains the next essential
dependency even after the worker becomes free.
