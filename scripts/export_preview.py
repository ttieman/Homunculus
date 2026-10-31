"""Export a full-body capture through the editor API and retain replay evidence.

Run from Homunculus with its Python environment. No credentials are read.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homunculus.editor.server import Handler
from homunculus.retarget.rig import load_rig, read_glb
from homunculus.retarget.character_glb import replay_pose


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('--character', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--physics-arm', action='store_true')
    args = parser.parse_args()
    capture_bytes = args.capture.read_bytes()
    capture = json.loads(capture_bytes)
    if len(capture.get('body_keypoints', [])) != 70:
        raise ValueError('Expected a full-body capture with 70 named keypoints')
    duration = capture.get('reference_animation', {}).get('keyframes', [{}])[-1].get('time')
    duration = duration or capture['frames'][-1]['t'] - capture['frames'][0]['t']
    Handler.rig = load_rig(args.character)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f'http://127.0.0.1:{server.server_port}/api/simulate',
            data=json.dumps(
                {
                    'capture': capture,
                    'edit': {'duration': duration, 'obstacle': False},
                    'body': True,
                    'physics_arm': args.physics_arm,
                }
            ).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urlopen(request, timeout=180) as response:
            payload = json.load(response)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        Handler.rig = None
    blob = base64.b64decode(payload['character_glb'])
    doc, binary = read_glb(blob)
    retarget = payload['result']['retarget']
    frames = retarget['frames']
    anim = doc['animations'][0]
    assert len(doc['animations']) == 1 and retarget['mode'] == 'body'
    assert len(anim['channels']) == len(retarget['bones']) + 1
    max_rotation_error = max_translation_error = 0.0
    for channel in anim['channels']:
        sampler = anim['samplers'][channel['sampler']]
        accessor = doc['accessors'][sampler['output']]
        view = doc['bufferViews'][accessor['bufferView']]
        width = 4 if channel['target']['path'] == 'rotation' else 3
        offset = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        actual = np.frombuffer(binary, dtype='<f4', count=accessor['count'] * width, offset=offset).reshape(
            -1, width
        )
        assert np.isfinite(actual).all()
        if width == 4:
            joint = retarget['nodes'].index(channel['target']['node'])
            expected = np.array([f['rotations_xyzw'][joint] for f in frames])
            max_rotation_error = max(max_rotation_error, float(np.max(np.abs(expected - actual))))
            assert np.allclose(np.linalg.norm(actual, axis=1), 1, atol=1e-5)
        else:
            expected = np.array([f['translation'] for f in frames])
            max_translation_error = float(np.max(np.abs(expected - actual)))
    times, world = replay_pose(blob)
    assert np.all(np.diff(times) > 0) and abs(times[-1] - duration) < 1e-4
    assert max_rotation_error < 1e-6 and max_translation_error < 1e-6
    assert all(np.isfinite(track).all() for track in world.values())
    indices = sorted(set(round(i * (len(frames) - 1) / 4) for i in range(5)))
    samples = [
        {
            'time': float(times[i]),
            'rotations': dict(zip(retarget['bones'], frames[i]['rotations_xyzw'])),
            'pelvis': frames[i]['translation'],
        }
        for i in indices
    ]
    report = {
        'capture': str(args.capture.resolve()),
        'capture_sha256': hashlib.sha256(capture_bytes).hexdigest(),
        'character': str(args.character.resolve()),
        'glb_sha256': hashlib.sha256(blob).hexdigest(),
        'physics_arm': args.physics_arm,
        'animation': anim['name'],
        'duration': float(times[-1]),
        'source_frames': len(capture['frames']),
        'export_frames': len(times),
        'rotation_channels': len(retarget['bones']),
        'translation_channels': 1,
        'max_rotation_component_error': max_rotation_error,
        'max_translation_component_error_m': max_translation_error,
        'bone_motion_extent_m': {
            n: float(np.linalg.norm(np.ptp(world[n], axis=0))) for n in retarget['bones']
        },
        'samples': samples,
        'limits': 'Export fidelity only; capture accuracy, foot contact and loop seam quality are not certified.',
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'animation.glb').write_bytes(blob)
    (args.output / 'export-review.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ('samples', 'bone_motion_extent_m')}, indent=2
        )
    )


if __name__ == '__main__':
    main()
