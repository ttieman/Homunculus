# Character GLB export and Bevy preview

The loop uses the same /api/simulate handler as the browser editor, saves its
character_glb response, decodes every exported channel, and loads that exact
file into Bevy Playground's independent homunculus_preview example.

## Export a saved full-body capture

From the Homunculus root, using a Python environment with requirements.txt:

```powershell
python scripts/export_preview.py path/to/capture.json --character C:/path/to/stickman.glb --output private/exports/my-clip
```

This writes animation.glb and export-review.json. The GLB contains the character
mesh, skin, materials and a single Homunculus_Body animation: 19 rotation tracks
and pelvis translation. Original character clips are omitted. --physics-arm
explicitly substitutes the simulated arm; the default follows the recording.
The metadata now records this selection accurately.

The exporter uses a temporary loopback editor server and shuts it down after
the request. It does not read .env files or change a running editor. It uses the
saved capture's reference timing/segments when present, default gains, and no
obstacle. Unsaved browser edits are not included; save the edited reference
first to review those changes.

## Run in Bevy Playground

From the Bevy Playground root:

```powershell
./tools/preview-homunculus.ps1 -ExportDirectory C:/path/to/homunculus/private/exports/my-clip
```

Controls: Space pauses/resumes; R restarts; 1/2/3 select 0.5x/1x/2x speed;
arrow keys orbit; +/- zoom; Escape closes. The window title shows playback
time. Preview looping does not blend the end back into the beginning.

Add -Audit to compare five sampled poses against the export report inside
Bevy, save bevy-review.json and bevy-pose-0.png through bevy-pose-4.png, and exit.
The audit requires all 19 named bones, quaternion component error below 1e-4,
pelvis error below 0.1 mm, and matching clip duration. It checks loaded animation
evaluation; screenshots still need visual inspection. Keep the report paired
with its exact GLB. All generated media remains under the ignored export folder.

## Validation boundaries

Export fidelity is separate from capture accuracy and animation quality.
Kinematic in-place motion has no foot-contact correction or full-body balance.
The recorded performance may not loop seamlessly. The preview uses the normal
Bevy GLB loader and animation graph, without the playground's locomotion or
physics systems changing the pose.

The 2026-10-29 case is the latest saved full-body capture
20261028-210430-2026-10-28_21-01-01: 383 source frames, 25.5 seconds, 1,276
export frames. Generated evidence is in private/exports/20261029-latest-body/.
Export decoding error was below 3e-8 for quaternion components and pelvis
translation in metres. The raw loop boundary differs by up to 18.8 degrees;
toe joint origins reach about 4.3 cm below nominal floor (not a mesh-contact
measurement). No motion cleanup was applied to hide either limitation.

Source-video inspection: sampled frames crop out the legs, and standing frames
also crop the head. Those joints are model estimates, not visually observed
full-body motion. This recording tests the export loop; it is not a reliable
full-body accuracy benchmark.

Bevy 0.20.0 validation passed on 2026-10-29: all 19 rotations and pelvis
translation matched at 0, 6.38, 12.76, 19.12 and 25.5 seconds (zero component
difference after conversion to f32). Duration was 25.5 s. All five engine
screenshots were inspected; the skin rendered and seated, standing and
reaching poses changed as expected. This is sampled engine validation, not
a claim of full-frame capture accuracy or user acceptance.

Reviewed GLB SHA-256: 878d0ef6c25926d4ec14977522568910506ad52fd30e879c6c2d329f8a27b256

Focused regression checks: 32 body/character tests passed, including both arm
driver modes. No live Muse call or new GPU capture was required.
