import { createCapture } from './capture.js';
import { createComposer } from './composer.js';
import { createLibrary } from './library.js';
import { createWorkflow } from './workflow.js';
import { createStage } from './stage3d.js';
import { createWorkspace } from './workspace.js';
import { describeWorker, processVideo, setWorkerMode, workerStatus } from './jobs.js';
import {
  armPoints,
  quaternionArm,
  readAccessor,
  sampleFrames,
  sampleRig,
  sampleTranslation,
  targetPoints,
} from './motion-math.js';
import { formatSegments } from './segments.js';
const $ = id => document.getElementById(id);
let workflow = null,
  composer = null,
  library = null,
  processing = false,
  activeComposition = null;
let glbPreview = null,
  assetName = 'homunculus';
const playbackDuration = () => glbPreview?.duration || result?.playback_duration || current?.duration || 4;
const rotationAxes = ['pitch', 'yaw', 'roll'];
const rotationFields = () =>
  Object.fromEntries(
    rotationAxes.map(axis => [
      axis,
      $('rotation-' + axis).value.trim() === '' ? NaN : Number($('rotation-' + axis).value),
    ]),
  );
const rotationDirty = () =>
  !!activeCapture &&
  rotationAxes.some(axis => rotationFields()[axis] !== (activeCapture.animation_rotation?.[axis] || 0));
const dirty = () =>
  rotationDirty() ||
  !!composer?.dirty ||
  (!!current && Object.entries(fields()).some(([k, v]) => v !== (appliedFields || current)[k]));
const names = ['duration', 'shoulder_deg', 'elbow_deg', 'strength', 'damping'];
let current = null,
  appliedFields = null,
  result = null,
  gltf = null,
  characterGlb = null,
  history = [],
  redoHistory = [],
  audit = [],
  proposal = null,
  busy = false;
let activeCapture = null,
  pendingCapture = null,
  videoHash = null,
  videoURL = null,
  hashingVideo = false;
let maxDocumentBytes = 0;
fetch('/api/contracts')
  .then(r => r.json())
  .then(c => {
    maxDocumentBytes = c.max_document_bytes;
  });
let playing = true,
  cursor = 0,
  exported = false,
  replayFrames = null,
  previous = performance.now();
function fields() {
  return Object.fromEntries([
    ...names.map(n => [n, Number($(n).value)]),
    ['obstacle', $('obstacle').checked],
  ]);
}
function labels() {
  for (const n of names)
    $(n + '-value').textContent = $(n).value + (n === 'duration' ? ' s' : n.endsWith('_deg') ? '°' : '×');
}
function fill(e) {
  for (const n of names) $(n).value = e[n];
  $('obstacle').checked = e.obstacle;
  labels();
}
for (const n of names) $(n).oninput = labels;
labels();
async function api(path, data) {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  const j = await r.json();
  if (!r.ok) throw Error(j.error || 'Request failed');
  return j;
}
function lock(value) {
  busy = value;
  for (const id of [
    'apply',
    'undo',
    'redo',
    'propose',
    'accept',
    'use-fixture',
    'capture-file',
    'video-file',
    'process-file',
  ])
    $(id).disabled = value;
  $('undo').disabled = value || !history.length;
  $('redo').disabled = value || !redoHistory.length;
  for (const id of ['optimize', 'three-poses', 'save-reference', 'edit-key'])
    $(id).disabled = value || activeCapture?.retargeting !== 'spatial_arm_v1';
  $('propose').disabled = value || (!!activeCapture && activeCapture.retargeting !== 'spatial_arm_v1');
  $('video-file').disabled = value || hashingVideo;
  $('use-capture').disabled =
    value || processing || hashingVideo || !pendingCapture || !$('review-capture').checked;
  $('animation-rotation').disabled = value || processing || !activeCapture || !characterGlb;
  workflow?.sync();
}
async function simulate(
  edit,
  source = 'manual',
  remember = true,
  capture = activeCapture,
  optimize = false,
  composition = activeComposition,
) {
  if (busy || processing) return;
  lock(true);
  $('message').textContent = 'Simulating physical response…';
  try {
    const view = $('character-view').value;
    const payload = await api(optimize ? '/api/synthesize' : '/api/simulate', {
      edit,
      capture,
      physics_arm: $('physics-arm').checked,
      composition,
      ...(view === 'auto' ? {} : { view }),
    });
    if (remember) redoHistory = [];
    if (remember && current) history.push(structuredClone({ edit: current, capture: activeCapture }));
    edit = payload.result.edit;
    current = edit;
    activeCapture = capture;
    syncRotation();
    activeComposition = composition;
    composer?.applied(composition);
    pathSource = null;
    showSegments();
    result = payload.result;
    gltf = payload.gltf;
    characterGlb = payload.character_glb || null;
    cursor = 0;
    exported = false;
    replayFrames = null;
    stage?.setReplayClip(null);
    glbPreview = null;
    $('glb-close').hidden = true;
    $('export-character').disabled = !characterGlb;
    proposal = null;
    $('accept').hidden = true;
    $('proposal').textContent = '';
    $('shoulder_deg').disabled = !!capture;
    $('elbow_deg').disabled = !!capture;
    $('source-note').textContent = capture
      ? 'Captured motion drives the character. Arm physics is optional; full-body physical balance is not simulated.'
      : 'Sample supported-arm reach. Import a recording for captured body motion.';
    audit.push({ source, edit: structuredClone(edit), at: new Date().toISOString() });
    fill(edit);
    appliedFields = fields();
    $('error').textContent = result.metrics.tracking_rmse_deg.toFixed(2) + '°';
    $('contact').textContent = result.metrics.contact_steps;
    $('speed').textContent = Math.round(result.metrics.simulation_wall_s * 1000) + ' ms';
    $('message').textContent = capture
      ? 'Animation ready. Review the motion, then edit or export.'
      : 'Sample ready. Import a performance or explore the editing controls.';
    $('view-label').textContent = activeCapture ? 'Captured motion' : 'Sample arm reach';
    $('replay').textContent = 'Replay export';
    return true;
  } catch (e) {
    $('message').textContent = e.message;
    return false;
  } finally {
    lock(false);
  }
}
async function editReference(three = false, save = false) {
  if (busy || !activeCapture) return;
  lock(true);
  try {
    let payload = await api('/api/reference', {
      capture: activeCapture,
      three_poses: three,
      duration: current.duration,
    });
    if (!three && !save) {
      const key = payload.reference.keyframes[Number($('key-index').value) - 1];
      if (!key) throw Error('Keyframe number is outside this timeline');
      payload = await api('/api/reference', {
        capture: payload.capture,
        commands: [
          { operation: 'move_keyframe', targetId: key.id, parameters: { time: Number($('key-time').value) } },
          {
            operation: 'set_interpolation',
            targetId: key.id,
            parameters: { interpolation: $('key-curve').value },
          },
        ],
      });
    }
    if (save) {
      download('homunculus-reference.json', payload.capture);
      return;
    }
    lock(false);
    await simulate(
      { ...fields(), duration: payload.reference.keyframes.at(-1).time },
      'timeline edit',
      true,
      payload.capture,
    );
    $('capture-status').textContent =
      payload.reference.keyframes.length + ' editable keyframes. Save reference to retain this timeline.';
  } catch (e) {
    $('message').textContent = e.message;
  } finally {
    lock(false);
  }
}
$('three-poses').onclick = () => editReference(true);
$('save-reference').onclick = () => editReference(false, true);
$('apply').onclick = () => simulate(fields());
$('optimize').onclick = () =>
  simulate(fields(), 'bounded controller optimization', true, activeCapture, true);
$('undo').onclick = async () => {
  const e = history.at(-1),
    before = structuredClone({ edit: current, capture: activeCapture });
  if (e && (await simulate(e.edit, 'undo', false, e.capture))) {
    history.pop();
    redoHistory.push(before);
    lock(false);
  }
};
$('redo').onclick = async () => {
  const e = redoHistory.at(-1),
    before = structuredClone({ edit: current, capture: activeCapture });
  if (e && (await simulate(e.edit, 'redo', false, e.capture))) {
    redoHistory.pop();
    history.push(before);
    lock(false);
  }
};
$('propose').onclick = async () => {
  if (busy || processing) return;
  lock(true);
  $('meta-status').textContent = 'Asking Muse Spark…';
  proposal = null;
  $('accept').hidden = true;
  $('proposal').textContent = '';
  try {
    proposal = await api('/api/propose', {
      edit: fields(),
      capture: activeCapture,
      prompt: $('prompt').value,
    });
    proposal.captureBase = JSON.stringify(activeCapture);
    $('proposal').textContent = JSON.stringify(proposal.commands || proposal.edit, null, 2);
    $('accept').hidden = false;
    $('meta-status').textContent = 'Live ' + proposal.provenance.model + ' proposal. Review before applying.';
  } catch (e) {
    $('meta-status').textContent = e.message;
  } finally {
    lock(false);
  }
};
$('accept').onclick = () => {
  if (!proposal) return;
  if (
    JSON.stringify(fields()) !== JSON.stringify(proposal.base) ||
    JSON.stringify(activeCapture) !== proposal.captureBase
  ) {
    $('meta-status').textContent = 'Controls changed since this proposal. Ask again before applying.';
    return;
  }
  simulate(proposal.edit, proposal.provenance, true, proposal.capture || activeCapture);
};
function download(name, data) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('export').onclick = () => gltf && download('force-puppet-reach.gltf', gltf);
function glbBytes(b64) {
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}
$('export-character').onclick = () => {
  if (!characterGlb) return;
  const url = URL.createObjectURL(new Blob([glbBytes(characterGlb)], { type: 'model/gltf-binary' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = 'homunculus-' + (result.retarget?.character || 'character').replace(/\.glb$/i, '') + '.glb';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$('save').onclick = () =>
  result &&
  download('force-puppet-session.json', {
    edit: current,
    capture: activeCapture,
    composition: activeComposition,
    audit,
    result,
    gltf,
  });
function reviewReady() {
  lock(busy);
}
$('review-capture').onchange = reviewReady;
async function loadVideo(f) {
  if (!f) return;
  if (f.size > 100 * 1024 * 1024) {
    $('capture-status').textContent = 'Choose a video under 100 MB.';
    return;
  }
  if (videoURL) URL.revokeObjectURL(videoURL);
  videoURL = URL.createObjectURL(f);
  $('source-video').src = videoURL;
  $('source-video').hidden = false;
  $('source-pane').hidden = false;
  $('comparison').classList.add('has-video');
  document.body.classList.add('comparison-active');
  videoHash = null;
  hashingVideo = true;
  $('review-capture').checked = false;
  reviewReady();
  try {
    videoHash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await f.arrayBuffer())), b =>
      b.toString(16).padStart(2, '0'),
    ).join('');
    $('capture-status').textContent =
      pendingCapture && pendingCapture.provenance.video_sha256 !== videoHash
        ? 'Video does not match imported capture. Select the original video.'
        : 'Local video ready. Process it with the worker and import capture.json.';
  } catch (e) {
    $('capture-status').textContent = e.message;
  } finally {
    hashingVideo = false;
    reviewReady();
  }
}
function clearVideo() {
  if (videoURL) URL.revokeObjectURL(videoURL);
  videoURL = videoHash = null;
  $('source-video').removeAttribute('src');
  $('source-pane').hidden = true;
  $('comparison').classList.remove('has-video', 'show-source');
  $('compare-source').setAttribute('aria-pressed', 'false');
  document.body.classList.remove('comparison-active');
}
$('video-file').onchange = () => loadVideo($('video-file').files[0]);
$('capture-file').onchange = async () => {
  const f = $('capture-file').files[0];
  pendingCapture = null;
  $('review-capture').checked = false;
  reviewReady();
  if (!f) return;
  try {
    if (!maxDocumentBytes) throw Error('Document limits are loading; select the file again.');
    if (f.size > maxDocumentBytes)
      throw Error('Capture exceeds the ' + maxDocumentBytes + ' byte document limit.');
    const candidate = JSON.parse(await f.text());
    const checked = await api('/api/capture/validate', { capture: candidate });
    pendingCapture = candidate;
    const dimensionality =
      candidate.retargeting === 'spatial_arm_v1'
        ? '3D arm'
        : checked.metadata.max_out_of_plane_deg.toFixed(1) + ' degrees out of plane';
    $('capture-status').textContent =
      candidate.provenance.kind +
      ' / ' +
      checked.metadata.source_duration_s.toFixed(2) +
      ' s / ' +
      dimensionality +
      ' / ' +
      checked.metadata.missing_frames +
      ' missing frames' +
      (checked.body_keypoints ? ' / full body (' + checked.body_keypoints + ' keypoints)' : '') +
      '. Inspect overlays and confirm the mapping.';
  } catch (e) {
    $('capture-status').textContent = e.message;
  } finally {
    reviewReady();
  }
};
$('character-view').onchange = () => {
  if (current && !busy) simulate(current, 'recording view', false, activeCapture);
};
$('physics-arm').onchange = () => {
  if (current && !busy) simulate(current, 'physics arm toggle', false, activeCapture);
};
$('use-fixture').onclick = () => simulate(fields(), 'procedural fixture', true, null);
$('replay').onclick = async () => {
  if (!gltf) return;
  exported = !exported;
  if (exported) {
    const samplers = gltf.animations[0].samplers;
    const tracks = samplers.map(s => readAccessor(gltf, s.output, 4));
    const times = readAccessor(gltf, samplers[0].input, 1);
    replayFrames = times.map((t, i) => ({
      t: t[0],
      rotations: tracks.map(track => track[i]),
      q: tracks.map(track => 2 * Math.atan2(track[i][2], track[i][3])),
      ...quaternionArm(tracks.map(track => track[i])),
    }));
  }
  try {
    await stage?.setReplayClip(exported && characterGlb ? glbBytes(characterGlb).buffer : null);
  } catch (e) {
    exported = false;
    throw e;
  }
  $('view-label').textContent = exported
    ? 'glTF replay · decoded animation buffers' + (characterGlb ? ' (arm + character clip)' : '')
    : activeCapture
      ? 'Captured motion'
      : 'Sample arm reach';
  $('replay').textContent = exported ? 'Back to simulation' : 'Replay export';
};
$('play').onclick = () => {
  playing = !playing;
  $('play').textContent = playing ? 'Pause' : 'Play';
  $('play').setAttribute('aria-label', playing ? 'Pause playback' : 'Play playback');
};
$('timeline').oninput = () => {
  if (current) cursor = Number($('timeline').value) * playbackDuration();
};
let stage = null,
  pathSource = null;
try {
  stage = createStage($('stage'));
} catch (e) {
  $('view-label').textContent = e.message;
}
function syncPath() {
  const frames = exported ? replayFrames : result?.frames;
  if (!stage || frames === pathSource) return;
  pathSource = frames;
  stage.setPath(activeComposition ? [] : frames?.map(f => armPoints(f).hand), exported);
}

function draw(now) {
  const dt = Math.min((now - previous) / 1000, 0.1);
  previous = now;
  if (result && playing) cursor = (cursor + dt) % playbackDuration();
  let state = { obstacle: current?.obstacle ?? $('obstacle').checked, actual: null, target: null };
  if (result) {
    const frames = exported ? replayFrames : result.frames;
    const f = sampleFrames(frames, cursor);
    const original = sampleFrames(result.frames, cursor);
    if (videoURL && activeComposition?.mode !== 'sequence') {
      const video = $('source-video');
      let sourceTime = null;
      if (activeCapture && videoHash === activeCapture.provenance.video_sha256) {
        const keys = activeCapture.reference_animation?.keyframes;
        if (keys && keys.every(k => Number.isFinite(k.sourceTime))) {
          const time = (cursor / current.duration) * keys.at(-1).time;
          let i = 0;
          while (i < keys.length - 2 && keys[i + 1].time <= time) i++;
          let u = Math.max(0, Math.min(1, (time - keys[i].time) / (keys[i + 1].time - keys[i].time)));
          if (keys[i].interpolation === 'smoothstep') u = u * u * (3 - 2 * u);
          if (keys[i].interpolation === 'hold') u = 0;
          sourceTime =
            activeCapture.frames[0].t +
            keys[i].sourceTime +
            (keys[i + 1].sourceTime - keys[i].sourceTime) * u;
        } else if (!keys) {
          sourceTime =
            activeCapture.frames[0].t +
            (cursor / current.duration) * (activeCapture.frames.at(-1).t - activeCapture.frames[0].t);
        }
      }
      if (sourceTime !== null && video.readyState >= 1) {
        if (!video.seeking && Math.abs(video.currentTime - sourceTime) > 0.025)
          video.currentTime = sourceTime;
        $('sync-status').textContent =
          'Matched source ' +
          video.currentTime.toFixed(2) +
          ' s / animation ' +
          cursor.toFixed(2) +
          ' s' +
          (video.seeking ? ' / seeking' : '');
      } else {
        $('sync-status').textContent = video.error
          ? 'Source video cannot be decoded; use a browser-compatible recording'
          : video.readyState < 1
            ? 'Loading source video'
            : hashingVideo
              ? 'Checking source hash'
              : !activeCapture
                ? 'Apply a captured animation'
                : videoHash !== activeCapture.provenance.video_sha256
                  ? 'Source mismatch: playback is not synchronized'
                  : 'No source time map: playback is not synchronized';
      }
    }
    if (videoURL && activeComposition?.mode === 'sequence')
      $('sync-status').textContent =
        'Joined animation: source comparison is paused because it contains two clips.';
    state = {
      obstacle: !!current.obstacle,
      actual: armPoints(f),
      target: targetPoints(original),
      replay: exported,
      contact: !exported && !!original.contacts,
      label: glbPreview
        ? 'SAVED GLB'
        : activeComposition
          ? 'COMPOSED MOTION'
          : exported
            ? 'EXPORTED MOTION'
            : original.contacts
              ? 'CONTACT'
              : 'REACH',
      showPhysics: $('show-physics').checked,
      character: result.retarget
        ? {
            side: result.retarget.side,
            toPuppet: result.retarget.character_to_puppet,
            rotations: sampleRig(result.retarget.frames, cursor),
            bones: result.retarget.mode === 'body' ? result.retarget.bones : null,
            translationBone: result.retarget.translation_bone || null,
            translation: sampleTranslation(result.retarget.frames, cursor),
            replayTime: exported || glbPreview ? cursor : null,
          }
        : null,
    };
    $('timeline').value = cursor / playbackDuration();
    $('time').textContent = cursor.toFixed(2) + ' / ' + playbackDuration().toFixed(2) + ' s';
  }
  if (stage) {
    syncPath();
    stage.render(state);
  }
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
fetch('/api/status')
  .then(r => r.json())
  .then(s => {
    $('meta-status').textContent = 'Muse Spark · ' + s.meta;
    if (s.character && stage) {
      $('export-character').hidden = false;
      $('physics-toggle').hidden = false;
      $('view-toggle').hidden = false;
      stage
        .loadCharacter('/character.glb')
        .then(() => {
          $('character-note').textContent =
            'Character: ' +
            s.character.source +
            ' · captures with body keypoints drive the whole skeleton (tick Drive arm from physics to use the simulated arm), others drive one arm; its own proportions are kept (tick Show physics arm to compare).';
        })
        .catch(e => {
          $('character-note').textContent = 'Character failed to load: ' + e.message;
        });
    }
  })
  .catch(e => {
    $('meta-status').textContent = e.message;
  });
const initialRun = simulate(fields(), 'initial procedural fixture', false);

async function closeGlbPreview() {
  glbPreview = null;
  $('glb-close').hidden = true;
  await stage?.setReplayClip(null);
  $('view-label').textContent = activeCapture ? 'Captured motion' : 'Sample arm reach';
  cursor = 0;
  workflow.sync();
}
$('glb-close').onclick = closeGlbPreview;
async function previewGlb(item) {
  if (!stage?.hasCharacter) throw Error('Previewing a GLB needs a character rig loaded in the editor.');
  if (exported) await originalReplay();
  const blob = await fetchAsset(item.id);
  const duration = await stage.setReplayClip(await blob.arrayBuffer());
  glbPreview = { duration };
  cursor = 0;
  $('glb-close').hidden = false;
  $('view-label').textContent = 'Saved GLB · ' + item.title;
  $('message').textContent =
    'Previewing ' + item.title + '. A GLB plays back only; open its project or capture to edit.';
  workflow.close();
  workflow.sync();
  return { status: 'Previewing GLB', title: item.title, duration };
}
async function fetchAsset(id) {
  const r = await fetch('/library/file?id=' + encodeURIComponent(id));
  if (!r.ok) throw Error((await r.json()).error || 'Could not read the file');
  return r.blob();
}
function stageUpload(file) {
  const files = new DataTransfer();
  files.items.add(file);
  $('process-file').files = files.files;
  $('process-start').value = '0';
  $('process-file').dispatchEvent(new Event('change'));
  library.showImport();
  workflow.go(0);
  workflow.sync();
}
// What opening an asset means depends on its kind; the workspace applies any returned file.
async function openAsset(id) {
  let item = await api('/api/library/open', { id });
  if (item.kind === 'recording' && item.capture_id)
    item = await api('/api/library/open', { id: item.capture_id });
  if (item.kind === 'character') throw Error('The active character is set when the editor starts.');
  if (item.kind === 'animation') return { result: await previewGlb(item) };
  const blob = await fetchAsset(item.id);
  if (item.kind === 'recording') {
    stageUpload(new File([blob], item.file, { type: blob.type }));
    return { result: { status: 'Recording ready to convert', title: item.title } };
  }
  if (item.kind === 'capture' && item.video) {
    const video = await (await fetch('/clip/video')).blob();
    await loadVideo(new File([video], item.video_id.split('/').pop(), { type: video.type }));
  } else if (item.kind !== 'scene') clearVideo();
  return {
    file: new File([blob], item.file, { type: 'application/json' }),
    done() {
      if (item.kind !== 'scene') assetName = item.title;
      if (item.kind === 'capture') workflow.go(1);
      if (item.kind === 'scene') workflow.close();
    },
  };
}
async function saveAsset(name, body) {
  const item = await library.upload(name, body);
  $('message').textContent = 'Saved ' + item.title + ' to the library.';
  library.refresh();
  return { status: 'Saved to library', id: item.id, title: item.title };
}

// Manual buttons and Muse use this same action surface. No eval or DOM automation.
const originalReplay = $('replay').onclick,
  originalCharacterExport = $('export-character').onclick;
let appliedView = $('character-view').value,
  appliedPhysics = $('show-physics').checked;
async function segmentCommand(operation) {
  if (activeCapture?.retargeting !== 'spatial_arm_v1') throw Error('Load a spatial capture first');
  const payload = await api('/api/segments', { capture: activeCapture, operation });
  await requireSimulation(current, payload.capture);
  showSegments();
  return { segments: payload.segments, physicsArm: $('physics-arm').checked };
}
function syncRotation() {
  const rotation = activeCapture?.animation_rotation || {};
  for (const axis of rotationAxes) $('rotation-' + axis).value = rotation[axis] || 0;
  $('rotation-status').textContent = activeCapture
    ? `Applied: pitch ${rotation.pitch || 0}°, yaw ${rotation.yaw || 0}°, roll ${rotation.roll || 0}°.`
    : 'Open a captured animation to rotate it.';
}
function showSegments() {
  $('segment-list').textContent = formatSegments(activeCapture?.timing?.segments || []);
}
async function requireSimulation(
  edit = current,
  capture = activeCapture,
  optimize = false,
  composition = activeComposition,
) {
  if (!(await simulate(edit, 'workspace command', false, capture, optimize, composition)))
    throw Error($('message').textContent);
  appliedView = $('character-view').value;
  appliedPhysics = $('show-physics').checked;
}
async function timelineCommand(commands = null, three = false) {
  if (activeCapture?.retargeting !== 'spatial_arm_v1') throw Error('A spatial capture is required');
  const payload = await api('/api/reference', {
    capture: activeCapture,
    duration: current.duration,
    three_poses: three,
    ...(commands ? { commands } : {}),
  });
  await requireSimulation({ ...current, duration: payload.reference.keyframes.at(-1).time }, payload.capture);
  $('capture-status').textContent =
    payload.reference.keyframes.length + ' editable keyframes. Save reference to retain this timeline.';
  return { keyframes: payload.reference.keyframes.length, duration: current.duration };
}
function inspect() {
  return {
    settings: { edit: current || fields(), view: appliedView, showPhysics: appliedPhysics },
    stage: workflow?.stage || 'import',
    availableBones: result?.available_bones || result?.retarget?.bones || [],
    composition: activeComposition
      ? {
          mode: activeComposition.mode,
          bones: activeComposition.bones,
          rootMotion: activeComposition.rootMotion,
          blend: activeComposition.blend,
        }
      : null,
    playback: { playing, time: cursor, replay: exported, duration: playbackDuration() },
    characterLoaded: !!stage?.hasCharacter,
    capture: activeCapture
      ? { kind: activeCapture.provenance.kind, retargeting: activeCapture.retargeting }
      : null,
    keyframes:
      activeCapture?.reference_animation?.keyframes?.map(k => ({
        id: k.id,
        time: k.time,
        interpolation: k.interpolation,
      })) || [],
    segments: activeCapture?.timing?.segments || [],
    sourceDuration: activeCapture ? activeCapture.frames.at(-1).t - activeCapture.frames[0].t : null,
    animationRotation: { pitch: 0, yaw: 0, roll: 0, ...activeCapture?.animation_rotation },
    physicsArm: $('physics-arm').checked,
    metrics: result?.metrics || null,
    limits:
      'Captured full-body motion is kinematic. Physics and pose correction affect the supported arm only. Decorative props have no collision.',
  };
}
const workspace = createWorkspace({
  inspect,
  fields,
  pendingRotation: () => (activeCapture && rotationDirty() ? rotationFields() : null),
  download,
  busy: () => busy || processing,
  attachmentsChanged: () => composer?.refreshSources(),
  loadProject: async project => {
    if (project.schema !== 'homunculus.project.v1' || !project.capture)
      throw Error('Choose a saved animation project');
    await api('/api/capture/validate', { capture: project.capture });
    await requireSimulation(project.edit, project.capture, false, project.composition || null);
    if (project.composition?.source) {
      const item = await workspace.attach(
        new File([JSON.stringify(project.composition.source)], 'project-second-capture.json', {
          type: 'application/json',
        }),
      );
      $('composition-source').value = item.id;
    }
    workflow.go(2);
    return { status: 'Animation project restored', duration: playbackDuration() };
  },
  configureScene: settings => stage?.configure(settings),
  validate: (name, args) => api('/api/commands/validate', { name, arguments: args }),
  validateCapture: capture => api('/api/capture/validate', { capture }),
  chat: body => api('/api/chat', body),
  snapshot: () =>
    structuredClone({
      edit: current || fields(),
      capture: activeCapture,
      composition: activeComposition,
      view: appliedView,
      showPhysics: appliedPhysics,
      playing,
      time: cursor,
    }),
  restore: async value => {
    $('character-view').value = value.view;
    await requireSimulation(value.edit, value.capture, false, value.composition || null);
    $('show-physics').checked = appliedPhysics = value.showPhysics;
    playing = value.playing;
    cursor = value.time;
  },
  useVideo: loadVideo,
  openAsset,
  saveAsset,
  useCapture: async capture => {
    await api('/api/capture/validate', { capture });
    if (hashingVideo) throw Error('Wait for source video hashing');
    if (videoHash && capture.provenance.video_sha256 !== videoHash)
      throw Error('Source video mismatch: capture does not match the selected video');
    const frames = capture.frames,
      duration = capture.reference_animation?.keyframes.at(-1).time ?? frames.at(-1).t - frames[0].t;
    if (capture.retargeting === 'spatial_arm_v1')
      capture = (await api('/api/reference', { capture, duration })).capture;
    await requireSimulation({ ...fields(), duration, obstacle: false }, capture, false, null);
    return { status: 'Captured motion applied', duration };
  },
  actions: {
    list_library: async () => {
      const r = await fetch('/api/library');
      const listing = await r.json();
      if (!r.ok) throw Error(listing.error || 'Could not read the library');
      return {
        lastOpened: listing.last_opened,
        assets: listing.items.map(({ id, kind, title, created, modified, size, meta }) => ({
          id,
          kind,
          title,
          created,
          modified,
          size,
          duration: meta.duration,
        })),
      };
    },
    save_to_library: async ({ format }) => {
      if (dirty()) throw Error('Apply your changes in Edit before saving.');
      if (glbPreview) throw Error('Close the GLB preview before saving the current animation.');
      if (format === 'character') {
        if (!characterGlb) throw Error('No character export available');
        return saveAsset(assetName + '.glb', new Blob([glbBytes(characterGlb)]));
      }
      if (!activeCapture) throw Error('Open a captured animation first.');
      return saveAsset(
        assetName + '.json',
        JSON.stringify({
          schema: 'homunculus.project.v1',
          edit: current,
          capture: activeCapture,
          composition: activeComposition,
        }),
      );
    },
    navigate_stage: async ({ stage: name }) => {
      workflow.go(['import', 'review', 'edit', 'export', 'capture'].indexOf(name));
      return { stage: name };
    },
    compose_motion: async (args, source) => {
      if (!activeCapture) throw Error('Import a captured animation first.');
      const { sourceId, ...options } = args;
      await requireSimulation(current, activeCapture, false, { ...options, ...(source ? { source } : {}) });
      workflow.go(2);
      return {
        composition: inspect().composition,
        duration: playbackDuration(),
        tracks: result.retarget.bones,
      };
    },
    clear_composition: async () => {
      await requireSimulation(current, activeCapture, false, null);
      return { status: 'Full base restored' };
    },
    set_animation_rotation: async args => {
      if (!activeCapture || !characterGlb)
        throw Error('Open a captured animation with a character rig first.');
      const capture = structuredClone(activeCapture);
      capture.animation_rotation = { pitch: 0, yaw: 0, roll: 0, ...capture.animation_rotation, ...args };
      await requireSimulation(current, capture);
      return { rotation: capture.animation_rotation, pivot: 'starting hips' };
    },
    set_settings: async args => {
      const oldView = appliedView;
      if (
        activeCapture &&
        args.edit &&
        ['shoulder_deg', 'elbow_deg'].some(k => k in args.edit && args.edit[k] !== current[k])
      )
        throw Error('Captured poses own these angles; use adjust_pose instead');
      if (args.view) $('character-view').value = args.view;
      try {
        if (args.rotation && (!activeCapture || !characterGlb))
          throw Error('Open a captured animation with a character rig first.');
        const capture = args.rotation
          ? { ...structuredClone(activeCapture), animation_rotation: args.rotation }
          : activeCapture;
        if (args.edit || args.view || args.rotation)
          await requireSimulation({ ...current, ...args.edit }, capture);
      } catch (e) {
        $('character-view').value = oldView;
        throw e;
      }
      if (args.showPhysics !== undefined) $('show-physics').checked = appliedPhysics = args.showPhysics;
      return inspect().settings;
    },
    playback: async args => {
      if (args.time !== undefined && args.time > playbackDuration())
        throw Error('Seek exceeds animation duration');
      if (args.replay !== undefined && args.replay !== exported) {
        if (!gltf) throw Error('No export is available');
        await originalReplay();
      }
      if (args.playing !== undefined) playing = args.playing;
      if (args.time !== undefined) cursor = args.time;
      $('play').textContent = playing ? 'Pause' : 'Play';
      $('play').setAttribute('aria-label', playing ? 'Pause playback' : 'Play playback');
      return inspect().playback;
    },
    simulate: () => requireSimulation(),
    optimize: () => requireSimulation(current, activeCapture, true),
    use_demo: async () => {
      await requireSimulation(fields(), null, false, null);
      workflow.go(1);
    },
    edit_timeline: args => timelineCommand(args.commands),
    assemble_three_poses: () => timelineCommand(null, true),
    export_asset: async ({ format }) => {
      if (!result) throw Error('No result available');
      if (dirty()) throw Error('Apply your changes in Edit before exporting.');
      if (glbPreview) throw Error('Close the GLB preview before exporting the current animation.');
      if (activeComposition && ['arm', 'reference'].includes(format))
        throw Error(
          'This format contains only the base motion. Use character GLB or Save animation project for the composed result.',
        );
      if (format === 'arm' && Object.values(activeCapture?.animation_rotation || {}).some(v => v !== 0))
        throw Error(
          'Animation rotation is included in the character GLB. Choose character export or reset rotation for the arm-only export.',
        );
      if (format === 'arm') download('homunculus-arm.gltf', gltf);
      if (format === 'character') {
        if (!characterGlb) throw Error('No character export available');
        originalCharacterExport();
      }
      if (format === 'project')
        download('homunculus-project.json', {
          schema: 'homunculus.project.v1',
          edit: current,
          capture: activeCapture,
          composition: activeComposition,
        });
      if (format === 'session')
        download('homunculus-session.json', {
          edit: current,
          capture: activeCapture,
          composition: activeComposition,
          audit,
          result,
          gltf,
        });
      if (format === 'reference') {
        if (!activeCapture) throw Error('No captured reference');
        const p = await api('/api/reference', { capture: activeCapture, duration: current.duration });
        download('homunculus-reference.json', p.capture);
      }
      return { status: 'Download requested', format };
    },
    set_segment: async args => segmentCommand({ operation: 'set', segment: args }),
    clear_segments: async ({ ids }) => segmentCommand({ operation: 'clear', ...(ids ? { ids } : {}) }),
    adjust_pose: async args => {
      if (!activeCapture) throw Error('Load a spatial capture first');
      const payload = await api('/api/pose', { capture: activeCapture, ...args });
      await requireSimulation(current, payload.capture);
      return { status: 'Pose adjusted', keyId: args.keyId };
    },
  },
});
$('apply-rotation').onclick = () => {
  if (
    rotationAxes.some(
      axis => !$('rotation-' + axis).checkValidity() || !Number.isFinite(rotationFields()[axis]),
    )
  ) {
    $('rotation-status').textContent = 'Enter an angle from -180 to 180 degrees for every axis.';
    return;
  }
  workspace.manual('set_animation_rotation', rotationFields()).catch(() => {});
};
$('reset-rotation').onclick = () =>
  workspace.manual('set_animation_rotation', { pitch: 0, yaw: 0, roll: 0 }).catch(() => {});
for (const axis of rotationAxes) $('rotation-' + axis).addEventListener('input', () => workflow?.sync());
$('edit-key').onclick = async () => {
  try {
    const k = activeCapture?.reference_animation?.keyframes[Number($('key-index').value) - 1];
    if (!k) throw Error('Invalid key number');
    await workspace.manual('edit_timeline', {
      commands: [
        { operation: 'move_keyframe', targetId: k.id, parameters: { time: Number($('key-time').value) } },
        {
          operation: 'set_interpolation',
          targetId: k.id,
          parameters: { interpolation: $('key-curve').value },
        },
      ],
    });
  } catch (e) {
    $('message').textContent = e.message;
  }
};
$('segment-apply').onclick = async () => {
  try {
    const args = {
      id: $('segment-id').value.trim() || 'seg-' + ((activeCapture?.timing?.segments.length || 0) + 1),
      start: Number($('segment-start').value),
      end: Number($('segment-end').value),
      blend: Number($('segment-blend').value),
      curve: $('segment-curve').value,
    };
    for (const k of ['strength', 'damping'])
      if ($('segment-' + k).value !== '') args[k] = Number($('segment-' + k).value);
    await workspace.manual('set_segment', args);
  } catch (e) {
    $('message').textContent = e.message;
  }
};
$('segment-clear').onclick = async () => {
  try {
    await workspace.manual('clear_segments', {});
  } catch (e) {
    $('message').textContent = e.message;
  }
};
$('adjust-pose').onclick = async () => {
  try {
    const k = activeCapture?.reference_animation?.keyframes[Number($('key-index').value) - 1];
    if (!k) throw Error('Invalid key number');
    await workspace.manual('adjust_pose', {
      keyId: k.id,
      joint: $('pose-joint').value,
      axis: $('pose-axis').value,
      degrees: Number($('pose-angle').value),
    });
  } catch (e) {
    $('message').textContent = e.message;
  }
};
$('use-capture').onclick = async () => {
  if (!pendingCapture || !$('review-capture').checked) return;
  try {
    const file = new File([JSON.stringify(pendingCapture)], 'reviewed-capture.json', {
      type: 'application/json',
    });
    const item = await workspace.attach(file);
    await workspace.manual('use_attachment', { id: item.id });
    workflow.go(1);
  } catch (e) {
    $('message').textContent = e.message;
    $('capture-status').textContent = e.message;
  }
};
// A processed clip goes through the same attach + use_attachment path as a manual import.
async function applyClip(capture, name, reveal = true) {
  const item = await workspace.attach(
    new File([JSON.stringify(capture)], name + '-capture.json', { type: 'application/json' }),
  );
  try {
    const done = await workspace.manual('use_attachment', { id: item.id });
    if (done?.ok === false) throw Error(done.error || 'capture rejected');
  } finally {
    workspace.detach(item.id);
  }
  assetName = name;
  workflow.go(1, reveal);
}
// On load, preview the newest processed clip (or --clip) with its source video.
initialRun.then(async () => {
  const r = await fetch('/api/clip');
  if (!r.ok) return;
  const clip = await r.json();
  try {
    if (clip.video) {
      const blob = await (await fetch('/clip/video')).blob();
      await loadVideo(new File([blob], clip.video, { type: blob.type }));
    }
    await applyClip(clip.capture, clip.name, false);
    $('capture-status').textContent =
      'Previewing clip ' + clip.name + (clip.video ? ' with source video ' + clip.video : '') + '.';
  } catch (e) {
    $('capture-status').textContent = 'Clip ' + clip.name + ' failed to load: ' + e.message;
  }
});
// Submit a video to the SAM worker, follow the job, then apply the capture to the whole skeleton.
$('process-file').onchange = () => {
  $('job-status').textContent = $('process-file').files[0]
    ? 'Video selected. Choose the start time, then convert up to 30 seconds.'
    : 'Choose a video to begin.';
  workflow.sync();
};
function showWorker(status) {
  $('sam-local').checked = status.mode === 'local';
  $('sam-status').textContent = describeWorker(status);
}
workerStatus()
  .then(showWorker)
  .catch(() => {});
$('sam-local').onchange = async () => {
  const box = $('sam-local');
  const mode = box.checked ? 'local' : 'remote';
  box.disabled = true;
  $('sam-status').textContent =
    mode === 'local' ? 'Starting the local worker…' : 'Switching to the remote worker…';
  try {
    showWorker(await setWorkerMode(mode));
  } catch (e) {
    box.checked = !box.checked;
    $('sam-status').textContent = e.message;
  } finally {
    box.disabled = false;
  }
};
$('process-submit').onclick = async () => {
  const f = $('process-file').files[0];
  if (!f || !$('process-start').reportValidity()) return;
  const status = $('job-status');
  processing = true;
  workflow.sync();
  try {
    const { job, s, started } = await processVideo(f, Number($('process-start').value || 0), text => {
      status.textContent = text;
    });
    const blob = await (await fetch('/clip/video')).blob();
    await loadVideo(new File([blob], s.name + '.mp4', { type: 'video/mp4' })); // the exact video SAM ran on
    processing = false;
    await applyClip(s.capture, s.name);
    library.refresh();
    status.textContent =
      'Processed ' +
      job.seconds +
      ' s of ' +
      f.name +
      ' in ' +
      Math.round((performance.now() - started) / 1000) +
      ' s; whole skeleton retargeted. Saved as private/clips/' +
      s.name +
      '.';
  } catch (e) {
    status.textContent = e.message;
  } finally {
    processing = false;
    lock(false);
    workflow.sync();
  }
};

// A recorded take is converted exactly like a chosen file, with the same progress and retry in Import.
const capture = createCapture(
  file => {
    stageUpload(file);
    $('process-submit').click();
  },
  file => library.upload(file.name, file),
  async () => {
    const status = await workerStatus();
    return status.reachable
      ? 'GPU worker is ready to convert takes.'
      : 'GPU worker is not reachable. Takes still save to the Library; convert them once it is back.';
  },
);
library = createLibrary({
  open: id => workspace.manual('open_library_asset', { id }),
  showExport: () => workflow.go(3),
});
workflow = createWorkflow(
  () => ({
    capture: activeCapture,
    duration: playbackDuration(),
    dirty: dirty(),
    busy,
    processing,
    character: !!characterGlb,
    ready: !!result && !glbPreview,
    preview: !!glbPreview,
  }),
  name => workspace.manual('navigate_stage', { stage: name }).catch(() => {}),
  (open, name) => {
    capture.setActive(open && name === 'capture');
    if (open && name === 'import') library.refresh();
  },
);

composer = createComposer(workspace, () => ({ refresh: () => workflow.sync() }));
$('save-project').onclick = () => workspace.manual('export_asset', { format: 'project' }).catch(() => {});
$('project-file').onchange = async () => {
  const file = $('project-file').files[0];
  if (!file) return;
  try {
    const item = await workspace.attach(file);
    await workspace.manual('use_attachment', { id: item.id });
  } catch (e) {
    $('project-status').textContent = e.message;
  } finally {
    $('project-file').value = '';
  }
};
