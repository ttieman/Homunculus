"""glTF 2.0: actual simulated local rotations, embedded buffers, visible rigid links."""

import base64
import struct
import math


def export_gltf(result):
    side = 'L' if (result.get('capture') or {}).get('provenance', {}).get('side') == 'left' else 'R'
    binary = bytearray()
    views, accessors = [], []

    def accessor(rows, kind, bounds=False):
        flat = [v for row in rows for v in row]
        offset = len(binary)
        binary.extend(struct.pack('<' + 'f' * len(flat), *flat))
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(flat) * 4})
        item = {'bufferView': len(views) - 1, 'componentType': 5126, 'count': len(rows), 'type': kind}
        if bounds:
            item.update(
                min=[min(r[i] for r in rows) for i in range(len(rows[0]))],
                max=[max(r[i] for r in rows) for i in range(len(rows[0]))],
            )
        accessors.append(item)
        return len(accessors) - 1

    # A unit cube, triangle soup. Children scale it without scaling joint offsets.
    corners = [
        (-1, -1, -1),
        (1, -1, -1),
        (1, 1, -1),
        (-1, 1, -1),
        (-1, -1, 1),
        (1, -1, 1),
        (1, 1, 1),
        (-1, 1, 1),
    ]
    triangles = [
        0,
        2,
        1,
        0,
        3,
        2,
        4,
        5,
        6,
        4,
        6,
        7,
        0,
        1,
        5,
        0,
        5,
        4,
        3,
        7,
        6,
        3,
        6,
        2,
        1,
        2,
        6,
        1,
        6,
        5,
        0,
        4,
        7,
        0,
        7,
        3,
    ]
    pos = accessor([corners[i] for i in triangles], 'VEC3', True)
    times = accessor([[f['t']] for f in result['frames']], 'SCALAR', True)
    samplers, channels = [], []
    for joint in range(2):
        rot = accessor(
            [
                (
                    f['local_rotations_xyzw'][joint]
                    if 'local_rotations_xyzw' in f
                    else [0, 0, math.sin(f['q'][joint] / 2), math.cos(f['q'][joint] / 2)]
                )
                for f in result['frames']
            ],
            'VEC4',
        )
        samplers.append({'input': times, 'output': rot, 'interpolation': 'LINEAR'})
        channels.append({'sampler': joint, 'target': {'node': joint, 'path': 'rotation'}})
    return {
        'asset': {'version': '2.0', 'generator': 'Force Puppet'},
        'scene': 0,
        'scenes': [{'nodes': [0, 5]}],
        'nodes': [
            {'name': 'shoulder.' + side, 'translation': [0, 1.4, 0], 'children': [1, 3]},
            {'name': 'elbow.' + side, 'translation': [0.34, 0, 0], 'children': [2, 4]},
            {'name': 'hand.' + side, 'translation': [0.29, 0, 0]},
            {'name': 'upper_arm_mesh', 'mesh': 0, 'translation': [0.17, 0, 0], 'scale': [0.17, 0.04, 0.04]},
            {'name': 'forearm_mesh', 'mesh': 0, 'translation': [0.145, 0, 0], 'scale': [0.145, 0.03, 0.03]},
            {
                'name': 'visible_shoulder_support',
                'mesh': 0,
                'translation': [0, 0.7, 0],
                'scale': [0.035, 0.7, 0.035],
            },
        ],
        'meshes': [{'primitives': [{'attributes': {'POSITION': pos}, 'material': 0}]}],
        'materials': [
            {
                'doubleSided': True,
                'pbrMetallicRoughness': {
                    'baseColorFactor': [0.35, 0.9, 0.7, 1],
                    'metallicFactor': 0,
                    'roughnessFactor': 0.7,
                },
            }
        ],
        'animations': [{'name': 'SimulatedReach', 'samplers': samplers, 'channels': channels}],
        'buffers': [
            {
                'byteLength': len(binary),
                'uri': 'data:application/octet-stream;base64,' + base64.b64encode(binary).decode(),
            }
        ],
        'bufferViews': views,
        'accessors': accessors,
        'extras': {
            'provenance': result['source'],
            'assistance': result['assistance'],
            'edit': result['edit'],
            'capture': result.get('capture'),
            'note': 'Rigid articulated arm; no skin or game-skeleton retargeting. Obstacle is not exported.',
        },
    }


def animation_tracks(document):
    """Validate this exporter's rig contract, times, channels and rotation buffers."""
    import numpy as np

    try:
        blob = base64.b64decode(document['buffers'][0]['uri'].split(',', 1)[1], validate=True)

        def read(index, width, kind):
            acc = document['accessors'][index]
            view = document['bufferViews'][acc['bufferView']]
            if acc['type'] != kind or acc['componentType'] != 5126 or acc['count'] < 2 or view['buffer'] != 0:
                raise ValueError('Invalid animation accessor')
            size = acc['count'] * width * 4
            offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
            if size > view['byteLength'] or offset + size > len(blob):
                raise ValueError('Truncated animation buffer')
            return np.array(struct.unpack_from('<' + 'f' * (acc['count'] * width), blob, offset)).reshape(
                -1, width
            )

        anim = document['animations'][0]
        if len(anim['channels']) != 2 or len(anim['samplers']) != 2:
            raise ValueError('Expected two arm tracks')
        tracks = {}
        times = None
        for channel in anim['channels']:
            node = channel['target']['node']
            if node not in (0, 1) or node in tracks or channel['target']['path'] != 'rotation':
                raise ValueError('Unexpected animation channel')
            sampler = anim['samplers'][channel['sampler']]
            if sampler['interpolation'] != 'LINEAR':
                raise ValueError('Unsupported interpolation')
            t = read(sampler['input'], 1, 'SCALAR')[:, 0]
            q = read(sampler['output'], 4, 'VEC4')
            if len(t) != len(q) or not np.isfinite(t).all() or t[0] != 0 or np.any(np.diff(t) <= 0):
                raise ValueError('Invalid animation times')
            if not np.isfinite(q).all() or not np.allclose(np.linalg.norm(q, axis=1), 1, atol=1e-5):
                raise ValueError('Invalid rotation track')
            if times is not None and not np.array_equal(times, t):
                raise ValueError('Arm tracks have different timestamps')
            times = t
            tracks[node] = q
        if 1 not in document['nodes'][0]['children'] or 2 not in document['nodes'][1]['children']:
            raise ValueError('Unexpected rig hierarchy')
        return times, [tracks[0], tracks[1]]
    except (KeyError, IndexError, TypeError, struct.error) as exc:
        raise ValueError('Malformed glTF animation') from exc


def replay_gltf(document, sample_times=None):
    """Independent buffer decode, timed SLERP and FK; never reads source samples."""
    import numpy as np
    from homunculus.animation.timeline import slerp

    times, rotations = animation_tracks(document)

    def rotation(q):
        x, y, z, w = q
        return np.array(
            [
                [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
            ]
        )

    hands = []
    for time in times if sample_times is None else sample_times:
        if not np.isfinite(time):
            raise ValueError('Invalid replay time')
        time = np.clip(time, times[0], times[-1])
        i = min(max(np.searchsorted(times, time, side='right') - 1, 0), len(times) - 2)
        u = (time - times[i]) / (times[i + 1] - times[i])
        a, b = [
            slerp(track[i, [3, 0, 1, 2]], track[i + 1, [3, 0, 1, 2]], u)[[1, 2, 3, 0]] for track in rotations
        ]
        root = np.array(document['nodes'][0]['translation'])
        upper = np.array(document['nodes'][1]['translation'])
        fore = np.array(document['nodes'][2]['translation'])
        hands.append((root + rotation(a) @ upper + rotation(a) @ rotation(b) @ fore).tolist())
    return hands
