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
placing keys in source, screenshots, chat, shell history or public issues. No
credential file is needed. Restart the server after changing its environment.

The implemented adapter uses `muse-spark-1.3` at
`https://api.meta.ai/v1/chat/completions`. It sends only the direction and current
controls, and expects one `propose_edit` tool call. Example: “Make this six seconds
long and reduce strength to 0.4.” Review its complete proposed controls before
applying. It cannot yet edit a time interval, load a reference video or direct a
full-body rig. Unsupported requests should be rejected, not approximated silently.

The user confirmed credentials are not configured. A fixture parsing test exists;
it is not a live-model evaluation. Account access, endpoint response behaviour,
latency and semantic accuracy remain BLOCKED/UNVERIFIED.

## Compute worker

The existing Linux worker has a 12 GB RTX 2060 and a working SSH connection.
The running inference service occupied ~11 GB and was actively processing during
inspection. User authorized takeover **after current work completes**. No service
was stopped or disabled. Determine job-level completion, not just a momentary idle
slot, before reallocating its GPU. Keep local connection details out of this public repo.

Once free, create an isolated environment for SAM 3D Body, obtain approved weights,
record exact revisions and run its original single-image example first. Do not
download large optional stacks or interrupt other services merely to prepare this
baseline. Keep any source recording private unless explicitly approved for publication.

## Next bounded experiment

1. Configure Spark and run the 20-case authoring evaluation in MODEL_POLICIES.md.
2. Request SAM 3D Body weight access. After worker completion, run a known image,
   then a short owned reach clip; inspect raw MHR outputs before retargeting.
3. Map one arm chain, documenting rest frames and scale, then compare captured
   versus synthetic input under the same controller.
4. Retarget/bake to the actual game skeleton and test Bevy playback separately.

For full-body work, reproduce PHC or MaskedMimic in its documented original
runtime first. Current conventional arm results are not evidence that whole-body
balance, learned-policy portability or game integration works.
