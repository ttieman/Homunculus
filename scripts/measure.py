"""Reproduce the first experiment and retain raw original-motion artifacts."""

from dataclasses import replace
from pathlib import Path
import sys
import json
import platform
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere: python scripts/measure.py
from homunculus.physics.settings import Edit
from homunculus.physics.simulate import run
from homunculus.export.gltf import export_gltf, replay_gltf


def main():
    out = Path('outputs')
    out.mkdir(exist_ok=True)
    summary = {'machine': platform.system(), 'python': platform.python_version(), 'cases': {}}
    for name, edit in [
        ('clean', Edit(obstacle=False)),
        ('blocked', Edit()),
        ('slow_loose', Edit(duration=6, strength=0.4, obstacle=False)),
    ]:
        result = run(edit)
        gltf = export_gltf(result)
        (out / f'{name}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        (out / f'{name}.gltf').write_text(json.dumps(gltf, indent=2), encoding='utf-8')
        replay_error = float(
            np.max(np.abs(np.array(replay_gltf(gltf)) - np.array([f['hand'] for f in result['frames']])))
        )
        summary['cases'][name] = {**result['metrics'], 'export_max_component_error_m': replay_error}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
