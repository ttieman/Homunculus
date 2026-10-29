"""Separate reconstruction diagnostics from optional annotated 2D accuracy."""

import json
import numpy as np


def capture_quality(bundle, annotations=None):
    frames = bundle['frames']
    missing = sum(f.get('arm') is None for f in frames)
    lengths = []
    outside = []
    size = bundle.get('provenance', {}).get('image_size_px')
    for frame in frames:
        if frame.get('arm') is not None:
            p = np.array(frame['arm'], dtype=float)
            if p.shape == (3, 3) and np.isfinite(p).all():
                lengths.append(np.linalg.norm(np.diff(p, axis=0), axis=1))
        if size and frame.get('arm_pixels') is not None:
            p = np.array(frame['arm_pixels'], dtype=float)
            if p.shape == (3, 2) and (
                not np.isfinite(p).all()
                or np.any(p[:, 0] < 0)
                or np.any(p[:, 0] >= size[0])
                or np.any(p[:, 1] < 0)
                or np.any(p[:, 1] >= size[1])
            ):
                outside.append(frame['t'])
    report = {
        'frames': len(frames),
        'missing_frames': missing,
        'out_of_frame_timestamps': outside if size else None,
        'confidence': 'not supplied; no confidence score inferred',
        'accuracy_3d': 'not measured; requires independent calibrated reference',
        'anatomical_twist': 'bend-plane convention, not measured',
        'reprojection_accuracy': {'status': 'not measured; no annotations'},
        'interpretation': 'Segment-length variation is a diagnostic, not a calibrated confidence or accuracy measure.',
    }
    if lengths:
        values = np.array(lengths)
        report['segment_length_coefficient_of_variation'] = (
            values.std(axis=0) / np.maximum(values.mean(axis=0), 1e-9)
        ).tolist()
    if annotations is not None:
        if (
            annotations.get('schema') != 'homunculus.annotations.v1'
            or annotations.get('video_sha256') != bundle['provenance']['video_sha256']
        ):
            raise ValueError('Annotation source/schema mismatch')
        groups = {}
        times = np.array([f['t'] for f in frames])
        for label in annotations.get('frames', []):
            i = int(np.argmin(np.abs(times - label['t'])))
            if abs(times[i] - label['t']) > 0.02:
                raise ValueError('Annotation has no matching capture timestamp within 20 ms')
            prediction = np.array(frames[i].get('arm_pixels'), dtype=float)
            if prediction.shape != (3, 2) or not np.isfinite(prediction).all():
                continue
            for j, point in enumerate(label['arm_pixels']):
                if point is None:
                    continue
                point = np.array(point, dtype=float)
                if point.shape != (2,) or not np.isfinite(point).all():
                    raise ValueError('Annotation must contain finite pixel coordinates or null')
                group = label.get('condition', 'unspecified')
                groups.setdefault(group, []).append(float(np.sum((prediction[j] - point) ** 2)))
        report['reprojection_accuracy'] = {
            'status': 'annotated 2D landmarks; not 3D accuracy',
            'by_condition': {
                k: {'landmarks': len(v), 'rmse_pixels': float(np.sqrt(np.mean(v)))} for k, v in groups.items()
            },
        }
    return report


if __name__ == '__main__':
    import argparse
    from pathlib import Path

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('capture', type=Path)
    p.add_argument('--annotations', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    report = capture_quality(
        json.loads(args.capture.read_text(encoding='utf-8')),
        json.loads(args.annotations.read_text(encoding='utf-8')) if args.annotations else None,
    )
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
