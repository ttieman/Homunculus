"""glTF 2.0: actual simulated local rotations, embedded buffers, visible rigid links."""
import base64
import struct
import math


def export_gltf(result):
    binary = bytearray()
    views, accessors = [], []

    def accessor(rows, kind, bounds=False):
        flat = [v for row in rows for v in row]
        offset = len(binary)
        binary.extend(struct.pack('<'+'f'*len(flat), *flat))
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(flat)*4})
        item = {'bufferView': len(views)-1, 'componentType': 5126, 'count': len(rows), 'type': kind}
        if bounds:
            item.update(min=[min(r[i] for r in rows) for i in range(len(rows[0]))],
                        max=[max(r[i] for r in rows) for i in range(len(rows[0]))])
        accessors.append(item)
        return len(accessors)-1

    # A unit cube, triangle soup. Children scale it without scaling joint offsets.
    corners = [(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)]
    triangles = [0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,3,7,6,3,6,2,1,2,6,1,6,5,0,4,7,0,7,3]
    pos = accessor([corners[i] for i in triangles], 'VEC3', True)
    times = accessor([[f['t']] for f in result['frames']], 'SCALAR', True)
    samplers, channels = [], []
    for joint in range(2):
        rot = accessor([[0,0,math.sin(f['q'][joint]/2),math.cos(f['q'][joint]/2)] for f in result['frames']], 'VEC4')
        samplers.append({'input': times, 'output': rot, 'interpolation': 'LINEAR'})
        channels.append({'sampler': joint, 'target': {'node': joint, 'path': 'rotation'}})
    return {'asset': {'version': '2.0', 'generator': 'Force Puppet'},
            'scene': 0, 'scenes': [{'nodes': [0,5]}],
            'nodes': [
                {'name':'shoulder.R','translation':[0,1.4,0],'children':[1,3]},
                {'name':'elbow.R','translation':[.34,0,0],'children':[2,4]},
                {'name':'hand.R','translation':[.29,0,0]},
                {'name':'upper_arm_mesh','mesh':0,'translation':[.17,0,0],'scale':[.17,.04,.04]},
                {'name':'forearm_mesh','mesh':0,'translation':[.145,0,0],'scale':[.145,.03,.03]},
                {'name':'visible_shoulder_support','mesh':0,'translation':[0,.7,0],'scale':[.035,.7,.035]}],
            'meshes':[{'primitives':[{'attributes':{'POSITION':pos},'material':0}]}],
            'materials':[{'doubleSided':True,'pbrMetallicRoughness':{'baseColorFactor':[.35,.9,.7,1],'metallicFactor':0,'roughnessFactor':.7}}],
            'animations':[{'name':'SimulatedReach','samplers':samplers,'channels':channels}],
            'buffers':[{'byteLength':len(binary),'uri':'data:application/octet-stream;base64,'+base64.b64encode(binary).decode()}],
            'bufferViews':views,'accessors':accessors,
            'extras':{'provenance':result['source'],'assistance':result['assistance'],'edit':result['edit'],
                      'note':'Rigid articulated arm; no skin or game-skeleton retargeting. Obstacle is not exported.'}}


def replay_gltf(document):
    """Independent buffer decode + quaternion FK; never reads source q or hand samples."""
    blob = base64.b64decode(document['buffers'][0]['uri'].split(',',1)[1])
    def read(index, width):
        acc = document['accessors'][index]
        view = document['bufferViews'][acc['bufferView']]
        values = struct.unpack_from('<'+'f'*(acc['count']*width), blob, view.get('byteOffset',0)+acc.get('byteOffset',0))
        return [values[i:i+width] for i in range(0,len(values),width)]
    anim = document['animations'][0]
    rotations = [read(s['output'],4) for s in anim['samplers']]
    hands = []
    for a,b in zip(*rotations):
        # Z-axis quaternion rotation matrix entries. Compose first and second rotation.
        ca,sa = 1-2*a[2]*a[2],2*a[2]*a[3]
        cb,sb = 1-2*b[2]*b[2],2*b[2]*b[3]
        l1 = document['nodes'][1]['translation'][0]
        l2 = document['nodes'][2]['translation'][0]
        root = document['nodes'][0]['translation']
        hands.append([root[0]+l1*ca+l2*(ca*cb-sa*sb), root[1]+l1*sa+l2*(sa*cb+ca*sb),root[2]])
    return hands
