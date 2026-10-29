# Plan — 2026-10-28

Homunculus turns a recorded performance into an editable game animation:

```
video clip ──► SAM 3D Body (GPU worker) ──► whole-skeleton retarget ──► timing / feel edits ──► character GLB
   upload          person detect, 70 keypoints     19 bones + pelvis        manual controls or        Bevy
                                                                             Muse chat, same tools
```

This replaces the closed GitHub issues and the old "Next experiments" list.

## Done

| Step | State |
|---|---|
| Submit a clip | Editor upload (mp4/webm/mov/mkv/avi/mpg, up to 30 s from a start time). Non-mp4 is cut and converted on the worker. |
| SAM 3D Body service | `worker/service.py` on the GPU node, one job at a time through `with-gpu.sh`; ViTDet person box; progress in the editor. ~1 s per sampled frame on the RTX 2060. |
| Whole-skeleton retarget | Automatic on job completion; clip kept in `private/clips/`, newest opens on load. Captured arm follows the recording; physics arm optional. |
| Timing primitives | Keyframes carry `time` + `sourceTime`; `timeline.source_time` maps output time to source time, so retiming already moves the body, physics reference and video sync together. Interpolation is `linear`, `smoothstep` or `hold` per key. |
| Muse plumbing | Chat panel ("Direct the workspace"), typed tool catalog shared with manual controls (`homunculus/editor/commands.py` → `web/workspace.js`), undo, receipts, 8-turn cap. **Never called live**: no `MODEL_API_KEY`; model id `muse-spark-1.3` and endpoint are unverified. |

## Phase 1 — Segment layer: physics, then speed (next)

Per-range edits as structured data over the whole clip, not per-key edits (a 25 s
clip has ~380 keys).

**Model.** `capture.timing` (`homunculus.timing.v1`): ordered, non-overlapping
segments over *source* time, `{id, start, end, blend, curve}` plus any of
`strength`, `damping` (physics) and `speed` (timing). `blend` seconds at each end
ease the segment's values in and out of the clip-wide settings along `curve`.

**1a — physics per segment (done 2026-10-28).** `homunculus/animation/segments.py`; `set_segment` /
`clear_segments` commands (Muse tools too) and a **Segment physics** panel; undoable. Strength (0.1–2) and damping (0.2–3)
override the clip-wide controls inside a segment; the MuJoCo loop reads them per
2 ms step through the output→source time map, and each result frame records the
gains used. Physics drives only the supported arm, so the visible effect needs
**Drive arm from physics** (the whole-body retarget follows the recording).

**1b — speed per segment.** `speed` compiles to a monotone output→source time
map; keyframe `time`s are regenerated from it, so body, arm reference, physics
and video sync need no new code paths. Original `sourceTime`s are never changed.

**Speed curves** (how speed moves across a segment or blend — this is the "feel"):

| Curve | Feel |
|---|---|
| `constant` | Plain speed change |
| `ramp` (linear) | Even acceleration/deceleration |
| `ease_in`, `ease_out`, `ease_in_out` (cubic) | Wind-up / settle / both |
| `smootherstep` | Softer, filmic transitions |
| `expo_in`, `expo_out` | Snappy attack or long hang |
| `freeze` | Hold the pose for the segment's output length |
| `stepped(fps)` | Pose updates on twos/threes (12 or 8 fps), anime/stop-motion |

Named presets combine segments + curves (e.g. **snappy**: expo_out into hits;
**heavy**: ease_in on wind-ups, slower overall; **floaty**: smootherstep, 0.8×).

**Validation.** Segments ordered, non-overlapping, inside the clip; speed
0.1–4×; output duration 2–30 s; smoothed arm reference still ≤720 °/s;
`stepped` fps 4–30. Errors name the segment.

**Done when.** Unit tests: an empty layer reproduces today's result exactly; a
segment's gains apply only inside it and blend along the curve; (1b) the time
map is monotone, a 2× segment halves that span's output time for every bone, and
the exported GLB clip length matches.

## Phase 2 — Commands and manual UI

* Tools in `homunculus/editor/commands.py` (shared by buttons and Muse): `set_segment` (range plus
  strength/damping/speed, curve, blend), `apply_feel(preset, range?)`,
  `clear_segments(range?)`; segments appear in `inspect_workspace`. The physics
  half lands with 1a so Muse can use it as soon as access is verified.
* A speed lane under the playback bar: segments as blocks with speed labels,
  drag edges to change range, curve picker, before/after toggle (A/B playback
  against the untimed clip), undo/redo through the existing history.

**Done when.** Every timing edit is reachable without Muse and round-trips
through save reference / reload.

## Phase 3 — Muse drives timing from chat

* **Access (grA):** add `MODEL_API_KEY=...` to `.env.local`. Claude never reads or
  writes `.env*`.
* Verify the real model id, endpoint and tool-call format with one live call;
  fix `homunculus/muse/meta.py`/`chat.py` to match. Status shows *verified* only after that.
* System prompt and state: Muse sees clip length, current segments, motion
  phases (key times where speed peaks/stops, derived from the body track), and
  the curve/preset catalog — not raw keypoints or video.
* Requests like "make the draw snappy and the follow-through floaty" become
  `set_speed`/`apply_feel` calls; each receipt reports the new duration and
  affected range; changes are undoable and shown with A/B playback.
* Optional: send a viewport snapshot so Muse can refer to what it sees.

**Done when.** A live chat session applies a multi-segment timing edit to a
processed clip and the exported GLB contains it. Tests use recorded fixture
responses only for protocol checks, never as claimed model quality.

## Phase 4 — Export and game playback

Bake timing into the character GLB clip (already uses the retargeted frames),
name the clip after the source, and verify playback in `bevy-playground`
(currently untested).

## Backlog (after the timing work)

* **Per-bone pose edits** — keyframe the whole skeleton, not just the arm (rotate
  any bone at a key, interpolate between).
* **Capture quality** — flag frames where legs are out of frame or low confidence;
  foot-contact cleanup; footage guidance (full body, camera 3–4 m back at waist
  height).
* **Consolidate** — venv and clips into this repo's folder; retire the
  force-puppet checkout; permanent worker service on the GPU node (systemd unit,
  grA's call) instead of the SSH-session runner.
* **Readability** — formatted (Black / Prettier) and split (`retarget/character.py` →
  geometry/rig/arm/character_glb; pure parts of `web/app.js` → jobs/motion-math/segments),
  2026-10-29. `app.js` still owns all editor state in one module.
* **Speed** — sample rate choice per job; overlapping conversion with inference.

## Open questions

1. ~~Muse access?~~ grA has it; the key goes in `.env.local` and the model id and
   endpoint get verified live in Phase 3.
2. Preset names and the exact feel of each — tune once the speed lane exists.
3. ~~Physics per segment?~~ Yes — both physics and speed; strength/damping first.
