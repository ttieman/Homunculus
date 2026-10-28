# Motion synthesis — 2026-10-27

Historical first-synthesis report. Subsequent inspection fixes and current contracts
are described in [STATUS.md](STATUS.md); the measurements below belong to the
original recorded experiment, not an automatic rerun after every change.

## Audit and selected scope

Existing modules are retained: `capture_video.py` owns offline SAM inference;
`motion.py` validates the original planar capture; `puppet.py` owns the existing
MuJoCo arm; `server.py` and `web/` own the loopback editor; `exporter.py` owns glTF.
Muse Spark already proposes bounded procedural edits but has no configured API
access. Model jobs are offline SSH/CLI operations, not a durable web job queue.
Raw and generated personal assets live in ignored `private/` and `outputs/`.

The supplied seated video contains genuine depth motion and cannot satisfy the
planar adapter's 25-degree gate. That gate remains intact. An explicit
`spatial_arm_v1` path adds a ball shoulder and elbow hinge using the same engine.
The existing game and its rigs are untouched. This is the handoff's incremental
pose-to-animation slice plus a supported-arm tracking experiment, not completion
of all six proposed stages or of a standing/crouching character.

## Contracts

- Capture: observations v1 retains timestamps, coordinate basis, source hashes,
  model revision and raw prediction NPZ files. Raw MHR parameters are never
  interpreted as engine quaternions. Named shoulder/elbow/wrist keypoints supply
  directions, independent of reconstructed scale and root translation.
- Pose library / reference: `timeline.py`, reference v1, skeleton ID, stable pose
  and key IDs, local unit quaternions (wxyz), root positions and timing curves.
  Hemisphere-correct shortest-arc SLERP interpolates rotations. Root positions
  interpolate independently. Linear, smoothstep and hold are supported.
- Spatial conversion: fixed lengths .34/.29 m; a bend-plane frame supplies the
  shoulder rotation. Axial twist is a convention, not measured anatomy. Near
  straight elbows retain the previous projected bend-plane direction. Samples
  with >720 deg/s discontinuity are rejected; 90 ms hemisphere-mean cleanup is
  explicit. Missing observations are rejected in this path.
- Physics adapter: only fixed-root references and elbow-axis rotations are
  accepted. General root animation is valid for timeline sampling but is rejected
  by this supported-arm controller. No per-step pose teleportation.
- Controller: conventional PD plus dynamics bias compensation, bounded torques
  [35,35,35,20] Nm. 2 ms integration, 20 ms recorded/exported samples plus terminal
  frame. Shoulder feedback uses quaternion tangent-space error. Desired velocity
  feed-forward is not implemented.
- Trajectory: target/actual poses, angular velocities, unclamped command and
  clamped upcoming torque, previous applied torque, center of mass, fixed root,
  joint-limit violation, contacts and local contact wrenches. These are
  model-dependent simulated forces, never recovered human forces. Contact
  wrenches describe the evaluated current state, not an integrated impulse.
- Motion profile: reference, trajectory, controller version/parameters, lengths,
  masses, timestep, gravity, engine, optimization results and validation scope.

## Reproduce and edit

In the existing SAM environment run the worker with `--spatial`, `--seconds` up
to 30, an explicitly reviewed bounding box and coordinate basis. Source timestamps
are preserved; requested sample rate is a maximum and decoder alignment can
reduce effective rate. The worker retains all numeric predictions and overlays.

On the editor machine:

```powershell
.venv/Scripts/python.exe synthesize.py private/capture.json --output private/my-motion
```

This creates capture.json, reference-animation.json, simulation.json,
animation.gltf, synthesis-report.json and motion-profile.json. Output directories
must be new. Export verification independently decodes glTF rotation buffers and
compares resulting hand transforms with the physical bake.

Import capture.json in the editor and inspect the mapping. Use captured motion,
then Optimize captured motion. Assemble three poses selects the start, middle and
end keys from the reference. Change a key's time and outgoing timing curve with
Apply keyframe edit. Undo/Redo retain complete references. Save reference writes
an observation wrapper containing the edited reference; reload it through the
same import control. Export glTF saves the physical bake. Drag the stage to orbit.

The structured timeline command API accepts move_keyframe, set_duration and
set_interpolation with strict parameter fields and atomic validation. The current
Spark adapter has not been wired to these commands; captured-animation natural
language editing remains unavailable. Manual editing provides the tested path.

## Measured real-video experiment

SAM 3D Body revision b5c765a0d89d789985e186d396315e7590887b94, DINOv3 checkpoint,
PyTorch 2.14.1+cu130, RTX 2060 12 GB. Existing compute model service was stopped
at the user's explicit request. The installed environment lacked checkpoint
binaries; these were downloaded using existing approved access.

195 observed poses over 14.55 seconds, anatomical left arm. Requested 15 Hz,
actual average 13.33 Hz. Worker time including decode/inference/output hashes but
excluding model load: 161.65 s. Peak allocated CUDA memory: 3,790,622,720 bytes.
Six sampled source overlays visually follow the arm; wrist visibility is poor
near frame edges and during occlusion. This is not calibrated 3D ground truth.
The model logged missing MHR buffers and unsupported CPU NNPACK warnings; finite
outputs and overlay alignment were checked, but model accuracy remains unmeasured.

Five same-clip PD settings were compared. The selection objective is explicitly
RMSE degrees / 1 degree + saturation / .1 + mean squared torque / 500 Nm^2 +
penetration / .001 m. These are engineering weighting scales, not learned weights
or validated human plausibility criteria. Baseline is always a candidate.

| Strength | Damping | Tracking RMS degrees (initial linear-quaternion bake) |
|---|---|---|
| 1 | 1 | 5.0090 |
| .7 | .7 | 5.0744 |
| 1.4 | .7 | 2.6611 |
| 1.8 | 1 | 2.9065 |
| 1.4 | 1.4 | 4.9686 |

The final exact-SLERP asset measures 2.66114 degrees RMS and 6.31e-8 m maximum
export position-component error. Its report is the authoritative measurement. No contact or saturation occurred in the original unobstructed
recording. Separate analytic contact tests confirm physical deviation and forces.
This is parameter optimization of a feedback controller on one clip, not policy
learning or proof of robustness to disturbances or another character.

## Validation and open questions

48 tests cover prior functionality, quaternion SLERP/hemisphere consistency,
ordered keyframes, coordinate conversion, serialization, deterministic sampling,
invalid/mismatched skeletons, atomic edits, spatial contact, controller comparison,
and independent export decode with a deliberate corruption control.

Cubic positional interpolation and quaternion splines remain research options;
linear root interpolation and eased SLERP are the chosen inspectable baseline.
No confidence score is fabricated from SAM. Root, camera, anatomical limits and
occluded-pose accuracy need calibrated multi-view or known-pose validation.

Next major milestone: an original standing/crouching fixture on a free-root
full-body rig with ground contacts, foot constraints, falls, joint-specific gains
and disturbance experiments. Root/foot-contact/fall metrics are not meaningful on
this anchored arm and are not presented as successful balance. Study DeepMimic,
MHR utilities and ProtoMotions for that milestone before choosing any optional
backend. No heavyweight learning framework was added.

The full supplied handoff is a research proposal; the immediate implementation
priorities A–D are represented here. Text editing of captured animations, full-body
retargeting and active-ragdoll balance remain separate incomplete milestones.
