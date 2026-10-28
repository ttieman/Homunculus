# Video to physical arm — experiment 002

The implemented path is an offline worker plus a capture importer. Video selected
in the editor stays local to the browser; it is not automatically uploaded to SAM
or sent to the compute box. The worker must be run separately with approved
weights. Live inference has NOT RUN: weights and a user-owned source clip are
still missing. Synthetic tests exercise conversion, simulation and export only.

## Record a useful first take

Use one stationary person, fixed camera, visible shoulder/elbow/wrist and a
side-on 3–5 second reach. Keep the person inside one fixed crop for the whole
take. Avoid cuts, other people entering the crop, occlusion and rapid depth motion.
This first worker does not implement automatic identity tracking. It trusts the
user-selected single-person crop and asks for review of the overlay sequence.

## Run the worker

Use an isolated Python 3.11 environment following the official
[SAM installation](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md).
Request `facebook/sam-3d-body-dinov3` access, including its MHR asset. Record exact
revisions. Add this repository to that environment's Python path or execute its
script by absolute path. No changes to the editor's Python environment are needed.

```bash
python capture_video.py /path/to/owned-reach.mp4 \
  --sam-root /path/to/sam-3d-body \
  --checkpoint /path/to/model.ckpt --mhr /path/to/mhr_model.pt \
  --output private/reach-001 \
  --bbox 100 40 1100 700 --start 0 --seconds 4 --sample-hz 15 \
  --side right --basis 1 0 0 0 -1 0 0 0 -1
```

**Replace the crop and basis for your video.** The numbers above are an example,
not measured calibration. The basis maps native vectors into the puppet's
X-right/Y-up/Z-out frame. It must be a proper rotation. The shown basis flips Y
and Z; verify with a known upward/forward arm movement in the overlays and the
target preview before applying. Do not infer metric depth from this transform.

The worker loads SAM once, uses the explicit crop, samples decoded presentation
timestamps, and calls `process_one_image(..., inference_type='body')`. Missing or
nonmonotonic decoder timestamps fail explicitly; no constant-FPS guess replaces
them. Input timestamps are retained even when the clip begins partway through
the video. GPU fit and speed on the 12 GB worker remain unmeasured.

Outputs:

- `raw-*.npz`: native numeric SAM outputs (no pickle).
- `overlay-*.jpg`: 2D shoulder/elbow/wrist overlay for source review.
- `capture.json`: timestamped three-point observations, explicit basis and provenance.
- `report.json`: READY_FOR_REVIEW or NEEDS_REVIEW with the reason and diagnostics.

Only the shoulder/elbow/wrist directions feed this puppet. The source mesh,
absolute translation and segment lengths are not transplanted. The puppet keeps
its original dimensions; this is directional retargeting, not metric mocap.
Source revision, checkpoint/MHR/video hashes, crop, side, runtime and allocation
telemetry remain in the bundle. Default FOV is labelled uncalibrated.

## Use the editor

1. Optionally select the original video for local preview.
2. Import the worker's `capture.json`. Validation reports out-of-plane motion
   and interpolated missing frames. A selected video must match its source hash.
3. Inspect the worker overlays, person and coordinate mapping, then check the
   review box and choose **Use captured motion**.
4. The first captured run disables the obstacle. Adjust duration, strength and
   damping; enable the obstacle for a comparison once the starting pose is clear.
5. Undo restores both the previous controls and motion source. Export preserves
   capture provenance and the actual physical outcome.

The shoulder/elbow pose sliders are disabled for captures because the recording
owns those targets. Spark editing is currently limited to the procedural demo;
we do not send a capture to an adapter that cannot express trajectory edits.

## Validation policy

2–10 seconds, 3–601 samples, increasing timestamps, finite nondegenerate segments,
proper orthonormal basis. First and last poses must exist. Gaps longer than 250 ms
are rejected. Short gaps are interpolated and counted, never called observations.
Angles are unwrapped and filtered in a 65 ms half-window, preserving endpoints.
Native 3D directions more than 25 degrees from the selected plane are rejected.
Joint targets beyond ±2.7 rad or jumps over 720 degrees/second require review.
These conservative thresholds define this arm experiment, not SAM accuracy.

At initialization only, physics starts in the captured first pose. Subsequent
motion is torque-driven. Initial obstacle contact rejects the run. No root motion,
shoulder translation, twist, full-body balance or automatic rest-pose calibration
is implemented. A passing importer does not certify the correctness of a model
prediction; imported SAM provenance is labelled IMPORTED_UNVERIFIED locally.

## Source contracts

- [Estimator outputs](https://github.com/facebookresearch/sam-3d-body/blob/main/sam_3d_body/sam_3d_body_estimator.py)
- [MHR70 names](https://github.com/facebookresearch/sam-3d-body/blob/main/sam_3d_body/metadata/mhr70.py)

The worker resolves keypoint indices by the official names rather than assuming
that wrist indices follow the COCO layout. It saves raw output before retargeting.

## Spatial motion and longer clips

Use --spatial for the explicit 3D arm path (2.1–30 seconds). Run synthesize.py locally on its capture.json. See [SYNTHESIS.md](SYNTHESIS.md) for editing, optimization and artifact contracts. The original planar path retains its stricter geometric limits.
