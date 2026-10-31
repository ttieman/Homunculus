"""Local asset library: everything the editor uses or produces, stored under private/.

clips/<folder>/   capture.json and its source video     exports/**/*.glb  character animations
projects/*.json   saved animation projects              scenes/*.json     saved preview scenes

Titles, creation dates and the last opened asset live in library.json, so renaming an
asset never moves a file and a clip folder keeps the name it was recorded under.
"""

import json
import os
from pathlib import Path
import re
import struct
import tempfile
import threading
import time

from homunculus.capture.prepare import prepare
from homunculus.contracts import MAX_DOCUMENT_BYTES
from homunculus.editor.commands import validate_command
from homunculus.retarget import body as full_body
from homunculus.retarget.rig import read_glb

MAX_FILE_BYTES = 200 * 1024 * 1024
VIDEO_SUFFIXES = ('.mp4', '.webm', '.mov', '.mkv', '.avi', '.mpg')
MAX_TITLE = 80
SKELETON = [
    ['nose', 'neck'],
    ['left-wrist', 'left-elbow', 'left-shoulder', 'neck', 'right-shoulder', 'right-elbow', 'right-wrist'],
    ['neck', 'left-hip', 'left-knee', 'left-ankle'],
    ['neck', 'right-hip', 'right-knee', 'right-ankle'],
    ['left-hip', 'right-hip'],
]


def without_stamp(name):
    return re.sub(r'^(\d{8}-\d{6}-)+', '', name) or name


def clean_name(name):
    name = re.sub(r'[^A-Za-z0-9._-]', '_', str(name)).strip('._')[-80:]
    return name or 'asset'


def pose_lines(capture):
    """Middle-frame stick figure as 0..1 polylines for a thumbnail, or None for arm-only captures."""
    track = full_body.body_track(capture)
    if track is None:
        return None
    _, points, names = track
    frame = points[len(points) // 2]
    at = {name: (float(frame[i][0]), float(frame[i][1])) for i, name in enumerate(names)}
    xs, ys = zip(*(at[n] for line in SKELETON for n in line))
    size = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
    mid_x, mid_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
    flip = -0.8 if at['nose'][1] > at['left-ankle'][1] else 0.8  # screen y runs down; the basis may not

    def place(point):
        return [
            round(0.5 + (point[0] - mid_x) / size * 0.8, 3),
            round(0.5 + (point[1] - mid_y) / size * flip, 3),
        ]

    return [[place(at[n]) for n in line] for line in SKELETON]


def capture_duration(capture):
    keys = (capture.get('reference_animation') or {}).get('keyframes')
    return keys[-1]['time'] if keys else capture['frames'][-1]['t'] - capture['frames'][0]['t']


def describe_capture(capture):
    pose = pose_lines(capture)
    return {
        'duration': round(capture_duration(capture), 2),
        'frames': len(capture['frames']),
        'body': 'full body' if pose else 'arm only',
        'pose': pose,
    }


def describe_glb(blob):
    document, _ = read_glb(blob)
    animations = document.get('animations') or []
    duration = 0.0
    for sampler in animations[0]['samplers'] if animations else []:
        duration = max(duration, document['accessors'][sampler['input']].get('max', [0])[0])
    return {
        'animation': animations[0].get('name', 'Unnamed') if animations else None,
        'duration': round(duration, 2),
        'tracks': len(animations[0]['channels']) if animations else 0,
    }


def describe(kind, path):
    if kind == 'recording':
        return {}
    if kind == 'animation':
        return describe_glb(path.read_bytes())
    data = json.loads(path.read_text(encoding='utf-8'))
    if kind == 'capture':
        return describe_capture(data)
    if kind == 'project':
        return {**describe_capture(data['capture']), 'duration': data['edit'].get('duration')}
    return {'background': data['scene'].get('background'), 'props': len(data['scene'].get('props', []))}


def check_upload(name, blob):
    """The category of an imported file; raises ValueError naming the problem."""
    suffix = Path(name).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return 'recording'
    if suffix == '.glb':
        describe_glb(blob)
        return 'animation'
    if suffix != '.json':
        raise ValueError(f'{name}: use a video, a .glb, or a capture, project or scene .json')
    if len(blob) > MAX_DOCUMENT_BYTES:
        raise ValueError(f'{name}: JSON files are limited to {MAX_DOCUMENT_BYTES} bytes')
    data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError(f'{name}: not a Homunculus file')
    if data.get('schema') == 'homunculus.project.v1':
        prepare(data['capture'])
        return 'project'
    if data.get('schema') == 'homunculus.scene.v1':
        validate_command('set_scene', data['scene'])
        return 'scene'
    prepare(data)
    return 'capture'


class Library:
    def __init__(self, root):
        self.root = Path(root)
        self.clips = self.root / 'clips'
        self.index_path = self.root / 'library.json'
        self.lock = threading.RLock()

    def kind_of(self, rel):
        parts = rel.split('/')
        suffix = Path(rel).suffix.lower()
        if parts[0] == 'clips' and len(parts) == 3:
            if parts[2] == 'capture.json':
                return 'capture'
            if suffix in VIDEO_SUFFIXES:
                return 'recording'
        if parts[0] == 'exports' and suffix == '.glb':
            return 'animation'
        if parts[0] == 'projects' and len(parts) == 2 and suffix == '.json':
            return 'project'
        if parts[0] == 'scenes' and len(parts) == 2 and suffix == '.json':
            return 'scene'
        return None

    def path(self, asset_id):
        """The file behind an id; ids are library-relative and can never leave the library."""
        if not isinstance(asset_id, str) or not self.kind_of(asset_id):
            raise ValueError('Unknown library asset')
        path = (self.root / asset_id).resolve()
        if not path.is_relative_to(self.root.resolve()) or not path.is_file():
            raise ValueError('Unknown library asset')
        return path

    def load_index(self):
        try:
            return json.loads(self.index_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return {'assets': {}, 'last_opened': None}

    def save_index(self, index):
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(dir=self.root, suffix='.tmp')
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(index, handle)
        os.replace(temp, self.index_path)

    def files(self):
        patterns = (('clips', '*/*'), ('exports', '**/*.glb'), ('projects', '*.json'), ('scenes', '*.json'))
        for folder, pattern in patterns:
            for path in sorted((self.root / folder).glob(pattern)):
                rel = path.relative_to(self.root).as_posix()
                kind = self.kind_of(rel)
                if kind and path.is_file():
                    yield rel, kind, path

    def row(self, rel, kind, path, entry):
        stat = path.stat()
        if entry.get('stamp') != stat.st_mtime_ns:
            try:
                entry.update(meta=describe(kind, path), broken=None)
            except (ValueError, KeyError, TypeError, IndexError, AttributeError, struct.error) as exc:
                entry.update(meta={}, broken=str(exc)[:200])
            entry['stamp'] = stat.st_mtime_ns
        entry.setdefault('created', min(stat.st_mtime, stat.st_ctime))

        def sibling(test):
            return next(
                (p.relative_to(self.root).as_posix() for p in sorted(path.parent.iterdir()) if test(p)), None
            )

        links = {}
        if kind == 'capture':
            links['video_id'] = sibling(lambda p: p.suffix.lower() in VIDEO_SUFFIXES)
        if kind == 'recording':
            links['capture_id'] = sibling(lambda p: p.name == 'capture.json')
        default_title = without_stamp(path.parent.name if rel.startswith('clips/') else path.stem)
        return {
            'id': rel,
            'kind': kind,
            'title': entry.get('title') or default_title,
            'file': path.name,
            'size': stat.st_size,
            'created': entry['created'],
            'modified': max(stat.st_mtime, entry.get('renamed', 0)),
            'meta': entry['meta'],
            'broken': entry.get('broken'),
            'read_only': False,
            **links,
        }

    def list(self):
        with self.lock:
            index = self.load_index()
            before = json.dumps(index, sort_keys=True)
            items = [
                self.row(rel, kind, path, index['assets'].setdefault(rel, {}))
                for rel, kind, path in self.files()
            ]
            known = {item['id'] for item in items}
            index['assets'] = {k: v for k, v in index['assets'].items() if k in known}
            if json.dumps(index, sort_keys=True) != before:
                self.save_index(index)
        return {
            'items': items,
            'last_opened': index['last_opened'] if index['last_opened'] in known else None,
        }

    def item(self, asset_id):
        self.path(asset_id)
        return next(item for item in self.list()['items'] if item['id'] == asset_id)

    def add(self, name, blob):
        """Store an imported or saved file under a fresh name; nothing is ever overwritten."""
        name = clean_name(name)
        kind = check_upload(name, blob)
        stamp = time.strftime('%Y%m%d-%H%M%S')
        stem, suffix = without_stamp(Path(name).stem), Path(name).suffix.lower()
        folders = {'animation': 'exports', 'project': 'projects', 'scene': 'scenes'}
        for attempt in range(100):
            unique = f'{stamp}-{stem}' + (f'-{attempt + 1}' if attempt else '')
            if kind in folders:
                target = self.root / folders[kind] / (unique + suffix)
                taken = target.exists()
            else:
                target = self.clips / unique / ('capture.json' if kind == 'capture' else stem + suffix)
                taken = target.parent.exists()
            if taken:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, 'xb') as handle:
                handle.write(blob)
            return self.item(target.relative_to(self.root).as_posix())
        raise ValueError(f'{name}: too many files with this name')

    def rename(self, asset_id, title):
        self.path(asset_id)
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= MAX_TITLE:
            raise ValueError(f'Names must be 1 to {MAX_TITLE} characters')
        with self.lock:
            index = self.load_index()
            index['assets'].setdefault(asset_id, {}).update(title=title.strip(), renamed=time.time())
            self.save_index(index)
        return self.item(asset_id)

    def delete(self, asset_id):
        path = self.path(asset_id)
        path.unlink()
        top = (self.root / asset_id.split('/')[0]).resolve()
        for folder in path.parents:  # drop a clip folder once its last file is gone
            if folder == top or any(folder.iterdir()):
                break
            folder.rmdir()
        with self.lock:
            index = self.load_index()
            index['assets'].pop(asset_id, None)
            if index['last_opened'] == asset_id:
                index['last_opened'] = None
            self.save_index(index)

    def mark_opened(self, asset_id):
        with self.lock:
            index = self.load_index()
            index['last_opened'] = asset_id
            self.save_index(index)

    def last_opened_clip(self):
        """Folder of the capture worked on last, if it still exists."""
        rel = self.load_index().get('last_opened')
        if rel and self.kind_of(rel) == 'capture' and (self.root / rel).is_file():
            return (self.root / rel).parent
        return None
