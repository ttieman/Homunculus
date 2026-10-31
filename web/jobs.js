// Choose between the remote worker and the one on this PC.
export async function workerStatus() {
  return (await fetch('/api/worker')).json();
}
export async function setWorkerMode(mode) {
  const r = await fetch('/api/worker', { method: 'POST', body: JSON.stringify({ mode }) });
  const reply = await r.json();
  if (!r.ok) throw Error(reply.error || 'Could not switch worker');
  return reply;
}
export function describeWorker(s) {
  if (s.mode !== 'local')
    return s.reachable ? 'Using the remote GPU worker.' : 'Remote GPU worker is not reachable right now.';
  const low = s.gpu_free_mib != null && s.gpu_free_mib < s.gpu_needed_mib;
  const free = s.gpu_free_mib == null ? '' : ` ${(s.gpu_free_mib / 1024).toFixed(1)} GB of GPU memory free.`;
  return (
    'Using this PC.' +
    free +
    (low
      ? ` Earlier runs needed about ${(s.gpu_needed_mib / 1024).toFixed(1)} GB, so close other GPU programs first or the run may fail.`
      : '')
  );
}

// Upload a video to the SAM 3D Body worker (through the editor server) and follow the job.
// Resolves with the finished job status, whose capture the server has saved in private/clips/.
export async function processVideo(file, start, onStatus) {
  onStatus('Uploading ' + file.name + '…');
  const r = await fetch('/api/jobs?name=' + encodeURIComponent(file.name) + '&start=' + start, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  });
  const job = await r.json();
  if (!r.ok) throw Error(job.error || 'Upload failed');
  const started = performance.now();
  let s;
  do {
    await new Promise(done => setTimeout(done, 2000));
    const p = await fetch('/api/jobs/' + job.id);
    s = await p.json();
    if (!p.ok) throw Error(s.error || 'Job status failed');
    onStatus(
      s.status +
        ' · ' +
        s.message +
        (s.frames ? ' · frame ' + s.frames + '/' + s.expected_frames : '') +
        ' · ' +
        Math.round((performance.now() - started) / 1000) +
        ' s' +
        (s.log?.length && !s.frames ? ' · ' + s.log.at(-1) : ''),
    );
  } while (!['done', 'failed'].includes(s.status));
  if (s.status === 'failed')
    throw Error(s.message + (s.log?.length ? ': ' + s.log.slice(-3).join(' | ') : ''));
  return { job, s, started };
}
