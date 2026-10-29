"""Backfill full-body keypoints into a finished worker run, from its preserved raw-*.npz files.

    python add_body.py private/run-001 private/run-001/capture-body.json

No inference runs: this only copies SAM's saved pred_keypoints_3d (the official MHR70
names, in body.py) into each capture frame, so older captures can drive the whole
character. The capture's frames, basis and provenance are kept as they are.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # run from anywhere: python scripts/add_body.py
from homunculus.retarget.body import MHR70


def add_body(directory, capture=None):
    directory = Path(directory)
    capture = capture or json.loads((directory / 'capture.json').read_text(encoding='utf-8'))
    for frame in capture['frames']:
        path = directory / f"raw-{frame['frame_index']:06d}.npz"
        if frame.get('arm') is None:
            continue  # no detection in this frame; the importer reports it
        if not path.is_file():
            raise ValueError(f'Missing preserved SAM output {path.name}')
        with np.load(path, allow_pickle=False) as raw:
            points = np.asarray(raw['pred_keypoints_3d'], dtype=float)
        if points.ndim != 2 or points.shape[0] < len(MHR70) or points.shape[1] != 3 or not np.isfinite(points[:len(MHR70)]).all():
            raise ValueError(f'{path.name}: expected at least {len(MHR70)} finite 3D keypoints, got {points.shape}')
        frame['body'] = points[:len(MHR70)].tolist()
    capture['body_keypoints'] = list(MHR70)
    return capture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('run_directory', type=Path, help='worker output folder with capture.json and raw-*.npz')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    out = add_body(args.run_directory)
    args.output.write_text(json.dumps(out, allow_nan=False), encoding='utf-8')
    print(f"{args.output}: {sum('body' in f for f in out['frames'])}/{len(out['frames'])} frames with full-body keypoints")
