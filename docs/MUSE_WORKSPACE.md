# Muse workspace controls — 2026-10-28

Reviewed Claude's local branch through f12bcdf (three.js, external GLB retarget,
recording-view mapping). Imported those commits without changing that checkout.
The optional character uses the existing bone contract and preserves its own
proportions. It is still a single supported arm; the rest of the body is at rest.

## Review findings and changes

* Muse previously returned one motion proposal, without workspace inspection,
  action execution receipts, scene configuration or chat media. The new chat
  loop exposes the same command dispatcher used by manual controls.
* Recording-view and scene changes needed shared undo. Workspace snapshots now
  retain the reference, motion settings, view, physics overlay and visual scene.
* Character export replay loaded asynchronously without reporting failures to
  the caller. The command now awaits the replay load.
* Switching captured sides could leave the previously driven arm posed. The
  renderer now restores the inactive arm's rest rotations.
* Capture timing was editable but local poses were not. `adjust_pose` adds a
  bounded local-axis rotation to a selected reference key, uses copy-on-write
  for shared poses, and validates the resulting timeline and supported rig.

## Components

`homunculus/editor/commands.py` is the typed tool catalog and strict argument validator. Both UI
and Muse execute through `web/workspace.js`; it calls the validator, dispatches
known handlers, records undo and returns success/error receipts. `homunculus/muse/chat.py`
issues one Meta Chat Completions request. The browser appends the complete model
message and matching tool receipts before requesting the next turn. It caps
the loop at eight turns, rejects stale responses after manual changes, and
supports stopping between requests/actions. Commands cannot execute code,
arbitrary URLs, shell processes or filesystem paths.

Use the Command inspector to exercise the exact same tools without model
inference. Manual controls and chat can inspect the workspace, change motion
settings, choose recording views, configure scene/light/camera/props, play/seek,
simulate, optimize, edit timing, adjust poses, assemble three poses, undo/redo,
use attached media and export arm/character/reference/session/scene assets.

Scene props are decorative, not collision bodies. The original obstacle toggle
controls physics. Save scene creates a portable JSON document; attach it to
reload. Captures/media are not embedded in scene saves. Camera presets are
saved; arbitrary mouse orbit/pan positions are not yet persisted.

## Media and access

Chat supports file selection, drag/drop and pasted images. Images (PNG/JPEG/
WebP/GIF; at most four per turn, 1.4 MB each) are sent to Meta only on Send.
Videos (100 MB maximum) remain local preview sources. Capture JSON uses the
existing validator; scene JSON uses the command schemas. The model receives
attachment IDs/names/types, key IDs/times and metrics rather than source video
bytes, raw captures or credentials. Media contents are untrusted data.

An attached video does not start a SAM job. Run the offline capture worker,
then attach its capture JSON. No generic file chooser or privileged computer
control is exposed to Muse. Source/video hash mismatch blocks captured playback.
Playback and source-media selection are not durable asset history.

Actual hosted inference requires locally configured MODEL_API_KEY. Fixture
responses in tests validate the tool protocol, not live Muse quality/access.
No model response is fabricated when credentials are absent.

Official protocol references:
https://dev.meta.ai/docs/cookbook/tool-function-calling
https://dev.meta.ai/docs/image-understanding
