"""Which SAM 3D Body job service the editor uses: the usual remote one, or one on this PC.

The local service runs in its own WSL distro (see scripts/setup_local_sam.sh). It holds no GPU
memory while idle because each job loads the model in a separate process, and it is only
started when the toggle is turned on.
"""

import atexit
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DISTRO = 'homunculus-sam'
SAM_ROOT = '/opt/sam'
LOCAL_URL = 'http://127.0.0.1:8769'
MEASURED_PEAK_MIB = 5930  # 5.79 GiB allocated by the 2026-10-28 captures; the real need is a little higher


def wsl_path(path):
    drive, rest = str(path).replace('\\', '/').split(':', 1)
    return f'/mnt/{drive.lower()}{rest}'


def health(url, timeout=2):
    """The service's /health reply, or None if it does not answer."""
    try:
        with urllib.request.urlopen(url + '/health', timeout=timeout) as response:
            return json.load(response)
    except (OSError, urllib.error.URLError, ValueError):
        return None


def wsl(script, timeout=30):
    return subprocess.run(
        ['wsl.exe', '-d', DISTRO, '-u', 'root', '--', 'bash', '-c', script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


class Workers:
    def __init__(self, remote, local=LOCAL_URL, shell=wsl):
        self.remote, self.local, self.shell = remote, local, shell
        self.mode = 'remote'
        self.process = None

    @property
    def url(self):
        return self.local if self.mode == 'local' else self.remote

    def missing(self):
        """What the local install still needs, in the words the editor shows."""
        checkpoint = f'{SAM_ROOT}/checkpoints/sam-3d-body-dinov3'
        checks = {
            'the Python environment': f'{SAM_ROOT}/.venv/bin/python',
            'the SAM 3D Body source': f'{SAM_ROOT}/sam-3d-body/sam_3d_body/__init__.py',
            'the SAM 3D Body checkpoint': f'{checkpoint}/model.ckpt',
            'the MHR model': f'{checkpoint}/assets/mhr_model.pt',
            'the person detector': f'{SAM_ROOT}/checkpoints/vitdet/model_final_f05665.pkl',
        }
        script = '; '.join(f'[ -f "{path}" ] || echo "{name}"' for name, path in checks.items())
        try:
            result = self.shell(script)
        except (OSError, subprocess.TimeoutExpired):
            return [f'the {DISTRO} WSL distro']
        return result.stdout.split('\n')[:-1] if result.returncode == 0 else [f'the {DISTRO} WSL distro']

    def free_gpu_mib(self):
        try:
            out = subprocess.run(
                ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout
            return int(out.split()[0])
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
            return None

    def start_local(self):
        if health(self.local):
            return
        missing = self.missing()
        if missing:
            raise ValueError(
                'Local SAM is not installed yet. Missing: ' + ', '.join(missing) + '. See docs/CAPTURE.md.'
            )
        self.process = subprocess.Popen(
            [
                'wsl.exe',
                '-d',
                DISTRO,
                '-u',
                'root',
                '--',
                'bash',
                '-c',
                f'cd "{wsl_path(ROOT)}" && PYTHONDONTWRITEBYTECODE=1 HOMUNCULUS_SAM_ROOT={SAM_ROOT} '
                f'exec {SAM_ROOT}/.venv/bin/python -m worker.service --host 127.0.0.1 --port {self.local.rsplit(":", 1)[1]}',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(40):
            if health(self.local):
                return
            time.sleep(0.5)
        self.stop_local()
        raise RuntimeError('The local SAM worker did not start within 20 seconds')

    def stop_local(self):
        try:
            self.shell('pkill -f "[w]orker.service" || true', timeout=15)  # [w] so it can't match this shell
        except (OSError, subprocess.TimeoutExpired):
            pass
        if self.process:
            self.process.terminate()
            self.process = None

    def set_mode(self, mode):
        if mode not in ('remote', 'local'):
            raise ValueError('mode must be remote or local')
        if mode == self.mode:
            return self.status()
        if mode == 'local':
            self.start_local()
            atexit.register(self.stop_local)
        else:
            state = health(self.local)
            if state and state.get('active'):
                raise ValueError('A local SAM job is still running. Wait for it to finish before switching.')
            self.stop_local()
        self.mode = mode
        return self.status()

    def status(self):
        reply = {'mode': self.mode, 'url': self.url, 'reachable': health(self.url) is not None}
        if self.mode == 'local':
            reply['gpu_free_mib'] = self.free_gpu_mib()
            reply['gpu_needed_mib'] = MEASURED_PEAK_MIB
        return reply
