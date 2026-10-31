// Record a take from a connected camera in the browser. Nothing leaves the machine until
// the user converts the take, which hands it to the same upload path as a chosen video file.
const MAX_SECONDS = 30; // worker limit per clip
const MIN_SECONDS = 2.1; // shortest clip the worker accepts

const CAMERA_ERRORS = {
  NotAllowedError: 'Camera access was blocked. Allow it in the browser address bar, then try again.',
  NotFoundError: 'No camera was found. Connect one, then try again.',
  NotReadableError: 'The camera is in use by another application. Close it, then try again.',
  OverconstrainedError: 'That camera is no longer available. Choose another one.',
};

export function createCapture(onTake, onSave, workerNote) {
  const $ = id => document.getElementById(id);
  const say = text => ($('camera-status').textContent = text);
  const overlay = text => ($('capture-overlay').textContent = text);
  let stream = null,
    recorder = null,
    wanted = true,
    active = false;
  let countdown = null,
    ticker = null,
    limit = null,
    startedAt = 0,
    take = null;
  let takes = [],
    nextTake = 1; // this session's takes, newest first; `take` is the one being reviewed

  function render() {
    const recording = !!recorder,
      counting = countdown !== null;
    document.body.dataset.recording = String(recording);
    $('capture-enable').hidden = !!stream;
    $('capture-live-area').hidden = !stream;
    $('capture-camera').disabled = recording || counting;
    $('capture-countdown').disabled = recording || counting;
    $('capture-record').textContent = recording ? 'Stop recording' : counting ? 'Cancel countdown' : 'Record';
    $('capture-record').classList.toggle('recording', recording);
    $('capture-take').hidden = !take;
    $('capture-use').disabled = !take || take.seconds < MIN_SECONDS;
    $('capture-takes').replaceChildren(
      ...takes.map(t => {
        const row = document.createElement('button');
        row.type = 'button';
        row.className = 'capture-take-row';
        row.setAttribute('aria-pressed', String(t === take));
        row.textContent = `Take ${t.number} · ${t.seconds.toFixed(1)} s · ${t.saved}`;
        row.onclick = () => {
          select(t);
          render();
        };
        return row;
      }),
    );
  }

  async function listCameras() {
    const box = $('capture-camera'),
      current = box.value;
    const cameras = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'videoinput');
    box.replaceChildren(...cameras.map((d, i) => new Option(d.label || 'Camera ' + (i + 1), d.deviceId)));
    if (cameras.some(d => d.deviceId === current)) box.value = current;
  }

  function release() {
    stream?.getTracks().forEach(t => t.stop());
    stream = null;
    $('capture-live').srcObject = null;
  }

  async function connect(deviceId) {
    if (!navigator.mediaDevices?.getUserMedia) return say('This browser cannot access cameras.');
    release();
    try {
      const next = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          width: { ideal: 1280 },
          height: { ideal: 720 },
          ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        },
      });
      if (!wanted || !active) return next.getTracks().forEach(t => t.stop()); // panel closed while waiting
      stream = next;
      stream.getVideoTracks()[0].addEventListener('ended', () => {
        if (recorder) recorder.stop();
        release();
        render();
        say('The camera disconnected. Any recording so far was kept.');
      });
      $('capture-live').srcObject = stream;
      await listCameras();
      $('capture-camera').value =
        stream.getVideoTracks()[0].getSettings().deviceId ?? $('capture-camera').value;
      say('Camera ready. Step back until your whole body is in frame.');
    } catch (e) {
      say(CAMERA_ERRORS[e.name] || 'Could not open the camera: ' + e.message);
    }
    render();
  }

  function clearTimers() {
    clearInterval(ticker);
    clearTimeout(limit);
    ticker = limit = null;
  }

  function select(t) {
    take = t;
    if (t) $('capture-playback').src = t.url;
    else $('capture-playback').removeAttribute('src');
  }

  function removeTake() {
    URL.revokeObjectURL(take.url);
    takes = takes.filter(t => t !== take);
    select(takes[0] || null);
  }

  async function saveTake(t) {
    if (t.seconds < MIN_SECONDS) t.saved = 'too short, not saved';
    else {
      t.saved = 'saving…';
      render();
      try {
        await onSave(t.file);
        t.saved = 'in Library';
      } catch (e) {
        t.saved = 'not saved: ' + e.message;
      }
    }
    render();
  }

  function startRecording() {
    const type = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(t =>
      MediaRecorder.isTypeSupported(t),
    );
    const chunks = [],
      rec = new MediaRecorder(stream, type ? { mimeType: type } : {});
    rec.ondataavailable = e => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      const seconds = (performance.now() - startedAt) / 1000;
      clearTimers();
      recorder = null;
      const stamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
      const file = new File(chunks, `capture-${stamp}.webm`, { type: 'video/webm' });
      const finished = { file, seconds, number: nextTake++, url: URL.createObjectURL(file), saved: '' };
      takes.unshift(finished);
      select(finished);
      overlay('');
      say(
        seconds < MIN_SECONDS
          ? `This take is ${seconds.toFixed(1)} s. Clips need at least ${MIN_SECONDS} s to convert.`
          : `Recorded ${seconds.toFixed(1)} s. Record another or convert this one.`,
      );
      saveTake(finished);
      $('capture-use').scrollIntoView({ block: 'nearest' });
      if (!active && !recorder) release();
    };
    recorder = rec;
    startedAt = performance.now();
    rec.start(1000);
    ticker = setInterval(() => {
      const elapsed = ((performance.now() - startedAt) / 1000).toFixed(0);
      say(`Recording ${elapsed} / ${MAX_SECONDS} s`);
      overlay(`● ${elapsed} s`);
    }, 250);
    limit = setTimeout(() => recorder?.stop(), MAX_SECONDS * 1000);
    say(`Recording 0 / ${MAX_SECONDS} s`);
    render();
  }

  function cancelCountdown(message) {
    clearInterval(countdown);
    countdown = null;
    overlay('');
    say(message);
    render();
  }

  $('capture-enable').onclick = () => {
    wanted = true;
    connect();
  };
  $('capture-camera').onchange = () => connect($('capture-camera').value);
  $('capture-record').onclick = () => {
    if (recorder) return recorder.stop();
    if (countdown !== null) return cancelCountdown('Countdown cancelled.');
    let left = Number($('capture-countdown').value);
    if (!left) return startRecording();
    say(`Recording in ${left}…`);
    overlay(left);
    countdown = setInterval(() => {
      left -= 1;
      if (left > 0) {
        overlay(left);
        return say(`Recording in ${left}…`);
      }
      overlay('');
      clearInterval(countdown);
      countdown = null;
      startRecording();
    }, 1000);
    render();
  };
  $('capture-discard').onclick = () => {
    removeTake();
    say('Removed from this session. Saved takes stay in the Library.');
    render();
  };
  $('capture-download').onclick = () => {
    const a = document.createElement('a');
    a.href = take.url;
    a.download = take.file.name;
    a.click();
  };
  $('capture-use').onclick = () => onTake(take.file);
  navigator.mediaDevices?.addEventListener?.('devicechange', () => stream && listCameras());
  document.addEventListener('keydown', e => {
    if (e.code !== 'Space' || !active || !stream || e.repeat) return;
    if (e.target.closest('input, textarea, select, button:not([data-step]), video, summary, dialog')) return; // the tab keeps focus after opening the panel
    e.preventDefault();
    $('capture-record').click();
  });
  render();

  return {
    // Called when the panel opens or closes. The camera is only held while the panel is open
    // or a recording is running, so collapsing the panel never interrupts a take.
    setActive(open) {
      active = open;
      if (open)
        workerNote()
          .then(text => ($('capture-worker').textContent = text))
          .catch(() => {});
      if (open && wanted && !stream) connect($('capture-camera').value || undefined);
      if (!open && countdown !== null) cancelCountdown('Countdown cancelled.');
      if (!open && !recorder) release();
      render();
    },
  };
}
