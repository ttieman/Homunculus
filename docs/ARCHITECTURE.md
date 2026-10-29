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
| `web/` | Browser editor: UI (`index.html`, `app.js`), 3D stage (`stage3d.js`), command dispatch + undo (`workspace.js`) | `app.js` |
| `homunculus/editor/` | Local HTTP server (`server.py`: every `/api/...` route) and the workspace command catalog shared by buttons and Muse (`commands.py`) | `server.py` `do_POST` |
| `homunculus/capture/` | Capture bundle (`homunculus.observations.v1`) → motion. `prepare.py` picks the path; `spatial.py` (3D arm, the one in use) or `planar.py` (original side-on arm); `quality.py` diagnostics | `prepare.py` |
| `homunculus/physics/` | MuJoCo simulation. `settings.py` (the `Edit` authoring values), `simulate.py` (picks the arm), `spatial.py` (3D arm + gain search), `planar.py` (original arm) | `simulate.py` |
| `homunculus/animation/` | Editable timing: `timeline.py` (keyframes, output→source time), `segments.py` (per-range physics), `pose_editor.py` (joint edits) | `timeline.py` |
| `homunculus/retarget/` | Onto the game character: `body.py` (whole skeleton from 70 body keypoints), `character.py` (GLB read/write, arm-only retarget, export) | `body.py` `retarget_body` |
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
   poses every bone and `retarget.character.export_character_glb` writes the GLB.
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
