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
