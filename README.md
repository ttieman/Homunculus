# Homunculus

An experimental animation-authoring workspace: direct a physical character,
refine its performance, and export the motion. **Homunculus** is the first
feasibility experiment within Homunculus.

![Supported physical reach editor](docs/evidence/editor.png)

**Current delivery:** planar and spatial supported-arm synthesis with obstacle contact,
manual timing/strength/pose edits, undo, glTF export and independent replay.
MuJoCo owns the simulation. SAM video observations drive spatial reference motion; the original procedural reach remains available.

**Meta integration:** a real Muse Spark adapter proposes validated edits through
the same controls. Live inference is blocked until API access is configured;
there are no fabricated model responses. SAM 3D Body has processed an owned video on the Linux GPU worker. Temporal cleanup, spatial retargeting, bounded controller search and physical glTF baking are implemented; see [synthesis](docs/SYNTHESIS.md) and [video capture instructions](docs/CAPTURE.md).
This is not yet the complete
Meta-powered product, a full-body controller, or a game-ready retargeted clip.

See [current capabilities and contracts](docs/STATUS.md) for spatial limits,
asset replay and quality-evaluation boundaries.

## Run

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe server.py
```

Open **http://127.0.0.1:8765**. On Linux, substitute `.venv/bin/python`.

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe measure.py
```

Measurements and original-motion exports are written to ignored `outputs/`.
Published baseline evidence is in [docs/evidence](docs/evidence/).

## What to try

1. Watch the green arm meet the obstacle while the dotted target continues.
2. Remove the obstacle and simulate again to compare the free reach.
3. Increase duration or reduce strength, simulate, then undo.
4. Export glTF and switch to export replay. This replays the actual physics result.
5. After configuring Meta access, ask Spark for a bounded edit, review it and apply.

The shoulder is fixed to the world; the surrounding body silhouette is scenery.
No free-standing balance or human muscle-force reconstruction is claimed.

- [Setup and next experiment](docs/SETUP.md)
- [Video to physical arm](docs/CAPTURE.md)
- [Selected architecture and hardware inventory](docs/DECISIONS.md)
- [Policies for every candidate model](docs/MODEL_POLICIES.md)
- [Measured results and limitations](docs/EXPERIMENTS.md)

Source code uses this repository's existing MIT license. MuJoCo, model weights,
datasets and any future third-party rigs retain their own terms. No private game
assets, source recordings, credentials or model weights are included.
