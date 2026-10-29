# Experiment 001 — supported reach

Measured locally 2026-10-26/27; Windows, Python 3.13.1, MuJoCo 3.17.0,
NumPy 2.5.4. No GPU inference, remote-controller run or training performed.

Commands: `python -m pytest -q`; `python scripts/measure.py` using the isolated venv.
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

## Experiment 002 — capture adapter (2026-10-27)

Implemented offline SAM video worker, raw numeric-output retention, source overlays,
explicit basis mapping, short-gap interpolation, angle cleanup and motion-driven
simulation. Browser import/validation, reviewed application, local video preview,
source-hash matching and capture-aware undo/export are implemented.

**PASS:** 32 total tests, including known analytic mapping, scale/translation
invariance, proper basis conversion, missing data and bad observations, time
stretch, repeatability and simulated-output export. Live HTTP capture simulation
with an explicitly labelled synthetic observation bundle measured 1.9852-degree
tracking RMS for a four-second free reach. This is NOT a SAM accuracy result.

**PASS:** browser selected a fixture JSON, displayed synthetic provenance and
diagnostics, required the review checkbox and applied motion to physics. It
disabled pose sliders and unsupported language edits while retaining physical
controls. Browser Undo restored the procedural source and its controls. Captured
motion contact and initial-overlap rejection also passed. Worker CLI help and
Python/JavaScript syntax checks passed. `evidence/capture-import.png` shows the
explicitly labelled synthetic importer test, not a SAM inference result.

**BLOCKED:** actual video decoding plus SAM inference has not been executed.
Approved weights and an owned input recording are still required. The worker's
GPU memory/runtime and prediction quality are unmeasured. All numeric arm tests
use synthetic observations, never presented as real capture.

Latest worker inspection: ~11654 MiB GPU memory free; former model service reports
failed, not successful completion. No service was restarted or interrupted by
this experiment. No SAM environment/weights were installed there yet.

## Experiment 003 — real SAM capture and spatial synthesis

See [SYNTHESIS.md](SYNTHESIS.md). The earlier SAM-blocked status is superseded. Real owned video inference, spatial torque tracking, controller search and independently verified glTF export now run. Full-body balance and captured-animation language editing remain incomplete.
