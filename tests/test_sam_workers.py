from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import subprocess
import threading

import pytest

from homunculus.editor.sam_workers import Workers, wsl_path


@pytest.fixture
def fake_service():
    state = {'active': 0}

    class Service(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'ok': True, 'active': state['active']}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Service)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}', state
    server.shutdown()


def shell(stdout='', code=0):
    return lambda script, timeout=30: subprocess.CompletedProcess([], code, stdout, '')


def test_defaults_to_the_remote_worker():
    workers = Workers('http://remote')
    assert workers.mode == 'remote' and workers.url == 'http://remote'


def test_refuses_local_and_names_what_is_missing():
    workers = Workers('http://remote', 'http://127.0.0.1:9', shell('the SAM 3D Body checkpoint\n'))
    with pytest.raises(ValueError, match='Missing: the SAM 3D Body checkpoint'):
        workers.set_mode('local')
    assert workers.mode == 'remote'


def test_missing_distro_is_reported():
    def absent(script, timeout=30):
        raise FileNotFoundError('wsl.exe')

    assert Workers('http://remote', shell=absent).missing() == ['the homunculus-sam WSL distro']
    assert Workers('http://remote', shell=shell(code=1)).missing() == ['the homunculus-sam WSL distro']


def test_switches_to_a_running_local_service_and_back(fake_service):
    url, _ = fake_service
    workers = Workers('http://remote', url, shell())
    assert workers.set_mode('local')['reachable'] is True
    assert workers.url == url
    assert workers.set_mode('remote')['mode'] == 'remote'


def test_will_not_stop_the_local_service_during_a_job(fake_service):
    url, state = fake_service
    workers = Workers('http://remote', url, shell())
    workers.set_mode('local')
    state['active'] = 1
    with pytest.raises(ValueError, match='still running'):
        workers.set_mode('remote')
    assert workers.mode == 'local'


def test_rejects_unknown_mode_and_maps_windows_paths():
    with pytest.raises(ValueError, match='mode must be'):
        Workers('http://remote').set_mode('cloud')
    assert wsl_path(r'C:\Users\me\repo') == '/mnt/c/Users/me/repo'
