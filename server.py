"""Local-only editor; each simulation request is self-contained and bounded."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import os
from puppet import Edit, run
from exporter import export_gltf
from meta import propose, MODEL

ROOT = Path(__file__).parent


class Handler(BaseHTTPRequestHandler):
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
        if self.path == '/api/status':
            return self.send(200,{'meta': 'configured; unverified' if os.environ.get('MODEL_API_KEY') else 'blocked: no credentials', 'model':MODEL})
        paths = {'/':('index.html','text/html; charset=utf-8'), '/app.js':('app.js','text/javascript; charset=utf-8')}
        if self.path not in paths:
            return self.send(404,{'error':'Not found'})
        name, mime = paths[self.path]
        self.send(200,(ROOT/'web'/name).read_bytes(),mime)

    def do_POST(self):
        if not self.local():
            return self.send(403,{'error':'Local origin required'})
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0 < size <= 16384:
                raise ValueError('Request size must be 1–16384 bytes')
            body = json.loads(self.rfile.read(size))
            edit = Edit.parse(body['edit'])
            if self.path == '/api/simulate':
                result = run(edit)
                return self.send(200,{'result':result,'gltf':export_gltf(result)})
            if self.path == '/api/propose':
                return self.send(200,propose(body['prompt'],edit))
            self.send(404,{'error':'Not found'})
        except (ValueError,KeyError,TypeError) as exc:
            self.send(400,{'error':str(exc)})
        except RuntimeError as exc:
            self.send(503,{'error':str(exc)})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    print(f'Force Puppet: http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()
