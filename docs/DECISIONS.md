# First feasibility slice — 2026-10-26

Selected: hybrid authoring, beginning with an original synthetic reach, conventional
torque control in MuJoCo, manual edits, a Spark edit adapter, and glTF export.
This is a supported two-joint arm attached to a fixed shoulder, not free-standing
balance. The fixture is deliberately visible. No game assets are redistributed.

| Route | First result | Main uncertainty | Decision |
|---|---|---|---|
| Reference-first | SAM frame to retargeted pose | Gated weights, temporal consistency and MHR mapping | Next experiment after access |
| Language-first | Spark changes typed reach parameters | Actual edit correctness and API access | Implement adapter, do not fake responses |
| Hybrid | Known motion, manual/language revisions, physical bake | Contact/tracking quality | Selected incremental direction |

| Controller | Evidence inspected | Decision |
|---|---|---|
| Conventional bounded joint torques | MuJoCo Python binary distribution; CPU simulation | Selected for a measured contact/export baseline |
| PHC | Official setup needs Isaac Gym, Python 3.8, SMPL assets and checkpoints; coordinate conversion documented | Defer original-checkpoint experiment to Linux; no reproduction claimed |
| MaskedMimic/ProtoMotions | SMPL model card and pretrained guide specify IsaacLab runtime; separate model/asset terms | Strong whole-body candidate; do not transplant its policy into MuJoCo |
| Offline optimization | Contact/trajectory refinement precedents in supplied handoff | Defer: does not answer interactive contact uncertainty first |

The browser is an editor/replay surface; Python owns physics and inference. A Bevy
extension would best integrate existing rigs but introduces the current pinned
engine/fork build and mixed working tree. Blender is useful for later retargeting;
neither its UI nor a new native editor is required to isolate this first question.

Model selection: Spark 1.3 for meaningful bounded authoring (blocked on access),
SAM 3D Body for subsequent reference capture (blocked on weights). Other models
are evaluated in MODEL_POLICIES.md. No external generative model substitutes for Meta.

Evidence: [Meta models](https://dev.meta.ai/docs/models),
[event](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon),
[PHC](https://github.com/ZhengyiLuo/PHC),
[ProtoMotions checkpoints](https://nvlabs.github.io/ProtoMotions/getting_started/pretrained_models.html),
[SAM setup](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md),
[MuJoCo Python](https://mujoco.readthedocs.io/en/stable/python.html).

Hardware observed: Windows, Python 3.13.1, RTX 3060 Ti 8192 MiB. Linux compute
worker: RTX 2060 12288 MiB, 417 MiB free; 15934 MiB RAM, 2734 MiB available,
1318 MiB swap used. Existing inference service active. User permits takeover
after its current work finishes; do not interrupt it on an idle-slot assumption.

Existing game inspected read-only: Bevy =0.20.0, Jackdaw f3df43c and Avian
252aac4; glTF Scene loading and AnimationGraph clip playback, Y-up metre-based
stickman rig. Our new arm rig is not mapped to that skeleton. Game replay remains
UNVERIFIED even if generic glTF replay passes.

2026-10-27 update: SAM inference is operational. See SYNTHESIS.md for the additive spatial/timeline architecture, real-video experiment and current limitations. Earlier blocked-access and wait-for-worker statements are historical; the user explicitly authorized stopping the running compute job.
