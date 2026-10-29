"""Retarget the supported-arm result onto an external game character (GLB).

The character file stays outside this repository (no private game assets in Git);
point the server at it with --character, HOMUNCULUS_CHARACTER or .env.local.

Rig contract (the Bevy-playground stickman): glTF 2.0 binary, one skin, Y-up,
character faces +Z, bones point along local +Y, and these names exist per side:
shoulder.L/R -> upper_arm.L/R -> forearm.L/R -> hand.L/R.

The puppet frame is the camera frame (X image-right, Y up, Z toward the camera), so
the mapping depends on how the person stood in the recording (VIEWS):
- front: the person faces the camera. Identity: image-right is the character's
  left (+X), toward-camera is its forward (+Z). Default for 3D (spatial) captures.
- side: side-on reach. Puppet +X (the reach) is the character's forward and +Z
  points away from the body on the captured side. Default for planar captures and
  the procedural demo, which are side-on by construction.
Only segment directions transfer; the character
keeps its own proportions. The upper-arm roll is chosen so the elbow bends about
the upper arm's local X axis (the rig's hinge); with a straight arm the previous
bend plane is kept. The rest of the body stays in its rest pose.
"""
import base64
import copy
import json
import math
import os
import struct
from pathlib import Path

import numpy as np

MAX_CHARACTER_BYTES = 32 * 1024 * 1024
CHAIN = ('shoulder', 'upper_arm', 'forearm', 'hand')
STRAIGHT_SIN = math.sin(math.radians(2))


# Quaternions are glTF order [x, y, z, w].
def qmul(a, b):
    x1, y1, z1, w1 = a; x2, y2, z2, w2 = b
    return np.array([w1*x2 + x1*w2 + y1*z2 - z1*y2, w1*y2 - x1*z2 + y1*w2 + z1*x2,
                     w1*z2 + x1*y2 - y1*x2 + z1*w2, w1*w2 - x1*x2 - y1*y2 - z1*z2])


def qinv(q):
    return np.array([-q[0], -q[1], -q[2], q[3]]) / float(np.dot(q, q))


def qmat(q):
    x, y, z, w = np.asarray(q, dtype=float) / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def mat_q(m):
    t = np.trace(m)
    if t > 0:
        s = math.sqrt(t + 1) * 2
        q = [(m[2, 1]-m[1, 2])/s, (m[0, 2]-m[2, 0])/s, (m[1, 0]-m[0, 1])/s, s/4]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [s/4, (m[0, 1]+m[1, 0])/s, (m[0, 2]+m[2, 0])/s, (m[2, 1]-m[1, 2])/s]
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1]+m[1, 0])/s, s/4, (m[1, 2]+m[2, 1])/s, (m[0, 2]-m[2, 0])/s]
    else:
        s = math.sqrt(1 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2]+m[2, 0])/s, (m[1, 2]+m[2, 1])/s, s/4, (m[1, 0]-m[0, 1])/s]
    q = np.array(q)
    return q / np.linalg.norm(q)


def read_glb(blob):
    if len(blob) < 20 or blob[:4] != b'glTF' or struct.unpack_from('<I', blob, 4)[0] != 2:
        raise ValueError('Character must be a glTF 2.0 binary (.glb)')
    if struct.unpack_from('<I', blob, 8)[0] != len(blob):
        raise ValueError('Character GLB length header does not match the file')
    length, kind = struct.unpack_from('<II', blob, 12)
    if kind != 0x4E4F534A or 20 + length > len(blob):
        raise ValueError('Character GLB has no JSON chunk')
    document = json.loads(blob[20:20+length])
    offset, binary = 20 + length, b''
    if offset + 8 <= len(blob):
        size, kind = struct.unpack_from('<II', blob, offset)
        if kind != 0x004E4942 or offset + 8 + size > len(blob):
            raise ValueError('Character GLB binary chunk is malformed')
        binary = bytes(blob[offset+8:offset+8+size])
    return document, binary


def write_glb(document, binary):
    text = json.dumps(document, separators=(',', ':'), allow_nan=False).encode()
    text += b' ' * (-len(text) % 4)
    binary = bytes(binary) + b'\0' * (-len(binary) % 4)
    total = 12 + 8 + len(text) + (8 + len(binary) if binary else 0)
    out = struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<II', len(text), 0x4E4F534A) + text
    if binary:
        out += struct.pack('<II', len(binary), 0x004E4942) + binary
    return out


class Rig:
    def __init__(self, blob, source='character.glb'):
        self.blob = bytes(blob)
        self.source = source
        self.document, self.binary = read_glb(self.blob)
        nodes = self.document.get('nodes') or []
        if len(self.document.get('skins') or []) != 1:
            raise ValueError('Character must contain exactly one skin')
        self.names = {}
        for i, node in enumerate(nodes):
            if 'matrix' in node:
                raise ValueError(f'Node {node.get("name", i)} uses a matrix; TRS nodes are required')
            if node.get('name') in self.names:
                raise ValueError(f'Duplicate node name {node["name"]}')
            if node.get('name'):
                self.names[node['name']] = i
        self.parent = {c: i for i, n in enumerate(nodes) for c in n.get('children', [])}
        joints = set(self.document['skins'][0]['joints'])
        for side in 'LR':
            chain = [self.index(f'{bone}.{side}') for bone in CHAIN]
            if any(j not in joints for j in chain):
                raise ValueError(f'{side} arm bones must belong to the skin')
            for parent, child in zip(chain, chain[1:]):
                if self.parent.get(child) != parent:
                    raise ValueError(f'{nodes[child]["name"]} must be a child of {nodes[parent]["name"]}')

    def index(self, name):
        if name not in self.names:
            raise ValueError(f'Character is missing bone {name}')
        return self.names[name]

    def local(self, i):
        node = self.document['nodes'][i]
        return (np.array(node.get('translation', [0, 0, 0]), dtype=float),
                np.array(node.get('rotation', [0, 0, 0, 1]), dtype=float),
                np.array(node.get('scale', [1, 1, 1]), dtype=float))

    def rest_world(self, i):
        """World (character-space) position and rotation in the rest pose."""
        t, r, s = self.local(i)
        if not np.allclose(s, 1, atol=1e-4):
            raise ValueError(f'Scaled node {self.document["nodes"][i].get("name", i)} is not supported on the arm chain')
        if i in self.parent:
            pt, pr = self.rest_world(self.parent[i])
            return pt + qmat(pr) @ t, qmul(pr, r)
        return t, r

    def summary(self):
        side = {}
        for s in 'LR':
            u, f, h = (self.index(f'{b}.{s}') for b in CHAIN[1:])
            side[s] = {'shoulder_m': self.rest_world(u)[0].round(4).tolist(),
                       'upper_arm_m': round(float(np.linalg.norm(self.local(f)[0])), 4),
                       'forearm_m': round(float(np.linalg.norm(self.local(h)[0])), 4)}
        return {'source': self.source, 'bytes': len(self.blob), 'arms': side,
                'views': VIEWS}


def load_rig(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f'Character file not found: {path}')
    if path.stat().st_size > MAX_CHARACTER_BYTES:
        raise ValueError('Character file exceeds 32 MiB')
    return Rig(path.read_bytes(), path.name)


def configured_path(root=Path(__file__).parent):
    value = os.environ.get('HOMUNCULUS_CHARACTER', '').strip()
    env = root / '.env.local'
    if not value and env.is_file():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('HOMUNCULUS_CHARACTER='):
                value = line.strip().split('=', 1)[1].strip().strip('"').strip("'")
    return value or None


def side_of(result):
    return 'L' if (result.get('capture') or {}).get('provenance', {}).get('side') == 'left' else 'R'


VIEWS = {'front': 'person faces the camera: image-right -> character left (+X), toward camera -> forward (+Z)',
         'side': 'side-on: puppet +X reach -> character forward (+Z), puppet +Z -> outward on the captured side'}


def default_view(result):
    return 'front' if result.get('rig') == 'spatial_arm_v1' else 'side'


def mapping(side, view):
    """3x3 matrix M with character = M @ puppet (a rotation, or a mirror for side-on left arms)."""
    if view == 'front':
        return np.eye(3)
    if view != 'side':
        raise ValueError(f'Unknown recording view {view!r}; use one of {sorted(VIEWS)}')
    return np.array([[0, 0, 1 if side == 'L' else -1], [0, 1, 0], [1, 0, 0]], dtype=float)


def to_character(v, side, view='side'):
    """Puppet direction -> character direction (see module docstring)."""
    return mapping(side, view) @ np.asarray(v, dtype=float)


def puppet_arm(frame):
    if 'elbow' in frame and 'hand' in frame:
        return np.array(frame['elbow'], dtype=float), np.array(frame['hand'], dtype=float)
    a, b = frame['q'][0], frame['q'][0] + frame['q'][1]
    elbow = np.array([.34*math.cos(a), 1.4 + .34*math.sin(a), 0])
    return elbow, elbow + [.29*math.cos(b), .29*math.sin(b), 0]


def unit(v, what):
    n = np.linalg.norm(v)
    if not np.isfinite(n) or n < 1e-9:
        raise ValueError(f'Degenerate {what} direction')
    return v / n


def retarget(result, rig, side=None, view=None):
    side = side or side_of(result)
    view = view or default_view(result)
    to_char = mapping(side, view)
    shoulder, upper, fore = (rig.index(f'{b}.{side}') for b in CHAIN[:3])
    shoulder_world = rig.rest_world(shoulder)[1]
    inv_shoulder = qinv(shoulder_world)
    root = np.array([0, 1.4, 0])
    directions = []
    for frame in result['frames']:
        elbow, hand = puppet_arm(frame)
        directions.append((unit(to_char @ (elbow - root), 'upper arm'),
                           unit(to_char @ (hand - elbow), 'forearm')))
    # Seed the bend plane from the first visibly bent frame (else the most bent one; rest +Z if never bent).
    bend = qmat(rig.rest_world(upper)[1])[:, 2]
    perpendiculars = [d2 - np.dot(d2, d1) * d1 for d1, d2 in directions]
    sizes = [np.linalg.norm(v) for v in perpendiculars]
    seed = next((i for i, n in enumerate(sizes) if n > STRAIGHT_SIN), int(np.argmax(sizes)))
    if sizes[seed] > 1e-9:
        bend = perpendiculars[seed] / sizes[seed]
    previous = None
    frames = []
    for frame, (d1, d2) in zip(result['frames'], directions):
        perpendicular = d2 - np.dot(d2, d1) * d1
        if np.linalg.norm(perpendicular) > STRAIGHT_SIN:
            bend = perpendicular / np.linalg.norm(perpendicular)
        else:
            bend = bend - np.dot(bend, d1) * d1
            if np.linalg.norm(bend) < 1e-6:  # bend plane lost exactly along the arm; pick any normal
                bend = np.cross(d1, [1, 0, 0] if abs(d1[0]) < .9 else [0, 0, 1])
            bend /= np.linalg.norm(bend)
        x = np.cross(d1, bend)
        world_upper = mat_q(np.column_stack([x, d1, bend]))
        local_upper = qmul(inv_shoulder, world_upper)
        # Signed hinge angle in the bend plane; slightly negative only inside the straight-arm zone.
        angle = math.atan2(float(np.dot(d2, bend)), float(np.dot(d2, d1)))
        local_fore = np.array([math.sin(angle/2), 0, 0, math.cos(angle/2)])
        if previous is not None and np.dot(previous, local_upper) < 0:
            local_upper = -local_upper  # keep the quaternion hemisphere continuous for LINEAR sampling
        previous = local_upper
        frames.append({'t': float(frame['t']), 'rotations_xyzw': [local_upper.tolist(), local_fore.tolist()]})
    return {'schema': 'homunculus.retarget.v1', 'character': rig.source, 'side': side,
            'bones': [rig.document['nodes'][upper]['name'], rig.document['nodes'][fore]['name']],
            'nodes': [upper, fore], 'view': view, 'mapping': VIEWS[view],
            'character_to_puppet': to_char.T.tolist(),
            'note': 'Arm segment directions only; character proportions and rest body pose are kept.',
            'frames': frames}


def export_character_glb(rig, retargeted, extras=None):
    """The character's mesh, skin and material plus one new clip; source clips are dropped."""
    src = rig.document
    doc = {k: copy.deepcopy(src[k]) for k in ('asset', 'scene', 'scenes', 'nodes', 'meshes', 'skins',
                                               'materials', 'textures', 'images', 'samplers',
                                               'extensionsUsed', 'extensionsRequired') if k in src}
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
    used_views = {src['accessors'][a]['bufferView'] for a in used_accessors if 'bufferView' in src['accessors'][a]}
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
        chunk = rig.binary[start:start + view['byteLength']]
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
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(flat)*4})
        binary.extend(struct.pack('<' + 'f'*len(flat), *flat))
        acc = {'bufferView': len(views)-1, 'componentType': 5126, 'count': len(rows), 'type': kind}
        if bounds:
            acc['min'] = [min(r[i] for r in rows) for i in range(len(rows[0]))]
            acc['max'] = [max(r[i] for r in rows) for i in range(len(rows[0]))]
        accessors.append(acc)
        return len(accessors)-1

    frames = retargeted['frames']
    times = add([[f['t'] - frames[0]['t']] for f in frames], 'SCALAR', True)
    samplers, channels = [], []
    for joint, node in enumerate(retargeted['nodes']):
        samplers.append({'input': times, 'output': add([f['rotations_xyzw'][joint] for f in frames], 'VEC4'),
                         'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': node, 'path': 'rotation'}})
    if retargeted.get('translation_node') is not None:
        samplers.append({'input': times, 'output': add([f['translation'] for f in frames], 'VEC3'), 'interpolation': 'LINEAR'})
        channels.append({'sampler': len(samplers) - 1, 'target': {'node': retargeted['translation_node'], 'path': 'translation'}})
    doc['animations'] = [{'name': 'Homunculus_Body' if retargeted.get('mode') == 'body' else 'Homunculus_Reach',
                          'samplers': samplers, 'channels': channels}]
    doc['buffers'] = [{'byteLength': len(binary) + (-len(binary) % 4)}]
    doc['bufferViews'] = views
    doc['accessors'] = accessors
    doc['extras'] = {'homunculus': {'mode': retargeted.get('mode', 'arm'), 'side': retargeted['side'], 'bones': retargeted['bones'],
                                    'view': retargeted['view'], 'mapping': retargeted['mapping'], 'note': retargeted['note'],
                                    **(extras or {})}}
    return write_glb(doc, binary)


def replay_pose(blob):
    """Independent decode of an exported character GLB: FK of the whole rig at every key.

    Returns (times, {node name: K x 3 world positions in character space}).
    """
    rig = Rig(blob)
    doc, binary = rig.document, rig.binary
    anim = doc['animations'][0]

    def read(index, width):
        acc = doc['accessors'][index]; view = doc['bufferViews'][acc['bufferView']]
        if acc['componentType'] != 5126:
            raise ValueError('Unexpected animation component type')
        offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        if offset + acc['count']*width*4 > view.get('byteOffset', 0) + view['byteLength']:
            raise ValueError('Truncated animation accessor')
        return np.array(struct.unpack_from('<' + 'f'*(acc['count']*width), binary, offset)).reshape(-1, width)

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
        stack = [(i, np.zeros(3), np.array([0, 0, 0, 1.])) for i in order]
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
        acc = doc['accessors'][index]; view = doc['bufferViews'][acc['bufferView']]
        if acc['componentType'] != 5126:
            raise ValueError('Unexpected animation component type')
        offset = view.get('byteOffset', 0) + acc.get('byteOffset', 0)
        if offset + acc['count']*width*4 > view.get('byteOffset', 0) + view['byteLength']:
            raise ValueError('Truncated animation accessor')
        return np.array(struct.unpack_from('<' + 'f'*(acc['count']*width), binary, offset)).reshape(-1, width)

    tracks = {}
    for channel in anim['channels']:
        sampler = anim['samplers'][channel['sampler']]
        tracks[channel['target']['node']] = (read(sampler['input'], 1)[:, 0], read(sampler['output'], 4))
    if set(tracks) != {upper, fore}:
        raise ValueError('Animation must drive exactly the upper arm and forearm')
    shoulder_t, shoulder_r = rig.rest_world(rig.parent[upper])
    up_t = rig.local(upper)[0]; fore_t = rig.local(fore)[0]; hand_t = rig.local(hand)[0]
    out = []
    for qu, qf in zip(tracks[upper][1], tracks[fore][1]):
        wu = qmul(shoulder_r, qu); wf = qmul(wu, qf)
        p_upper = shoulder_t + qmat(shoulder_r) @ up_t
        p_fore = p_upper + qmat(wu) @ fore_t
        p_hand = p_fore + qmat(wf) @ hand_t
        out.append((unit(p_fore - p_upper, 'upper arm'), unit(p_hand - p_fore, 'forearm')))
    return tracks[upper][0], out


def b64(blob):
    return base64.b64encode(blob).decode()
