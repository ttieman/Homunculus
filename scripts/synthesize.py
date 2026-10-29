"""Offline, reproducible spatial synthesis and independently checked glTF export."""

import argparse
import json
from pathlib import Path
import sys
import numpy as np

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1])
)  # run from anywhere: python scripts/synthesize.py
from homunculus.capture.spatial import prepare_spatial
from homunculus.physics.spatial import synthesize
from homunculus.physics.settings import Edit
from homunculus.export.gltf import export_gltf, replay_gltf


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--duration', type=float)
    p.add_argument('--obstacle', action='store_true')
    args = p.parse_args()
    if args.output.exists():
        p.error('Choose a new output directory')
    bundle = json.loads(args.capture.read_text(encoding='utf-8'))
    bundle['retargeting'] = 'spatial_arm_v1'
    motion = prepare_spatial(bundle)
    edit = Edit.parse({'duration': args.duration or float(motion.times[-1]), 'obstacle': args.obstacle})
    result, report = synthesize(motion, edit)
    gltf = export_gltf(result)
    error = float(
        np.max(np.abs(np.asarray(replay_gltf(gltf)) - np.array([f['hand'] for f in result['frames']])))
    )
    if error > 1e-6:
        raise RuntimeError('Export transform verification failed')
    report.update(export_max_component_error_m=error, capture=motion.metadata)
    from homunculus.export.assets import save_asset

    save_asset(args.output, bundle, motion, result, report)
    print(
        json.dumps(
            {
                'output': str(args.output),
                'selected': report['selected'],
                'metrics': result['metrics'],
                'export_error_m': error,
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
