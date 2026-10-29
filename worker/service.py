"""SAM 3D Body job service for the GPU node; the editor's server submits clips here.

POST /jobs?name=&start=&seconds=&sample_hz=&side=[&bbox=x1,y1,x2,y2]  (body: video bytes) -> {id}
GET  /jobs/<id>                -> {id, status, message, log}   status: queued|waiting-gpu|running|done|failed
GET  /jobs/<id>/capture.json   -> the capture (full-body keypoints)
GET  /jobs/<id>/video.mp4      -> the video SAM ran on (its hash is in the capture)

One job at a time, through the node's shared GPU lock (with-gpu.sh). Without bbox the
person is detected automatically. Non-mp4 uploads (e.g. OBS .mkv) are cut to the requested
window and converted to H.264 mp4 first, so browsers can play exactly what was processed.
Uploads and outputs stay under private/jobs/.

Run from the deployed folder (holding .venv, checkpoints, sam-3d-body, homunculus/, worker/):
    .venv/bin/python -m worker.service --host 127.0.0.1 --port 8766
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import argparse
import json
import queue
import re
import subprocess
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]  # the deployed folder
JOBS = ROOT / 'private' / 'jobs'
GPU = Path.home() / 'experiments' / 'with-gpu.sh'
MAX_UPLOAD = 200 * 1024 * 1024
BASIS = ['1', '0', '0', '0', '-1', '0', '0', '0', '-1']  # camera -> puppet, as used for every capture so far
jobs, pending = {}, queue.Queue()


def number(query, key, default, low, high):
    value = float(query.get(key, [default])[0])
    if not low <= value <= high:
        raise ValueError(f'{key} must be within [{low}, {high}]')
    return value


def duration(video):
    out = subprocess.check_output(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(video)],
        text=True,
    )
    return float(out.strip())


def command(job):
    checkpoint = ROOT / 'checkpoints' / 'sam-3d-body-dinov3'
    cmd = [
        str(GPU),
        str(ROOT / '.venv/bin/python'),
        '-m',
        'worker.capture_video',
        str(job['video']),
        '--sam-root',
        str(ROOT / 'sam-3d-body'),
        '--checkpoint',
        str(checkpoint / 'model.ckpt'),
        '--mhr',
        str(checkpoint / 'assets/mhr_model.pt'),
        '--output',
        str(job['dir'] / 'capture'),
        '--basis',
        *BASIS,
        '--spatial',
        '--side',
        job['side'],
        '--start',
        str(job['start']),
        '--seconds',
        str(job['seconds']),
        '--sample-hz',
        str(job['sample_hz']),
    ]
    return cmd + (
        ['--bbox', *map(str, job['bbox'])]
        if job['bbox']
        else ['--detect', str(ROOT / 'checkpoints' / 'vitdet')]
    )


def convert(job):
    """Cut [start, start+seconds] to a browser-playable mp4; the capture then starts at 0."""
    job['status'], job['message'] = 'running', 'Converting to mp4'
    out = job['dir'] / (job['video'].stem + '.mp4')
    subprocess.run(
        [
            'ffmpeg',
            '-v',
            'error',
            '-y',
            '-ss',
            str(job['start']),
            '-t',
            str(job['seconds'] + 0.1),
            '-i',
            str(job['video']),
            '-an',
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '18',
            '-pix_fmt',
            'yuv420p',
            '-movflags',
            '+faststart',
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    job['video'], job['start'] = out, 0


def work():
    while True:
        job = jobs[pending.get()]
        if job['video'].suffix.lower() != '.mp4':
            try:
                convert(job)
            except subprocess.CalledProcessError as exc:
                job['status'], job['message'] = (
                    'failed',
                    'ffmpeg: ' + exc.stderr.decode(errors='replace')[-300:],
                )
                continue
        while True:
            job['status'], job['message'] = 'running', 'Running SAM 3D Body'
            with open(job['dir'] / 'worker.log', 'w') as log:
                code = subprocess.run(command(job), stdout=log, stderr=subprocess.STDOUT, cwd=ROOT).returncode
            if code != 75:
                break
            job['status'], job['message'] = (
                'waiting-gpu',
                'Another experiment holds the GPU; retrying in 15 s',
            )
            time.sleep(15)
        done = (job['dir'] / 'capture' / 'capture.json').is_file()
        job['status'] = 'done' if code == 0 and done else 'failed'
        job['message'] = 'Capture ready' if job['status'] == 'done' else f'capture_video.py exited {code}'


def tail(job, lines=12):
    log = job['dir'] / 'worker.log'
    return log.read_text(errors='replace').splitlines()[-lines:] if log.is_file() else []


def progress(job):
    """(frames done, frames expected) from capture_video.py's per-frame lines."""
    log = job['dir'] / 'worker.log'
    done = (
        re.findall(r'^(\d+) frames, source', log.read_text(errors='replace'), re.M) if log.is_file() else []
    )
    return int(done[-1]) if done else 0, int(job['seconds'] * job['sample_hz']) + 1


class Handler(BaseHTTPRequestHandler):
    def send(self, status, data, content_type='application/json'):
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        match = re.fullmatch(r'/jobs/([0-9a-f]{32})(/capture\.json|/video\.mp4)?', urlparse(self.path).path)
        if self.path == '/health':
            return self.send(200, {'ok': True, 'jobs': len(jobs)})
        if not match or match[1] not in jobs:
            return self.send(404, {'error': 'Unknown job'})
        job = jobs[match[1]]
        if match[2]:
            if job['status'] != 'done':
                return self.send(409, {'error': 'Job not finished'})
            if match[2] == '/video.mp4':
                return self.send(200, job['video'].read_bytes(), 'video/mp4')
            return self.send(200, (job['dir'] / 'capture' / 'capture.json').read_bytes())
        done, expected = progress(job)
        self.send(
            200,
            {
                'id': job['id'],
                'status': job['status'],
                'message': job['message'],
                'frames': done,
                'expected_frames': expected,
                'log': [
                    line
                    for line in tail(job, 40)
                    if re.match(r'\d+ frames|Detected person|Traceback|\w*Error', line)
                ][-6:],
            },
        )

    def do_POST(self):
        try:
            url = urlparse(self.path)
            if url.path != '/jobs':
                return self.send(404, {'error': 'Not found'})
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_UPLOAD:
                raise ValueError(f'Video must be 1-{MAX_UPLOAD} bytes')
            query = parse_qs(url.query)
            name = re.sub(r'[^A-Za-z0-9._-]', '_', query.get('name', ['clip.mp4'])[0])[-80:]
            if Path(name).suffix.lower() not in ('.mp4', '.mov', '.webm', '.mkv', '.mpg', '.avi'):
                raise ValueError('Unsupported video type')
            job_id = uuid.uuid4().hex
            folder = JOBS / f'{time.strftime("%Y%m%d-%H%M%S")}-{job_id[:8]}'
            folder.mkdir(parents=True)
            video = folder / name
            remaining = size
            with open(video, 'wb') as out:
                while remaining:
                    chunk = self.rfile.read(min(remaining, 1 << 20))
                    if not chunk:
                        raise ValueError('Upload ended early')
                    out.write(chunk)
                    remaining -= len(chunk)
            start = number(query, 'start', 0, 0, 36000)
            available = duration(video) - start
            seconds = number(query, 'seconds', min(available, 30), 2.1, 30)
            if seconds > available + 0.05:
                raise ValueError(f'Only {available:.2f} s of video after start')
            bbox = [float(v) for v in query['bbox'][0].split(',')] if 'bbox' in query else None
            if bbox is not None and len(bbox) != 4:
                raise ValueError('bbox must be x1,y1,x2,y2')
            side = query.get('side', ['right'])[0]
            if side not in ('right', 'left'):
                raise ValueError('side must be right or left')
            jobs[job_id] = {
                'id': job_id,
                'dir': folder,
                'video': video,
                'start': start,
                'seconds': round(seconds - 0.02, 2),
                'sample_hz': number(query, 'sample_hz', 15, 5, 30),
                'side': side,
                'bbox': bbox,
                'status': 'queued',
                'message': f'Queued behind {pending.qsize()} job(s)',
            }
            pending.put(job_id)
            self.send(202, {'id': job_id, 'seconds': jobs[job_id]['seconds']})
        except (ValueError, KeyError, subprocess.CalledProcessError) as exc:
            self.send(400, {'error': str(exc)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    threading.Thread(target=work, daemon=True).start()
    print(f'Homunculus worker: http://{args.host}:{args.port}', flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
