"""Write the posed character as a GLB with an animation clip, and replay such files for checks."""

import base64
import copy
import struct

import numpy as np
from homunculus.retarget.geometry import qmat, qmul, unit
from homunculus.retarget.rig import Rig, write_glb


def export_character_glb(rig, retargeted, extras=None):
    """The character's mesh, skin and material plus one new clip; source clips are dropped."""
    src = rig.document
    doc = {
        k: copy.deepcopy(src[k])
        for k in (
            'asset',
            'scene',
            'scenes',
            'nodes',
            'meshes',
            'skins',
            'materials',
            'textures',
            'images',
            'samplers',
            'extensionsUsed',
            'extensionsRequired',
        )
        if k in src
    }
    doc['asset']['generator'] = 'Homunculus character retarget'
    used_accessors = set()
    for mesh in doc.get('meshes', []):
        for prim in mesh['primitives']:
            used_accessors.update(prim['attributes'].values())
            if 'indices' in prim:
                used_accessors.add(prim['indices'])
            for target in prim.get('targets', []):
                used_accessors.update(target.values())
    for skin in doc.get('skins', []):
        if 'inverseBindMatrices' in skin:
            used_accessors.add(skin['inverseBindMatrices'])
    used_views = {
        src['accessors'][a]['bufferView'] for a in used_accessors if 'bufferView' in src['accessors'][a]
    }
    if any('sparse' in src['accessors'][a] for a in used_accessors):
        raise ValueError('Sparse accessors are not supported in the character')
    used_views.update(img['bufferView'] for img in doc.get('images', []) if 'bufferView' in img)
    if any('uri' in img for img in doc.get('images', [])) or any('uri' in b for b in src.get('buffers', [])):
        raise ValueError('Character must be self-contained (no external URIs)')

    binary = bytearray()
    view_map, views = {}, []
    for old in sorted(used_views):
        view = copy.deepcopy(src['bufferViews'][old])
        binary.extend(b'\0' * (-len(binary) % 4))
        start = view.get('byteOffset', 0)
        chunk = rig.binary[start : start + view['byteLength']]
        view['byteOffset'] = len(binary)
        view['buffer'] = 0
        binary.extend(chunk)
        view_map[old] = len(views)
        views.append(view)
    accessor_map, accessors = {}, []
    for old in sorted(used_accessors):
        acc = copy.deepcopy(src['accessors'][old])
        if 'bufferView' in acc:
            acc['bufferView'] = view_map[acc['bufferView']]
        accessor_map[old] = len(accessors)
        accessors.append(acc)
    for mesh in doc.get('meshes', []):
        for prim in mesh['primitives']:
            prim['attributes'] = {k: accessor_map[v] for k, v in prim['attributes'].items()}
            if 'indices' in prim:
                prim['indices'] = accessor_map[prim['indices']]
            if 'targets' in prim:
                prim['targets'] = [{k: accessor_map[v] for k, v in t.items()} for t in prim['targets']]
    for skin in doc.get('skins', []):
        if 'inverseBindMatrices' in skin:
            skin['inverseBindMatrices'] = accessor_map[skin['inverseBindMatrices']]
    for img in doc.get('images', []):
        if 'bufferView' in img:
            img['bufferView'] = view_map[img['bufferView']]

    def add(rows, kind, bounds=False):
        flat = [float(v) for row in rows for v in row]
        binary.extend(b'\0' * (-len(binary) % 4))
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(flat) * 4})
        binary.extend(struct.pack('<' + 'f' * len(flat), *flat))
        acc = {'bufferView': len(views) - 1, 'componentType': 5126, 'count': len(rows), 'type': kind}
        if bounds:
            acc['min'] = [min(r[i] for r in rows) for i in range(len(rows[0]))]
            acc['max'] = [max(r[i] for r in rows) for i in range(len(rows[0]))]
        accessors.append(acc)
        return len(accessors) - 1

    frames = retargeted['frames']
    times = add([[f['t'] - frames[0]['t']] for f in frames], 'SCALAR', True)
    samplers, channels = [], []
    for joint, node in enumerate(retargeted['nodes']):
        samplers.append(
            {
                'input': times,
                'output': add([f['rotations_xyzw'][joint] for f in frames], 'VEC4'),
                'interpolation': 'LINEAR',
            }
        )
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': 'rotation'}})
    if retargeted.get('translation_node') is not None:
        samplers.append(
            {
                'input': times,
                'output': add([f['translation'] for f in frames], 'VEC3'),
                'interpolation': 'LINEAR',
            }
        )
        channels.append(
            {
                'sampler': len(samplers) - 1,
                'target': {'node': retargeted['translation_node'], 'path': 'translation'},
            }
        )
    doc['animations'] = [
        {
            'name': 'Homunculus_Body' if retargeted.get('mode') == 'body' else 'Homunculus_Reach',
            'samplers': samplers,
            'channels': channels,
        }
    ]
    doc['buffers'] = [{'byteLength': len(binary) + (-len(binary) % 4)}]
    doc['bufferViews'] = views
    doc['accessors'] = accessors
    doc['extras'] = {
        'homunculus': {
            'mode': retargeted.get('mode', 'arm'),
            'side': retargeted['side'],
            'bones': retargeted['bones'],
            'view': retargeted['view'],
            'mapping': retargeted['mapping'],
            'note': retargeted['note'],
            **(extras or {}),
        }
    }
    return write_glb(doc, binary)


def replay_pose(blob):
    """Independent decode of an exported character GLB: FK of the whole rig at every key.

    Returns (times, {node name: K x 3 world positions in character space}).
    """
    rig = Rig(blob)
    doc, binary = rig.document, rig.binary
    anim = doc['animations'][0]

    def read(index, width):
        acc = doc['accessors'][index]
        view = doc['bufferViews'][acc['bufferView']]
        if acc['componentType'] != 5126:
            raise ValueError('Unexpected animation component type')
        offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        if offset + acc['count'] * width * 4 > view.get('byteOffset', 0) + view['byteLength']:
            raise ValueError('Truncated animation accessor')
        return np.array(struct.unpack_from('<' + 'f' * (acc['count'] * width), binary, offset)).reshape(
            -1, width
        )

    times, tracks = None, {}
    for channel in anim['channels']:
        sampler = anim['samplers'][channel['sampler']]
        t = read(sampler['input'], 1)[:, 0]
        if times is not None and not np.array_equal(t, times):
            raise ValueError('Animation channels use different key times')
        times = t
        path = channel['target']['path']
        if path not in ('rotation', 'translation') or (channel['target']['node'], path) in tracks:
            raise ValueError('Unexpected animation channel')
        tracks[(channel['target']['node'], path)] = read(sampler['output'], 4 if path == 'rotation' else 3)
    nodes = doc['nodes']
    order = [i for i in range(len(nodes)) if i not in rig.parent]
    out = {n.get('name', str(i)): np.zeros((len(times), 3)) for i, n in enumerate(nodes)}
    for k in range(len(times)):
        stack = [(i, np.zeros(3), np.array([0, 0, 0, 1.0])) for i in order]
        while stack:
            i, pt, pr = stack.pop()
            t, r, _ = rig.local(i)
            t = tracks.get((i, 'translation'), [t] * len(times))[k]
            r = tracks.get((i, 'rotation'), [r] * len(times))[k]
            wt, wr = pt + qmat(pr) @ t, qmul(pr, r)
            out[nodes[i].get('name', str(i))][k] = wt
            stack.extend((c, wt, wr) for c in nodes[i].get('children', []))
    return times, out


def replay_character(blob, side=None):
    """Independent decode of an exported character GLB: FK of the animated arm, character space.

    Returns per-key (upper-arm direction, forearm direction) unit vectors.
    """
    rig = Rig(blob)
    doc, binary = rig.document, rig.binary
    anim = doc['animations'][0]
    side = side or doc['extras']['homunculus']['side']
    upper, fore = rig.index(f'upper_arm.{side}'), rig.index(f'forearm.{side}')
    hand = rig.index(f'hand.{side}')

    def read(index, width):
        acc = doc['accessors'][index]
        view = doc['bufferViews'][acc['bufferView']]
        if acc['componentType'] != 5126:
            raise ValueError('Unexpected animation component type')
        offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        if offset + acc['count'] * width * 4 > view.get('byteOffset', 0) + view['byteLength']:
            raise ValueError('Truncated animation accessor')
        return np.array(struct.unpack_from('<' + 'f' * (acc['count'] * width), binary, offset)).reshape(
            -1, width
        )

    tracks = {}
    for channel in anim['channels']:
        sampler = anim['samplers'][channel['sampler']]
        tracks[channel['target']['node']] = (read(sampler['input'], 1)[:, 0], read(sampler['output'], 4))
    if set(tracks) != {upper, fore}:
        raise ValueError('Animation must drive exactly the upper arm and forearm')
    shoulder_t, shoulder_r = rig.rest_world(rig.parent[upper])
    up_t = rig.local(upper)[0]
    fore_t = rig.local(fore)[0]
    hand_t = rig.local(hand)[0]
    out = []
    for qu, qf in zip(tracks[upper][1], tracks[fore][1]):
        wu = qmul(shoulder_r, qu)
        wf = qmul(wu, qf)
        p_upper = shoulder_t + qmat(shoulder_r) @ up_t
        p_fore = p_upper + qmat(wu) @ fore_t
        p_hand = p_fore + qmat(wf) @ hand_t
        out.append((unit(p_fore - p_upper, 'upper arm'), unit(p_hand - p_fore, 'forearm')))
    return tracks[upper][0], out


def b64(blob):
    return base64.b64encode(blob).decode()
