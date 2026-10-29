"""Load the external game character (GLB) and read its arm chains.

The character file stays outside this repository (no private game assets in Git);
point the server at it with --character, HOMUNCULUS_CHARACTER or .env.local.

Rig contract (the Bevy-playground stickman): glTF 2.0 binary, one skin, Y-up,
character faces +Z, bones point along local +Y, and these names exist per side:
shoulder.L/R -> upper_arm.L/R -> forearm.L/R -> hand.L/R.
"""

import json
import os
import struct
from pathlib import Path

import numpy as np
from homunculus import ROOT
from homunculus.retarget.arm import CHAIN, VIEWS
from homunculus.retarget.geometry import qmat, qmul

MAX_CHARACTER_BYTES = 32 * 1024 * 1024


def read_glb(blob):
    if len(blob) < 20 or blob[:4] != b'glTF' or struct.unpack_from('<I', blob, 4)[0] != 2:
        raise ValueError('Character must be a glTF 2.0 binary (.glb)')
    if struct.unpack_from('<I', blob, 8)[0] != len(blob):
        raise ValueError('Character GLB length header does not match the file')
    length, kind = struct.unpack_from('<II', blob, 12)
    if kind != 0x4E4F534A or 20 + length > len(blob):
        raise ValueError('Character GLB has no JSON chunk')
    document = json.loads(blob[20 : 20 + length])
    offset, binary = 20 + length, b''
    if offset + 8 <= len(blob):
        size, kind = struct.unpack_from('<II', blob, offset)
        if kind != 0x004E4942 or offset + 8 + size > len(blob):
            raise ValueError('Character GLB binary chunk is malformed')
        binary = bytes(blob[offset + 8 : offset + 8 + size])
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
        return (
            np.array(node.get('translation', [0, 0, 0]), dtype=float),
            np.array(node.get('rotation', [0, 0, 0, 1]), dtype=float),
            np.array(node.get('scale', [1, 1, 1]), dtype=float),
        )

    def rest_world(self, i):
        """World (character-space) position and rotation in the rest pose."""
        t, r, s = self.local(i)
        if not np.allclose(s, 1, atol=1e-4):
            raise ValueError(
                f'Scaled node {self.document["nodes"][i].get("name", i)} is not supported on the arm chain'
            )
        if i in self.parent:
            pt, pr = self.rest_world(self.parent[i])
            return pt + qmat(pr) @ t, qmul(pr, r)
        return t, r

    def summary(self):
        side = {}
        for s in 'LR':
            u, f, h = (self.index(f'{b}.{s}') for b in CHAIN[1:])
            side[s] = {
                'shoulder_m': self.rest_world(u)[0].round(4).tolist(),
                'upper_arm_m': round(float(np.linalg.norm(self.local(f)[0])), 4),
                'forearm_m': round(float(np.linalg.norm(self.local(h)[0])), 4),
            }
        return {'source': self.source, 'bytes': len(self.blob), 'arms': side, 'views': VIEWS}


def load_rig(path):
    path = Path(path).expanduser()
    if not path.is_file():
        raise ValueError(f'Character file not found: {path}')
    if path.stat().st_size > MAX_CHARACTER_BYTES:
        raise ValueError('Character file exceeds 32 MiB')
    return Rig(path.read_bytes(), path.name)


def configured_path(root=ROOT):
    value = os.environ.get('HOMUNCULUS_CHARACTER', '').strip()
    env = root / '.env.local'
    if not value and env.is_file():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if line.strip().startswith('HOMUNCULUS_CHARACTER='):
                value = line.strip().split('=', 1)[1].strip().strip('"').strip("'")
    return value or None
