# Code map

How a recorded clip becomes an editable animation, and where each step lives.

```
video ──► worker/ ──────► homunculus/capture ──► homunculus/physics ──► homunculus/retarget ──► homunculus/export
          SAM 3D Body     validate + smooth      MuJoCo arm            whole skeleton          glTF / assets
          (GPU node)      into motion            (strength, damping)   onto the GLB character
                                   ▲
                 homunculus/animation (timeline, segments, pose edits)
                 driven by homunculus/editor (server + commands) and homunculus/muse (chat)
```

## Folders

| Folder | What it is | Start reading at |
|---|---|---|
| `server.py` | Launcher for the editor (`python server.py`) | — |
| `web/` | Browser editor: UI (`index.html`), state and wiring (`app.js`), 3D stage (`stage3d.js`), command dispatch + undo (`workspace.js`), SAM upload + job polling (`jobs.js`), frame sampling and arm placement (`motion-math.js`), segment list text (`segments.js`). New `web/*.js` files must be added to the server's file list in `editor/server.py` | `app.js` |
| `homunculus/editor/` | Local HTTP server (`server.py`: every `/api/...` route), the workspace command catalog shared by buttons and Muse (`commands.py`), and remote/local SAM worker selection (`sam_workers.py`) | `server.py` `do_POST` |
| `homunculus/capture/` | Capture bundle (`homunculus.observations.v1`) → motion. `prepare.py` picks the path; `spatial.py` (3D arm, the one in use) or `planar.py` (original side-on arm); `quality.py` diagnostics | `prepare.py` |
| `homunculus/physics/` | MuJoCo simulation. `settings.py` (the `Edit` authoring values), `simulate.py` (picks the arm), `spatial.py` (3D arm + gain search), `planar.py` (original arm) | `simulate.py` |
| `homunculus/animation/` | Editable timing: `timeline.py` (keyframes, output→source time), `segments.py` (per-range physics), `pose_editor.py` (joint edits) | `timeline.py` |
| `homunculus/retarget/` | Onto the game character: `body.py` (whole skeleton from 70 body keypoints), `rig.py` (load the GLB character), `arm.py` (arm-only retarget), `character_glb.py` (write/replay the posed GLB), `geometry.py` (quaternions) | `body.py` `retarget_body` |
| `homunculus/export/` | `gltf.py` (physics result → glTF + replay), `assets.py` (versioned, checksummed motion assets) | `gltf.py` |
| `homunculus/muse/` | Meta's hosted model: `meta.py` (API access, edit proposals), `chat.py` (one chat turn with tool calls) | `chat.py` |
| `homunculus/contracts.py` | Shared limits (frames, duration, request size) and validators | — |
| `worker/` | Runs on the GPU node: `service.py` (job queue HTTP service), `capture_video.py` (SAM 3D Body + person detection) | `service.py` |
| `scripts/` | One-off tools: `measure.py` (experiment 001 outputs), `synthesize.py` (asset from a capture), `add_body.py` (backfill body keypoints) | — |
| `tests/` | `pytest` unit tests; `tests/browser/` Playwright specs; `*_fixture.py` build test inputs | — |
| `docs/` | `PLAN.md` (what's next), `SETUP.md`, `CAPTURE.md`, `STATUS.md`, `MUSE_WORKSPACE.md`; experiment records: `EXPERIMENTS.md`, `SYNTHESIS.md`, `DECISIONS.md`, `MODEL_POLICIES.md` | `PLAN.md` |

Ignored, local only: `private/` (clips, jobs, captures), `outputs/` (generated
files), `.env.local` (keys and character path), `node_modules/`.

## One request, end to end

1. **Upload** (`web/app.js` → `POST /api/jobs`): the server forwards the video to
   `worker/service.py`, which runs `worker/capture_video.py` under the GPU lock.
2. **Done** (`GET /api/jobs/<id>`): the server saves the mp4 and `capture.json` to
   `private/clips/<time>-<name>/` and the page applies the capture.
3. **Simulate** (`POST /api/simulate`): `capture.prepare` → `physics.simulate.run`
   → `export.gltf.export_gltf`; with a character, `retarget.body.retarget_body`
   poses every bone and `retarget.character_glb.export_character_glb` writes the GLB.
4. **Edit**: buttons and Muse both send workspace commands (`editor/commands.py`)
   through `web/workspace.js`, which validates, applies and records undo.
   Segment edits go to `POST /api/segments`, timing to `POST /api/reference`.

## Conventions

- Imports are absolute from the repository root: `from homunculus.physics.settings import Edit`.
  Run Python from the root (`python -m pytest`, `python server.py`, `python scripts/measure.py`).
- Formatting: Black for Python and Prettier for `web/` and the browser specs, both at
  110 columns with single quotes (`pyproject.toml`, `.prettierrc.json`). Run them before
  committing: `python -m black .` and `npx prettier@3.3.3 --write web tests/browser`.
- On the GPU node the deployed folder holds `homunculus/` (only `contracts.py` and
  `capture/` are needed) and `worker/`; start it with `python -m worker.service`.

## Game export verification

See [export and Bevy preview](EXPORT_PREVIEW.md). scripts/export_preview.py
exports a saved full-body capture through the editor handler, validates the
GLB, and writes evidence for Bevy Playground examples/homunculus_preview.rs.

### Guided browser workflow (2026-10-29)

`web/workflow.js` presents four steps around the existing command controls;
`web/workflow.css` owns responsive layout and focus states. The single 3D canvas
is a fixed full-window base layer. The steps are icon squares that open one
floating panel, and the Muse chat is a collapsible corner window; on narrow
screens opening one closes the other. Menus start collapsed on load.
`web/library.js` and `homunculus/editor/library.py` own the Import/Library panel. Assets are plain files under
`private/` (`clips/`, `exports/`, `projects/`, `scenes/`); titles, creation dates and the last opened asset are in
`private/library.json`, so renaming never moves a file. `server.py --storage` selects another folder, and browser
tests use one so they never touch real clips.
`web/capture.js` owns the Capture panel: camera choice, countdown and browser recording
(video only, webm, 2.1-30 s). A take stays local until Convert hands it to the Import upload path. `web/app.js` remains
the state owner and supplies readiness to the workflow. File selection does not
submit a worker job: Convert starts it explicitly, retains the file after failure,
and shows indeterminate progress. Export checks applied settings in both UI and
the shared command handler so a stale preview cannot silently become a download.


### Whole-character animation rotation

homunculus/animation/rotation.py validates capture.animation_rotation (pitch/yaw/roll,
degrees) and applies one rigid transform to retargeted character tracks after composition.
The first pelvis position is the fixed pivot; motion translation rotates around it.
web/app.js owns the Edit fields and shared set_animation_rotation action; the capture
metadata flows through existing snapshots, projects, references and library persistence.
The character GLB contains the same transformed tracks as the preview; raw reference
physics, camera mapping and input observations are unchanged. Reset uses the base
retargeted result, avoiding accumulated rotations.
