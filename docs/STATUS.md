# Current capabilities — 2026-10-27

This page is the current contract. Dated experiments and model-policy proposals
remain historical evidence, not a claim that every research stage is complete.

| Layer | Current status | Validation boundary |
|---|---|---|
| SAM capture | Operational offline Linux worker | Model accuracy is not independently measured |
| Spatial pose/timeline | Implemented | Fixed proportions, bend-plane twist convention |
| Timeline editing | Manual and validated Meta proposal adapter | Live Meta response pending local key |
| Physics | Supported spatial arm and original planar arm | No full-body ground/balance controller |
| Optimization | Current setting plus bounded PD sweep, explicit feasibility | Same clip; bounded joint-impulse replay tested, no generalization claim |
| Asset persistence | Checksummed v2 profiles with recorded XML and replay CLI | Exact MuJoCo version and supported arm rig |
| Browser comparison | Matching source video, source-time map, common animation transport | Seek latency is shown; no fake frame-perfect claim |
| Export | Timed quaternion replay and Khronos validator check | Rigid arm glTF |
| Character retarget | Arm directions onto an external stickman-contract GLB; viewer pose, GLB clip export, three.js replay | Directions only: no IK to contacts, rest body pose, other clips dropped; Bevy playback not yet tested |
| Full-body retarget | 70 SAM keypoints -> all 19 moving stickman bones + pelvis height; captured arm from physics; backfill from raw NPZ | Kinematic and in place: no balance, travel, foot IK or contact cleanup; spine curvature not observed (torso bends as one); exact on synthetic poses, real accuracy unmeasured |
| Capture quality | Diagnostics and optional annotated 2D-landmark evaluation | No invented confidence; calibrated 3D accuracy unmeasured |

Spatial inputs: 2–30 seconds, 3–901 frames, observation gaps <=250 ms, finite
poses and proper coordinate basis. Worker requests 2.1–30 seconds at 5–30 Hz.
Planar mode retains its older 2–10-second/601-frame/geometric restrictions.
Browser/server document limit: 8 MiB. Shared constants live in contracts.py.

Local key: MODEL_API_KEY in the environment or ignored .env.local. The UI only
reports configured/unconfigured; this is not a successful API entitlement test.
No key contents, private recordings or raw personal model output belong in Git.

## Files and reload paths

- capture.json / saved reference wrapper: browser capture importer.
- motion-profile.json v2: `python assets.py <asset-directory>` verifies checksums
  and replays the stored physical configuration.
- reference-animation.json: linked asset component; use its wrapper for browser import.
- animation.gltf: independent rigid-joint playback; no controller is embedded.
- saved browser session: audit output only; session import remains unsupported.

## Quality evaluation

`python quality.py private/capture.json --output private/quality.json` reports
missing/out-of-frame landmarks (if image dimensions exist), segment-length
variation and explicit unknowns. Add `--annotations private/annotations.json`
for independently labelled 2D pixel error, separated by recording condition.
Annotation schema: homunculus.annotations.v1, matching video_sha256, and frames
with t, condition and arm_pixels (three [x,y] points; null means unlabelled).
Use clear, sideways, occluded and cropped examples. Fixture tests prove arithmetic,
not SAM accuracy. A real independently annotated benchmark remains to be collected.

## Workspace tools (2026-10-28)

The 3D character branch now has a shared validated command interface for Muse
and manual controls: scene setup, playback, media attachments, exports,
undo/redo, timeline editing and bounded local pose corrections. See
[Muse workspace architecture and review](MUSE_WORKSPACE.md). Live model access
and new worker video runs remain separate verification steps.
