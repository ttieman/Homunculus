"""Synthetic stand-in for the private game character: same bone names and A-pose layout.

Writes nothing unless run as a script (CI writes outputs/test-character.glb for the browser test).
"""
import math
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from homunculus.retarget.character import mat_q, qinv, qmul, write_glb  # noqa: E402


def aim(direction, roll_hint=(0, 0, 1)):
    """World rotation whose +Y points along direction."""
    y = np.asarray(direction, float); y /= np.linalg.norm(y)
    z = np.asarray(roll_hint, float); z = z - np.dot(z, y) * y; z /= np.linalg.norm(z)
    return mat_q(np.column_stack([np.cross(y, z), y, z]))


def build(drop_bone=None):
    nodes, joints, world = [], [], {}

    def bone(name, parent, head, direction, hint=(0, 0, 1)):
        if name == drop_bone:
            return None
        rot = aim(direction, hint)
        if parent is None:
            t, r = np.array(head, float), rot
        else:
            ph, pr = world[parent]
            from homunculus.retarget.character import qmat
            t = qmat(qinv(pr)) @ (np.array(head, float) - ph)
            r = qmul(qinv(pr), rot)
        world[len(nodes)] = (np.array(head, float), rot)
        nodes.append({'name': name, 'translation': t.round(6).tolist(), 'rotation': r.round(8).tolist()})
        if parent is not None:
            nodes[parent].setdefault('children', []).append(len(nodes) - 1)
        joints.append(len(nodes) - 1)
        return len(nodes) - 1

    # Joint layout measured from the Bevy-playground stickman (A-pose, faces +Z, left on +X).
    root = bone('root', None, [0, 0, 0], [0, 1, 0])
    pelvis = bone('pelvis', root, [0, .9, 0], [0, 1, 0])
    spine = bone('spine', pelvis, [0, 1.07, 0], [0, 1, 0])
    chest = bone('chest', spine, [0, 1.25, 0], [0, 1, 0])
    neck = bone('neck', chest, [0, 1.41, 0], [0, 1, 0])
    bone('head', neck, [0, 1.49, 0], [0, 1, 0])
    for side, sx in (('L', 1), ('R', -1)):
        thigh = bone(f'thigh.{side}', pelvis, [.105*sx, .9, 0], [.036*sx, -.996, .085])
        shin = bone(f'shin.{side}', thigh, [.12*sx, .49, .035], [.027*sx, -.995, -.094])
        foot = bone(f'foot.{side}', shin, [.13*sx, .12, 0], [0, -.298, .954], (1, 0, 0))
        bone(f'toe.{side}', foot, [.13*sx, .07, .16], [0, 0, 1], (1, 0, 0))
    for side, sx in (('L', 1), ('R', -1)):
        sh = bone(f'shoulder.{side}', chest, [.13*sx, 1.34, 0], [sx, -.18, 0])
        up = bone(f'upper_arm.{side}', sh, [.24*sx, 1.32, 0], [.65*sx, -.75, -.09])
        if up is None:
            continue
        elbow = np.array([.24*sx, 1.32, 0]) + .29 * np.array([.65*sx, -.75, -.09]) / np.linalg.norm([.65, -.75, -.09])
        fa = bone(f'forearm.{side}', up, elbow, [.56*sx, -.81, .17])
        hand = elbow + .23 * np.array([.56*sx, -.81, .17]) / np.linalg.norm([.56, -.81, .17])
        bone(f'hand.{side}', fa, hand, [.36*sx, -.93, .1])

    # One small skinned triangle per joint so every bone visibly deforms something.
    positions, jidx, weights, inverse = [], [], [], []
    for j, index in enumerate(joints):
        head = world[index][0]
        positions += [head + [-.02, 0, 0], head + [.02, 0, 0], head + [0, .04, 0]]
        jidx += [[j, 0, 0, 0]] * 3
        weights += [[1, 0, 0, 0]] * 3
        h, r = world[index]
        from homunculus.retarget.character import qmat
        m = np.eye(4); m[:3, :3] = qmat(r); m[:3, 3] = h
        inverse.append(np.linalg.inv(m).T.reshape(-1).tolist())  # column-major
    binary = bytearray(); views = []; accessors = []

    def add(fmt, rows, kind, ctype, extra=None):
        flat = [v for row in rows for v in row]
        binary.extend(b'\0' * (-len(binary) % 4))
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': struct.calcsize('<' + fmt*len(flat))})
        binary.extend(struct.pack('<' + fmt*len(flat), *flat))
        accessors.append({'bufferView': len(views)-1, 'componentType': ctype, 'count': len(rows), 'type': kind, **(extra or {})})
        return len(accessors) - 1

    pts = np.array(positions)
    pos = add('f', pts.tolist(), 'VEC3', 5126, {'min': pts.min(0).tolist(), 'max': pts.max(0).tolist()})
    jo = add('B', jidx, 'VEC4', 5121)
    we = add('f', weights, 'VEC4', 5126)
    ib = add('f', inverse, 'MAT4', 5126)
    # A source clip on the chest, standing in for third-party clips the export must drop.
    clip_t = add('f', [[0], [1]], 'SCALAR', 5126, {'min': [0], 'max': [1]})
    clip_r = add('f', [nodes[chest]['rotation'], nodes[chest]['rotation']], 'VEC4', 5126)
    mesh_node = len(nodes)
    nodes.append({'name': 'Test_Mesh', 'mesh': 0, 'skin': 0})
    nodes.append({'name': 'Test_Rig', 'children': [mesh_node, root]})
    doc = {'asset': {'version': '2.0', 'generator': 'Homunculus test character'}, 'scene': 0,
           'scenes': [{'nodes': [len(nodes) - 1]}], 'nodes': nodes,
           'meshes': [{'primitives': [{'attributes': {'POSITION': pos, 'JOINTS_0': jo, 'WEIGHTS_0': we}, 'material': 0}]}],
           'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [.3, .3, .3, 1]}, 'doubleSided': True}],
           'skins': [{'joints': joints, 'inverseBindMatrices': ib}],
           'animations': [{'name': 'Licensed_Source_Clip', 'samplers': [{'input': clip_t, 'output': clip_r}],
                           'channels': [{'sampler': 0, 'target': {'node': chest, 'path': 'rotation'}}]}],
           'buffers': [{'byteLength': len(binary) + (-len(binary) % 4)}], 'bufferViews': views, 'accessors': accessors}
    return write_glb(doc, binary)


if __name__ == '__main__':
    out = Path(sys.argv[1] if len(sys.argv) > 1 else 'outputs/test-character.glb')
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(build())
    print(out)
