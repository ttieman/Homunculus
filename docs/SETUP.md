# Setup and next experiment

Python 3.13 is tested. Windows PowerShell, from this repository:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe measure.py
.venv/Scripts/python.exe server.py
```

Open http://127.0.0.1:8765. Linux: use `.venv/bin/python` for the same commands.
No GPU is required for the first slice. No build step or CDN dependency.
The server binds loopback and only serves the editor's two static assets.
Do not expose this development server to the public internet.

Change controls, click **Simulate edit**, compare the dotted target with the
solid physical result, then **Undo**. **Export glTF** downloads a portable rigid
arm animation. **Replay export** decodes its embedded rotation buffers rather
than reading simulation joint samples. **Save session** retains settings,
results and the in-memory edit audit; importing saved sessions is not implemented.

## Enable the selected Meta integration

Obtain access through the official [Meta dashboard](https://dev.meta.ai/).
Set `MODEL_API_KEY` in the process environment before starting the server. Avoid
placing keys in source, screenshots, chat, shell history or public issues. Alternatively place MODEL_API_KEY=your_key in the ignored .env.local file; it
is read on demand. Restart only after changing process environment variables.

The implemented adapter uses `muse-spark-1.3` at
`https://api.meta.ai/v1/chat/completions`. It sends only the direction and current
controls for procedural edits (`propose_edit`). Spatial captures use
`edit_timeline` with key IDs, times and interpolation modes; no raw poses or
video are sent by that adapter. Example: “Make this six seconds
long and reduce strength to 0.4.” Review its complete proposed controls before
applying. It cannot yet edit a time interval, load a reference video or direct a
full-body rig. Unsupported requests should be rejected, not approximated silently.

The user confirmed credentials are not configured. A fixture parsing test exists;
it is not a live-model evaluation. Account access, endpoint response behaviour,
latency and semantic accuracy remain BLOCKED/UNVERIFIED.

## Compute worker

SAM 3D Body inference has run successfully on the existing 12 GB Linux GPU worker.
Use its isolated approved environment and checkpoints; do not reinstall or stop
unrelated jobs as part of routine setup. The first takeover was explicitly
requested by the user. Credentials and connection details remain local.

The worker needs capture_video.py, motion.py and contracts.py together. Install
these from the same revision. Use --spatial for 3D arm observations. The worker
and editor use separate Python environments; see CAPTURE.md and STATUS.md.

## Reusable motion assets

Run `python synthesize.py private/capture.json --output private/new-asset`.
The version-2 motion-profile.json references checksummed capture, reference,
physics, trajectory, glTF and optimization files. `python assets.py private/new-asset`
reloads the recorded configuration and compares reproduced positions and torques.
Do not edit linked files in place without regenerating the asset manifest.

Save reference produces an editable capture wrapper for the browser importer.
Save session is an audit download; browser session import is not implemented.
Neither a successful profile replay nor low tracking error measures capture accuracy.

## Next experiments

Supply a local Meta key and run live timing-edit evaluation. Add independently
annotated observations for capture-quality evaluation. Full-body crouching,
ground contacts, balance, perturbation recovery and game rig mapping remain
separate research milestones, not prerequisites for supported-arm authoring.
