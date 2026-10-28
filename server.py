"""Local-only editor; each simulation request is self-contained and bounded."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
from puppet import Edit, run
from exporter import export_gltf
from meta import propose, propose_reference, MODEL, configured_key
from motion import prepare

from contracts import MAX_DOCUMENT_BYTES, object_value
import character

ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
    rig = None  # optional external character (see character.py)

    def send(self, status, data, content_type='application/json'):
        encoded = json.dumps(data,allow_nan=False).encode() if content_type=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(encoded)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        self.end_headers()
        self.wfile.write(encoded)

    def local(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://'+expected) == 'http://'+expected

    def do_GET(self):
        if not self.local():
            return self.send(403,{'error':'Local origin required'})
        if self.path == '/api/contracts':
            return self.send(200,{'max_document_bytes':MAX_DOCUMENT_BYTES})
        if self.path == '/api/status':
            return self.send(200,{'meta': 'configured; unverified' if configured_key() else 'blocked: no credentials', 'model':MODEL,
                                  'character': self.rig.summary() if self.rig else None})
        if self.path == '/character.glb':
            if not self.rig: return self.send(404,{'error':'No character configured'})
            return self.send(200,self.rig.blob,'model/gltf-binary')
        js = 'text/javascript; charset=utf-8'
        paths = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js',js),
                 '/stage3d.js':('stage3d.js',js), '/vendor/three.js':('vendor/three.js',js)}
        if self.path not in paths:
            return self.send(404,{'error':'Not found'})
        name, mime = paths[self.path]
        self.send(200,(ROOT/'web'/name).read_bytes(),mime)

    def do_POST(self):
        if not self.local():
            return self.send(403,{'error':'Local origin required'})
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= MAX_DOCUMENT_BYTES:
                raise ValueError(f'Request size must be 1–{MAX_DOCUMENT_BYTES} bytes')
            body = object_value(json.loads(self.rfile.read(size)),'request')
            if self.path == '/api/capture/validate':
                motion = prepare(body['capture'])
                return self.send(200,{'metadata':motion.metadata})
            if self.path == '/api/reference':
                from spatial import SpatialMotion
                from timeline import Timeline
                motion=prepare(body['capture'])
                if not isinstance(motion,SpatialMotion): raise ValueError('Spatial capture required')
                timeline=motion.timeline
                if body.get('three_poses') is True:
                    doc=timeline.document
                    keys=doc['keyframes']; doc['keyframes']=[keys[0],keys[len(keys)//2],keys[-1]]
                    ids={k['poseId'] for k in doc['keyframes']};doc['poses']={k:v for k,v in doc['poses'].items() if k in ids}
                    timeline=Timeline(doc)
                if body.get('duration') is not None: timeline=timeline.edited([{'operation':'set_duration','parameters':{'seconds':body['duration']}}])
                if body.get('commands'): timeline=timeline.edited(body['commands'])
                capture=body['capture'];capture['reference_animation']=timeline.document
                prepare(capture)
                return self.send(200,{'capture':capture,'reference':timeline.document})
            edit = Edit.parse(body['edit'])
            if self.path in ('/api/simulate','/api/synthesize'):
                motion = prepare(body['capture']) if body.get('capture') is not None else None
                if self.path == '/api/synthesize':
                    from spatial import SpatialMotion, synthesize
                    if not isinstance(motion,SpatialMotion): raise ValueError('Optimization requires a spatial capture')
                    result,report = synthesize(motion,edit)
                    result['optimization']=report
                else:
                    result = run(edit,motion)
                payload={'result':result,'gltf':export_gltf(result)}
                if self.rig:
                    result['retarget']=character.retarget(result,self.rig)
                    payload['character_glb']=character.b64(character.export_character_glb(self.rig,result['retarget'],
                        {'provenance':result['source'],'edit':result['edit'],'capture':result.get('capture')}))
                return self.send(200,payload)
            if self.path == '/api/propose':
                return self.send(200,propose_reference(body['prompt'],body['capture'],edit) if body.get('capture') is not None else propose(body['prompt'],edit))
            self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError,RecursionError) as exc:
            self.send(400,{'error':str(exc)})
        except RuntimeError as exc:
            self.send(503,{'error':str(exc)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--character',help='GLB game character to retarget onto (default: HOMUNCULUS_CHARACTER in the environment or .env.local)')
    args = parser.parse_args()
    path = args.character or character.configured_path()
    if path:
        Handler.rig = character.load_rig(path)
        print(f'Character: {Handler.rig.source} ({Handler.rig.summary()["mapping"]})',flush=True)
    print(f'Force Puppet: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
