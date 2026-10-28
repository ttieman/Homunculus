# Model integration policies

Checked 2026-10-26/27. These are implementation proposals, not model benchmarks.
The proposals below preserve the original dated research. Current status is in
[STATUS.md](STATUS.md): SAM inference and weight download have occurred; Spark
adapters are implemented, but live API verification is still pending. Public catalog availability, account access and event eligibility are
independent. No hosted model subscription or paid infrastructure was purchased.

## Shared contract and evaluation rules

Every policy below inherits these requirements: retain source/model/version,
input provenance and units; show a preview; validate before applying; record the
prior state for undo. Models cannot execute arbitrary code or emit per-frame
torques into the simulator. Unsupported/ambiguous requests ask for refinement;
refusals, timeouts, malformed outputs and missing access leave state unchanged.
Never substitute fixtures for real inference. Fixtures only test adapters.

The selected editor contract is `Edit`: duration seconds [2,30], shoulder degrees
[5,100], elbow degrees [-100,30], strength [.1,2], damping [.2,3], obstacle boolean.
All numbers must be finite. These are complete-clip controls, not regional edits.
Use manual controls as ground truth for the equivalent language operations.

Proposed command evaluation: 20 cases (8 single edits, 6 combined, 3 ambiguous,
3 unsupported). Record exact semantic correctness, rejection quality, latency,
corrections and cost. Initial adoption target: >=18/20 correct, zero unsafe
applications, p95 <=10 seconds. These are workflow targets, NOT measured claims.
Any latency estimate below is a testing budget, not observed model speed.

## 1. Muse Spark — IMPLEMENTED ADAPTERS (live evaluation pending)

- **Problem/capability:** typed direction -> previewable control changes.
- **Evidence:** official catalog documents tool use; animation-edit quality is a hypothesis.
- **Options:** one hosted tool call (selected), versus reference-library selection later; ordinary sliders remain the baseline.
- **I/O:** prompt + current Edit -> complete `propose_edit` arguments + response ID; no physical state mutation until review.
- **Execution:** interactive server-side HTTPS, 45-second timeout, no local GPU. Start `muse-spark-1.3`; compare `muse-spark-1.2`/`muse-spark-1.1` only if access or measured cost warrants.
- **Authority/failure:** shared contract; invalid/incomplete/no/multiple tool calls are rejected. Secrets stay in server environment.
- **Experiment/adoption:** shared 20-case set, manual baseline, 1–2 hours estimated plus API charges (not yet authorized or incurred). Require real output to demonstrably change motion.
- **Dependencies:** Model API account/key and API terms; event explicitly names Spark. Endpoint documented; account entitlement unverified. Adapter implemented; live test BLOCKED.

## 2. Muse Wonder — DEFER (medium)

- **Problem/capability:** diagnose difficult tracking failures -> proposed corrective edit and rationale.
- **Evidence/hypothesis:** reasoning documented; reliable physical diagnosis untested.
- **Options:** `muse-wonder-1.0` over hosted API, or use Spark plus deterministic diagnostics first.
- **I/O:** metrics with units + selected frames -> cited diagnosis + validated Edit; no solver or torque ownership.
- **Execution/failure:** background hosted request, timeout without changes; shared refusal/validation rules. Wonder Full is a Muse Code-only option, not a presumed endpoint.
- **Experiment/adoption:** same 10 labelled failures for Spark/Wonder, 2-hour test budget; adopt only >=2 additional correct useful diagnoses with tolerable latency/cost. No benchmark run.
- **Dependencies:** account/API terms; event-listed, access absent. Adds little before a useful baseline exists.

## 3. Muse Image — DEFER (high)

- **Problem/capability:** communicate performance intent -> labelled storyboard image.
- **Evidence/hypothesis:** image generation/editing documented; improved authoring efficiency untested.
- **Options:** `muse-image-1.0` hosted image job, or ordinary target-rig preview (preferred now).
- **I/O:** text + approved reference image -> image URI, prompt/model provenance, explicitly non-measured reference.
- **Execution/authority/failure:** offline generation; cannot create motion measurements or colliders. Missing image/refusal/timeout leaves scene intact; preview and discard supported.
- **Experiment/adoption:** five ambiguous direction examples with/without storyboard, 2-hour budget; adopt only if fewer clarification rounds without misleading anatomy. No numeric quality score invented.
- **Dependencies:** API access/terms, image rights; explicitly event-listed. Not necessary for contact/export proof.

## 4. SAM 3.1 — EXPERIMENT after capture (medium)

- **Problem/capability:** isolate the intended performer/prop -> masks and identity tracks.
- **Evidence/hypothesis:** segmentation/tracking documented; downstream pose improvement untested.
- **Options:** hosted `sam-3.1`, versus Body estimator's detection path or manual crop.
- **I/O:** approved frames/video + object prompt -> masks, boxes, frame times/IDs; pixel space, not skeletal rotations.
- **Execution/authority/failure:** offline perception job; select crop/identity only. No implied force or depth. Missing identities flag frames rather than interpolate silently.
- **Experiment/adoption:** 3 short clips (clear, cluttered, occluded), compare pose dropout/jitter with identical Body backend; half-day estimated. Adopt if useful improvement outweighs extra processing and annotation.
- **Dependencies:** API terms/access, video permission; event-listed. No uploads performed.

## 5. Muse Code — DEFER (high; development only)

- **Problem/capability:** help implement adapters -> reviewable code diffs and executed checks.
- **Evidence/hypothesis:** coding tool documented; speed/quality for this project unmeasured.
- **Options:** developer-invoked Muse Code versus current development tools. Not a shipped authoring model.
- **I/O:** bounded source context/task -> diff, command log, tests; no authority over secrets, deployments or unrelated repos.
- **Execution/failure:** development session; broken build or unavailable account leaves a reviewed checkpoint, not a success claim.
- **Experiment/adoption:** one adapter task compared with manual implementation, 2-hour budget; adopt if verified time saved without regressions. No model-count credit claimed.
- **Dependencies:** installation/account/product terms; organizer names it, but development-only use does not meet this project's intended user-facing Meta role. Not used here.

## 6. Muse Glimmer — EXPERIMENT later (low)

- **Problem/capability:** private/offline commands -> same bounded Edit.
- **Evidence/hypothesis:** local text/image inference documented; fit and command quality on these machines not established.
- **Options:** compatible local quantized checkpoint, or hosted Spark; deterministic controls remain fallback visible to user.
- **I/O/authority:** shared Edit contract and provenance including exact weight revision/quantization; never silently replace Spark.
- **Execution/failure:** isolated worker, wait for current GPU job to finish; OOM/unavailable weights is a failed experiment. Exact variant and license review remain prerequisites, not guessed.
- **Experiment/adoption:** shared command set, measure peak VRAM, latency and correctness; half-day setup budget. Require no OOM and >=18/20 correctness before adopting.
- **Dependencies:** runtime compatibility, checkpoint-specific terms and access. Broad open-weight event category; individual qualification unresolved. Current worker is busy.

## 7. Muse Spark Open — REJECT local hosting; DEFER provider (high)

- **Problem/capability:** alternate deployment for authoring -> same proposals.
- **Evidence/hypothesis:** open-weight release documented; useful cost/deployment advantage untested.
- **Options:** provider-hosted model with exact provider ID recorded before test, versus selected hosted Spark. No consumer-GPU deployment is selected.
- **I/O/authority/failure:** shared command contract; explicit provider provenance, timeout/rejection leaves edits unchanged.
- **Execution:** provider request only after verified access/terms. Current two GPUs do not justify a local large-model hosting project.
- **Experiment/adoption:** shared 20 cases, 2-hour test after access; adopt only on demonstrated cost/privacy/control benefit at comparable quality.
- **Dependencies:** provider credentials, checkpoint license and event open-weight wording. Exact checkpoint/provider ID unresolved; no download or claimed performance.

## 8. SAM 3D Body — OPERATIONAL EXPERIMENT (accuracy unmeasured)

- **Capability:** image/video pose estimates supply spatial-arm reference motion.
- **Selected implementation:** approved DINOv3 checkpoint and MHR asset in the isolated Linux runtime; fixed user-reviewed person crop; named MHR70 shoulder/elbow/wrist keypoints; full numeric output retained privately.
- **Authority:** estimated directions only. Default camera is uncalibrated; body proportions and root are normalized to the supported rig. No ground-truth human forces or direct MHR-to-game rotation equivalence is claimed.
- **Measured evidence:** one owned 14.55-second capture, 195 observations in the original sampler, 161.65-second worker time excluding model load, 3.79 GB peak allocated GPU memory. See SYNTHESIS.md for revision, warnings and scope. Subsequent sampler fixes are regression-tested separately.
- **Remaining evaluation:** independently annotated clear, sideways, cropped and occluded examples; separate reconstruction accuracy, cleanup error, controller tracking and export fidelity. Quality tooling is implemented but no calibrated accuracy benchmark is claimed.
- **Dependencies/status:** approved weights and runtime are operational. Licenses remain separate from project MIT licensing. No weights or private recording are redistributed. Contest qualification remains unresolved; successful technical use is not organizer approval.

## 9. SAM 3D Objects — DEFER (high)

- **Problem/capability:** reference prop -> draft scene geometry.
- **Evidence/hypothesis:** object reconstruction documented; scale/contact suitability untested.
- **Options:** official reconstruction job versus manually sized box (selected baseline).
- **I/O:** image/mask -> mesh, source attribution, scale status and simplified collision proxy; mass/friction require explicit values.
- **Execution/authority/failure:** offline job; preview only, no automatic replacement of physical collider. Bad topology, unavailable weights or unknown scale leave the primitive in place.
- **Experiment/adoption:** compare 3 props against known dimensions and manual modelling time, one-day estimate; adopt if faster staging with acceptable user-verified collision proxies.
- **Dependencies:** official checkpoint/license review and access, approved imagery. Exact weight revision unresolved; eligibility UNKNOWN. No reconstruction attempted.

## 10. Llama — DEFER (medium)

- **Problem/capability:** small local command interpretation -> shared Edit.
- **Evidence/hypothesis:** candidate `meta-llama/Llama-3.2-3B-Instruct` is a specific text alternative; edit correctness not measured.
- **Options:** approved original weights with a supported local runtime, or separately attributed quantization. Compare with Glimmer/Spark; do not integrate three command servers.
- **I/O/authority/failure:** text/current controls -> validated proposals, weight revision recorded; shared rejection/undo rules, no unlabelled provider fallback.
- **Execution:** worker after completion of existing job; memory/latency must be measured. No claim based solely on parameter count.
- **Experiment/adoption:** shared 20 cases, half-day estimated deployment/test budget; adopt only if offline value and correctness justify it.
- **Dependencies:** Llama 3.2 license/access and exact revision, compatible inference runtime. Broad event category is not individual approval. Current worker's Qwen is not a Meta substitute.

## 11. Meta open-weight category — classification, not another integration

Evaluate specific releases above. No blanket compatibility, license or eligibility
inference applies to all models. Exact deployment artifacts must be selected
before claiming any live result. No separate model-count target exists.

## Sources and unresolved checks

- [Official model catalog](https://dev.meta.ai/docs/models): named capabilities/IDs.
- [Chat Completions](https://dev.meta.ai/docs/protocols/chat-completions): adapter protocol.
- [Organizer](https://events.cerebralvalley.ai/e/meta-ai-developer-hackathon): named models and open-weight category, not account access.
- [SAM Body setup](https://github.com/facebookresearch/sam-3d-body/blob/main/INSTALL.md): gated weights and environment.
- [SAM Objects](https://github.com/facebookresearch/sam-3d-objects): reconstruction candidate.
- [Llama model family](https://github.com/meta-llama/llama-models/tree/main/models/llama3_2): candidate release/terms.
- [Kinesia](https://github.com/flyaurelien/kinesia): community temporal-pipeline precedent; not locally reproduced or copied.

License status: no model weights redistributed; hosted terms must be reviewed by
the account holder during onboarding. Open-weight model and asset licenses are
not inherited from this repository's MIT license. No official SAM 3D contest
answer was obtained. Live benchmarks, pricing and quota checks are still NOT RUN.
