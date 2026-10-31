"""Local-only editor; each simulation request is self-contained and bounded."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from homunculus import ROOT
from homunculus.animation.rotation import apply_rotation, rotation_values
from homunculus.capture.prepare import prepare
from homunculus.contracts import MAX_DOCUMENT_BYTES, object_value
from homunculus.export.gltf import export_gltf
from homunculus.muse.meta import propose, propose_reference, MODEL, configured_key
from homunculus.animation.composition import compose, validate_options
from homunculus.physics.settings import Edit
from homunculus.physics.simulate import run
from homunculus.editor.library import Library, MAX_FILE_BYTES, clean_name
from homunculus.editor.sam_workers import Workers
from homunculus.retarget import body as full_body
from homunculus.retarget.arm import VIEWS, retarget as retarget_arm
from homunculus.retarget.character_glb import b64, export_character_glb
from homunculus.retarget.rig import configured_path, load_rig

VIDEO_TYPES = {'.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime'}
STORAGE = ROOT / 'private'
MAX_VIDEO_BYTES = 200 * 1024 * 1024
UPLOAD_TYPES = ('.mp4', '.webm', '.mov', '.mkv', '.avi', '.mpg')  # the worker converts non-mp4 to mp4


def latest_clip(clips):
    found = sorted(clips.glob('*/capture.json'), key=lambda p: p.stat().st_mtime)
    return found[-1].parent if found else None


def worker_call(base, path, data=None, headers=None):
    request = urllib.request.Request(base.rstrip('/') + path, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise ValueError('Worker: ' + json.loads(exc.read() or b'{}').get('error', str(exc))) from None
    except OSError as exc:
        raise RuntimeError(f'SAM worker unreachable at {base} ({exc})') from None


def load_clip(path):
    """A capture.json (or its folder) plus the sibling video whose hash it was recorded from."""
    import hashlib

    path = Path(path)
    if path.is_dir():
        path = path / 'capture.json'
    capture = json.loads(path.read_text(encoding='utf-8'))
    prepare(capture)
    want = capture['provenance'].get('video_sha256')
    video = next(
        (
            v
            for v in sorted(path.parent.iterdir())
            if v.suffix.lower() in VIDEO_TYPES and hashlib.sha256(v.read_bytes()).hexdigest() == want
        ),
        None,
    )
    return {'name': path.parent.name, 'capture': capture, 'video': video, 'path': path}


class Handler(BaseHTTPRequestHandler):
    rig = None  # optional external character (see retarget/rig.py)
    clip = None  # optional capture (+ matching source video) preloaded into the editor
    workers = Workers('http://127.0.0.1:8766')  # SAM 3D Body job services (worker/service.py)
    jobs = {}  # worker job id -> (local clip folder, the worker that took it)
    library = Library(STORAGE)

    def send(self, status, data, content_type='application/json'):
        encoded = json.dumps(data, allow_nan=False).encode() if content_type == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)

    def local(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return (
            self.headers.get('Host') == expected
            and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected
        )

    def do_GET(self):
        if not self.local():
            return self.send(403, {'error': 'Local origin required'})
        job = re.fullmatch(r'/api/jobs/([0-9a-f]{32})', self.path)
        if job:
            try:
                return self.send(200, self.job_status(job[1]))
            except ValueError as exc:
                return self.send(400, {'error': str(exc)})
            except RuntimeError as exc:
                return self.send(503, {'error': str(exc)})
        if self.path == '/api/worker':
            return self.send(200, self.workers.status())
        url = urllib.parse.urlparse(self.path)
        if url.path == '/api/library':
            return self.send(200, self.library_listing())
        if url.path == '/library/file':
            query = urllib.parse.parse_qs(url.query)
            try:
                return self.send_asset(query.get('id', [''])[0], 'download' in query)
            except ValueError as exc:
                return self.send(404, {'error': str(exc)})
        if self.path == '/api/contracts':
            return self.send(200, {'max_document_bytes': MAX_DOCUMENT_BYTES})
        if self.path == '/api/commands':
            from homunculus.editor.commands import tools

            return self.send(200, {'tools': tools()})
        if self.path == '/api/status':
            return self.send(
                200,
                {
                    'meta': 'configured; unverified' if configured_key() else 'blocked: no credentials',
                    'model': MODEL,
                    'character': self.rig.summary() if self.rig else None,
                },
            )
        if self.path == '/api/clip':
            self.forget_deleted_clip()
            if not self.clip:
                return self.send(404, {'error': 'No clip configured'})
            return self.send(
                200,
                {
                    'name': self.clip['name'],
                    'capture': self.clip['capture'],
                    'video': self.clip['video'].name if self.clip['video'] else None,
                },
            )
        if self.path == '/clip/video':
            if not (self.clip and self.clip['video']):
                return self.send(404, {'error': 'No clip video'})
            return self.send(
                200, self.clip['video'].read_bytes(), VIDEO_TYPES[self.clip['video'].suffix.lower()]
            )
        if self.path == '/character.glb':
            if not self.rig:
                return self.send(404, {'error': 'No character configured'})
            return self.send(200, self.rig.blob, 'model/gltf-binary')
        js = 'text/javascript; charset=utf-8'
        paths = {
            '/': ('index.html', 'text/html; charset=utf-8'),
            '/app.js': ('app.js', js),
            '/workflow.js': ('workflow.js', js),
            '/composer.js': ('composer.js', js),
            '/capture.js': ('capture.js', js),
            '/library.js': ('library.js', js),
            '/workflow.css': ('workflow.css', 'text/css; charset=utf-8'),
            '/stage3d.js': ('stage3d.js', js),
            '/workspace.js': ('workspace.js', js),
            '/jobs.js': ('jobs.js', js),
            '/motion-math.js': ('motion-math.js', js),
            '/segments.js': ('segments.js', js),
            '/vendor/three.js': ('vendor/three.js', js),
        }
        if self.path not in paths:
            return self.send(404, {'error': 'Not found'})
        name, mime = paths[self.path]
        self.send(200, (ROOT / 'web' / name).read_bytes(), mime)

    def library_listing(self):
        listing = self.library.list()
        if self.rig:
            listing['items'].append(
                {
                    'id': 'character',
                    'kind': 'character',
                    'title': Path(self.rig.source).stem,
                    'file': Path(self.rig.source).name,
                    'size': len(self.rig.blob),
                    'meta': {},
                    'read_only': True,
                }
            )
        return listing

    def send_asset(self, asset_id, download):
        if asset_id == 'character' and self.rig:
            blob, name = self.rig.blob, Path(self.rig.source).name
        else:
            path = self.library.path(asset_id)
            blob, name = path.read_bytes(), path.name
        mime = {'.json': 'application/json', '.glb': 'model/gltf-binary', **VIDEO_TYPES}.get(
            Path(name).suffix.lower(), 'application/octet-stream'
        )
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(blob)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        if download:
            self.send_header('Content-Disposition', 'attachment; filename="' + clean_name(name) + '"')
        self.end_headers()
        try:
            self.wfile.write(blob)
        except ConnectionError:
            pass  # a thumbnail <video> hangs up once it has the first frame

    def open_asset(self, asset_id):
        """Remember what was opened; a capture also becomes the clip a page reload shows."""
        item = self.library.item(asset_id)
        if item['kind'] == 'capture':
            Handler.clip = load_clip(self.library.path(asset_id))
            self.library.mark_opened(asset_id)
            item['video'] = bool(Handler.clip['video'])
        return item

    def forget_deleted_clip(self):
        clip = self.clip
        if clip and not (clip['path'].is_file() and (clip['video'] is None or clip['video'].is_file())):
            folder = clip['path'].parent if clip['path'].is_file() else latest_clip(self.library.clips)
            Handler.clip = load_clip(folder) if folder else None

    def job_status(self, job_id):
        if job_id not in self.jobs:
            raise ValueError('Unknown job')
        folder, worker = self.jobs[job_id]
        status = json.loads(worker_call(worker, f'/jobs/{job_id}'))
        if status['status'] == 'done':
            if not (folder / 'capture.json').is_file():
                (folder / (folder.name.split('-', 2)[-1] + '.mp4')).write_bytes(
                    worker_call(worker, f'/jobs/{job_id}/video.mp4')
                )
                (folder / 'capture.json').write_bytes(worker_call(worker, f'/jobs/{job_id}/capture.json'))
            Handler.clip = load_clip(folder)  # a page reload now opens this clip
            self.library.mark_opened((folder / 'capture.json').relative_to(self.library.root).as_posix())
            status['name'], status['capture'] = folder.name, Handler.clip['capture']
        return status

    def submit_video(self):
        """Queue the upload on the SAM worker; the processed mp4 and capture land in private/clips/."""
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= MAX_VIDEO_BYTES:
            raise ValueError(f'Video must be 1–{MAX_VIDEO_BYTES} bytes')
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        name = re.sub(r'[^A-Za-z0-9._-]', '_', query.get('name', ['clip.mp4'])[0])[-80:]
        if Path(name).suffix.lower() not in UPLOAD_TYPES:
            raise ValueError('Use one of ' + ', '.join(UPLOAD_TYPES))
        video = self.rfile.read(size)
        folder = self.library.clips / f'{time.strftime("%Y%m%d-%H%M%S")}-{Path(name).stem}'
        forward = {k: query[k][0] for k in ('start', 'seconds', 'side', 'bbox') if k in query}
        worker = self.workers.url
        reply = json.loads(
            worker_call(
                worker,
                '/jobs?' + urllib.parse.urlencode({'name': name, **forward}),
                video,
                {'Content-Type': 'application/octet-stream'},
            )
        )
        folder.mkdir(parents=True)  # only once the worker has accepted the job
        self.jobs[reply['id']] = (folder, worker)
        return {'id': reply['id'], 'seconds': reply['seconds'], 'name': folder.name}

    def do_POST(self):
        if not self.local():
            return self.send(403, {'error': 'Local origin required'})
        try:
            if urllib.parse.urlparse(self.path).path == '/api/jobs':
                return self.send(202, self.submit_video())
            if urllib.parse.urlparse(self.path).path == '/api/library/upload':
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_FILE_BYTES:
                    raise ValueError(f'File must be 1 to {MAX_FILE_BYTES} bytes')
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                return self.send(200, self.library.add(query.get('name', [''])[0], self.rfile.read(size)))
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= MAX_DOCUMENT_BYTES:
                raise ValueError(f'Request size must be 1–{MAX_DOCUMENT_BYTES} bytes')
            body = object_value(json.loads(self.rfile.read(size)), 'request')
            if self.path == '/api/worker':
                return self.send(200, self.workers.set_mode(body.get('mode')))
            if self.path == '/api/library/open':
                return self.send(200, self.open_asset(body.get('id')))
            if self.path == '/api/library/rename':
                return self.send(200, self.library.rename(body.get('id'), body.get('title')))
            if self.path == '/api/library/delete':
                self.library.delete(body.get('id'))
                self.forget_deleted_clip()
                return self.send(200, {'deleted': body.get('id')})
            if self.path == '/api/chat':
                from homunculus.muse.chat import turn

                return self.send(200, turn(body))
            if self.path == '/api/segments':
                from homunculus.animation import segments

                capture = body['capture']
                frames = capture['frames']
                if capture.get('retargeting') != 'spatial_arm_v1':
                    raise ValueError('Segments require a spatial capture')
                capture['timing'] = segments.apply(
                    capture.get('timing'),
                    object_value(body.get('operation'), 'operation'),
                    frames[-1]['t'] - frames[0]['t'],
                )
                if not capture['timing']['segments']:
                    del capture['timing']
                prepare(capture)
                return self.send(
                    200, {'capture': capture, 'segments': segments.describe(capture.get('timing'))}
                )
            if self.path == '/api/pose':
                from homunculus.animation.pose_editor import adjust

                return self.send(
                    200,
                    {'capture': adjust(body['capture'], {k: v for k, v in body.items() if k != 'capture'})},
                )
            if self.path == '/api/commands/validate':
                from homunculus.editor.commands import validate_command

                return self.send(
                    200, {'arguments': validate_command(body.get('name'), body.get('arguments'))}
                )
            if self.path == '/api/capture/validate':
                rotation_values(body['capture'].get('animation_rotation'))
                motion = prepare(body['capture'])

                track = full_body.body_track(body['capture'])
                return self.send(
                    200,
                    {'metadata': motion.metadata, 'body_keypoints': 0 if track is None else len(track[2])},
                )
            if self.path == '/api/reference':
                from homunculus.capture.spatial import SpatialMotion
                from homunculus.animation.timeline import Timeline

                motion = prepare(body['capture'])
                if not isinstance(motion, SpatialMotion):
                    raise ValueError('Spatial capture required')
                timeline = motion.timeline
                if body.get('three_poses') is True:
                    doc = timeline.document
                    keys = doc['keyframes']
                    doc['keyframes'] = [keys[0], keys[len(keys) // 2], keys[-1]]
                    ids = {k['poseId'] for k in doc['keyframes']}
                    doc['poses'] = {k: v for k, v in doc['poses'].items() if k in ids}
                    timeline = Timeline(doc)
                if body.get('duration') is not None:
                    timeline = timeline.edited(
                        [{'operation': 'set_duration', 'parameters': {'seconds': body['duration']}}]
                    )
                if body.get('commands'):
                    timeline = timeline.edited(body['commands'])
                capture = body['capture']
                capture['reference_animation'] = timeline.document
                prepare(capture)
                return self.send(200, {'capture': capture, 'reference': timeline.document})
            edit = Edit.parse(body['edit'])
            if self.path in ('/api/simulate', '/api/synthesize'):
                rotation = rotation_values((body.get('capture') or {}).get('animation_rotation'))
                if any(rotation.values()) and not self.rig:
                    raise ValueError('Load a character rig to rotate the animation')
                motion = prepare(body['capture']) if body.get('capture') is not None else None
                if self.path == '/api/synthesize':
                    from homunculus.capture.spatial import SpatialMotion
                    from homunculus.physics.spatial import synthesize

                    if not isinstance(motion, SpatialMotion):
                        raise ValueError('Optimization requires a spatial capture')
                    result, report = synthesize(motion, edit)
                    result['optimization'] = report
                else:
                    result = run(edit, motion)
                if body.get('composition') is not None and not self.rig:
                    raise ValueError('Load a character rig before composing animation')
                payload = {'result': result, 'gltf': export_gltf(result)}
                if self.rig:
                    view = body.get('view')
                    if view is not None and view not in VIEWS:
                        raise ValueError('view must be one of ' + ', '.join(sorted(VIEWS)))
                    if body.get('body') not in (None, True, False):
                        raise ValueError('body must be true or false')
                    capture = body.get('capture')

                    if (
                        capture is not None
                        and body.get('body') is not False
                        and full_body.body_track(capture) is not None
                    ):
                        keys = (
                            motion.timeline.document['keyframes']
                            if getattr(motion, 'timeline', None)
                            else None
                        )
                        if body.get('physics_arm') not in (None, True, False):
                            raise ValueError('physics_arm must be true or false')
                        result['retarget'] = full_body.retarget_body(
                            result, self.rig, capture, keys, physics_arm=body.get('physics_arm') is True
                        )
                    else:
                        result['retarget'] = retarget_arm(result, self.rig, view=view)
                    result['available_bones'] = result['retarget']['bones'][:]
                    composition = body.get('composition')
                    if composition is not None:
                        mode, _, _, _ = validate_options(composition)
                        secondary = None
                        if mode != 'mask':
                            source = composition.get('source')
                            if not isinstance(source, dict):
                                raise ValueError('A second capture is required')
                            other_motion = prepare(source)
                            if full_body.body_track(source) is None:
                                raise ValueError('Second capture must contain full-body keypoints')
                            keys = (
                                other_motion.timeline.document['keyframes']
                                if getattr(other_motion, 'timeline', None)
                                else None
                            )
                            duration = (
                                keys[-1]['time']
                                if keys
                                else source['frames'][-1]['t'] - source['frames'][0]['t']
                            )
                            other_edit = Edit.parse(
                                {**result['edit'], 'duration': duration, 'obstacle': False}
                            )
                            other_result = run(other_edit, other_motion)
                            secondary = full_body.retarget_body(other_result, self.rig, source, keys)
                        result['retarget'] = compose(result['retarget'], composition, secondary)
                        result['playback_duration'] = result['retarget']['frames'][-1]['t']
                    result['retarget'] = apply_rotation(result['retarget'], self.rig, rotation)
                    payload['character_glb'] = b64(
                        export_character_glb(
                            self.rig,
                            result['retarget'],
                            {
                                'provenance': result['source'],
                                'edit': result['edit'],
                                'capture': result.get('capture'),
                            },
                        )
                    )
                return self.send(200, payload)
            if self.path == '/api/propose':
                return self.send(
                    200,
                    (
                        propose_reference(body['prompt'], body['capture'], edit)
                        if body.get('capture') is not None
                        else propose(body['prompt'], edit)
                    ),
                )
            self.send(404, {'error': 'Not found'})
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            IndexError,
            OverflowError,
            RecursionError,
        ) as exc:
            self.send(400, {'error': str(exc)})
        except RuntimeError as exc:
            self.send(503, {'error': str(exc)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument(
        '--character',
        help='GLB game character to retarget onto (default: HOMUNCULUS_CHARACTER in the environment or .env.local)',
    )
    parser.add_argument(
        '--clip',
        help='capture.json (or its folder) to preview on page load (default: newest processed clip in private/clips); the matching source video beside it is loaded too',
    )
    parser.add_argument(
        '--no-clip',
        action='store_true',
        help='open empty instead of preloading the newest clip (browser tests)',
    )
    parser.add_argument(
        '--worker', default=Handler.workers.remote, help='SAM 3D Body job service URL (default %(default)s)'
    )
    parser.add_argument(
        '--storage',
        default=STORAGE,
        help='folder holding clips, exports, projects and scenes (default %(default)s)',
    )
    args = parser.parse_args()
    Handler.workers.remote = args.worker
    Handler.library = Library(args.storage)
    clip = (
        None
        if args.no_clip
        else args.clip or Handler.library.last_opened_clip() or latest_clip(Handler.library.clips)
    )
    if clip:
        try:
            Handler.clip = load_clip(clip)
        except (ValueError, KeyError, TypeError) as exc:
            if args.clip:
                raise
            print(f'Newest clip {clip.name} not loaded: {exc}', flush=True)
        else:
            print(
                f"Clip: {Handler.clip['name']} (video: {Handler.clip['video'].name if Handler.clip['video'] else 'none matching'})",
                flush=True,
            )
    path = args.character or configured_path()
    if path:
        Handler.rig = load_rig(path)
        print(f'Character: {Handler.rig.source}', flush=True)
    print(f'Homunculus editor: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
