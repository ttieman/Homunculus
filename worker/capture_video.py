"""Offline SAM worker. Run inside the official SAM 3D Body environment, from the repository
(or deployed) root: python -m worker.capture_video VIDEO ...

No credentials, remote API, or background service changes.
One stationary person inside a fixed bounding box: given with --bbox, or found with
--detect (SAM 3D Body's ViTDet human detector on a few frames spread over the clip).
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from homunculus.contracts import MAX_FRAMES, SampleGrid


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def detect_box(args, p, probes=8, pad=0.1):
    """One fixed ROI covering the main person across the capture window."""
    import cv2
    import numpy as np
    import torch
    from tools.build_detector import HumanDetector

    detector = HumanDetector('vitdet', device='cuda', path=str(args.detect))
    video = cv2.VideoCapture(str(args.video))
    fps = video.get(cv2.CAP_PROP_FPS) or 30
    count = int(video.get(cv2.CAP_PROP_FRAME_COUNT))
    first = int(args.start * fps)
    last = min(count - 1, int((args.start + args.seconds) * fps))
    boxes = []
    for index in np.linspace(first, max(first, last), probes).round().astype(int):
        video.set(cv2.CAP_PROP_POS_FRAMES, int(index))
        ok, bgr = video.read()
        if not ok:
            continue
        h, w = bgr.shape[:2]
        found = detector.run_human_detection(bgr, default_to_full_image=False)
        if len(found):
            boxes.append(max(found, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])))
    video.release()
    del detector
    torch.cuda.empty_cache()
    if not boxes:
        p.error('No person detected; pass --bbox')
    b = np.array(boxes)
    x1, y1 = b[:, :2].min(0)
    x2, y2 = b[:, 2:].max(0)
    dx, dy = (x2 - x1) * pad, (y2 - y1) * pad
    return [float(max(0, x1 - dx)), float(max(0, y1 - dy)), float(min(w, x2 + dx)), float(min(h, y2 + dy))]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('video', type=Path)
    p.add_argument('--sam-root', type=Path, required=True)
    p.add_argument('--checkpoint', type=Path, required=True)
    p.add_argument('--mhr', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--bbox', type=float, nargs=4, metavar=('X1', 'Y1', 'X2', 'Y2'))
    p.add_argument(
        '--detect',
        type=Path,
        metavar='VITDET_DIR',
        help='Find the person instead of --bbox; directory holding model_final_f05665.pkl',
    )
    p.add_argument(
        '--basis',
        type=float,
        nargs=9,
        required=True,
        help='Row-major native-to-puppet proper rotation, verified in preview',
    )
    p.add_argument(
        '--spatial', action='store_true', help='Capture up to 30 seconds for spatial arm synthesis'
    )
    p.add_argument('--side', choices=['right', 'left'], default='right')
    p.add_argument('--start', type=float, default=0)
    p.add_argument('--seconds', type=float, default=4)
    p.add_argument('--sample-hz', type=float, default=15)
    args = p.parse_args()
    if (
        not 2.1 <= args.seconds <= (30 if args.spatial else 10)
        or not 5 <= args.sample_hz <= 30
        or not args.start >= 0
    ):
        p.error('Use 2.1–10 seconds, 5–30 Hz and a nonnegative start')
    if int(args.seconds * args.sample_hz) + 1 > MAX_FRAMES:
        p.error(f'Capture exceeds {MAX_FRAMES} frame budget')
    for name in ('video', 'checkpoint', 'mhr'):
        if not getattr(args, name).is_file():
            p.error(f'BLOCKED: {name} file unavailable')
    if args.output.exists():
        p.error('Output already exists; choose a new directory')
    if (args.bbox is None) == (args.detect is None):
        p.error('Give exactly one of --bbox or --detect')
    sys.path.insert(0, str(args.sam_root.resolve()))
    import cv2
    import numpy as np
    import torch
    from sam_3d_body import load_sam_3d_body, SAM3DBodyEstimator
    from sam_3d_body.metadata.mhr70 import mhr_names
    from homunculus.capture.prepare import prepare

    if not torch.cuda.is_available():
        p.error('CUDA unavailable in this SAM environment')
    basis = np.asarray(args.basis).reshape(3, 3)
    if not np.allclose(basis @ basis.T, np.eye(3), atol=1e-5) or not np.isclose(np.linalg.det(basis), 1):
        p.error('basis must be a proper orthonormal rotation')
    revision = subprocess.check_output(
        ['git', '-C', str(args.sam_root), 'rev-parse', 'HEAD'], text=True
    ).strip()
    args.output.mkdir(parents=True)
    identity = 'user-selected single-person fixed ROI; no automatic identity tracking'
    if args.detect:
        args.bbox = detect_box(args, p)
        identity = 'ViTDet largest person per probe frame, union of 8 probes padded 10%; no identity tracking'
        print(f'Detected person box {[round(v) for v in args.bbox]}', flush=True)
    model, cfg = load_sam_3d_body(str(args.checkpoint), device='cuda', mhr_path=str(args.mhr))
    estimator = SAM3DBodyEstimator(model, cfg)
    indices = [mhr_names.index(f'{args.side}-{part}') for part in ('shoulder', 'elbow', 'wrist')]
    video = cv2.VideoCapture(str(args.video))
    if not video.isOpened():
        p.error('Cannot decode input video')
    image_size = [int(video.get(cv2.CAP_PROP_FRAME_WIDTH)), int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))]
    records = []
    last_t = -1
    grid = SampleGrid(args.start, args.sample_hz)
    frame_index = 0
    started = time.perf_counter()
    try:
        while True:
            ok, bgr = video.read()
            if not ok:
                break
            t = float(video.get(cv2.CAP_PROP_POS_MSEC)) / 1000
            if not np.isfinite(t) or t <= last_t:
                raise ValueError(
                    'Decoder did not preserve strictly increasing timestamps; transcode/inspect video first'
                )
            last_t = t
            if t > args.start + args.seconds:
                break
            if not grid.take(t):
                frame_index += 1
                continue
            h, w = bgr.shape[:2]
            x1, y1, x2, y2 = args.bbox
            if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                raise ValueError('Bounding box outside decoded image')
            output = estimator.process_one_image(
                cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), bboxes=np.array([args.bbox]), inference_type='body'
            )
            record = {'t': t, 'frame_index': frame_index, 'arm': None}
            if len(output) == 1:
                pred = output[0]
                # Preserve every numeric raw output, without unsafe pickle files.
                numeric = {k: v for k, v in pred.items() if isinstance(v, (np.ndarray, float, int))}
                np.savez_compressed(args.output / f'raw-{frame_index:06d}.npz', **numeric)
                keypoints = np.asarray(pred['pred_keypoints_3d'])
                record['arm'] = keypoints[indices].tolist()
                record['body'] = keypoints[
                    : len(mhr_names)
                ].tolist()  # every named keypoint, for full-body retargeting
                xy = np.asarray(pred['pred_keypoints_2d'])[indices]
                for a, b in zip(xy[:-1], xy[1:]):
                    if np.all(np.isfinite([a, b])):
                        cv2.line(
                            bgr,
                            tuple(np.round(a).astype(int)),
                            tuple(np.round(b).astype(int)),
                            (100, 255, 130),
                            3,
                        )
                record['arm_pixels'] = xy.tolist()
            cv2.imwrite(str(args.output / f'overlay-{frame_index:06d}.jpg'), bgr)
            records.append(record)
            frame_index += 1
            print(f'{len(records)} frames, source t={t:.3f}s', flush=True)
    finally:
        video.release()
    bundle = {
        'schema': 'homunculus.observations.v1',
        'basis': basis.tolist(),
        'frames': records,
        'body_keypoints': list(mhr_names),
        'provenance': {
            'kind': 'sam3d',
            'model': 'SAM 3D Body supplied checkpoint',
            'revision': revision,
            'checkpoint_sha256': sha256(args.checkpoint),
            'mhr_sha256': sha256(args.mhr),
            'video_sha256': sha256(args.video),
            'side': args.side,
            'bbox': args.bbox,
            'image_size_px': image_size,
            'identity': identity,
            'native_units': 'unverified; directions only',
            'camera': 'default FOV; not metric calibration',
            'requested_sample_hz': args.sample_hz,
            'achieved_sample_hz': (
                (len(records) - 1) / (records[-1]['t'] - records[0]['t']) if len(records) > 1 else 0
            ),
            'wall_s': time.perf_counter() - started,
            'torch': torch.__version__,
            'peak_cuda_allocated_bytes': torch.cuda.max_memory_allocated(),
        },
    }
    (args.output / 'capture.json').write_text(json.dumps(bundle, indent=2, allow_nan=False), encoding='utf-8')
    # Keep raw output even if the motion is outside the first puppet's supported scope.
    try:
        if args.spatial:
            bundle['retargeting'] = 'spatial_arm_v1'
            (args.output / 'capture.json').write_text(
                json.dumps(bundle, indent=2, allow_nan=False), encoding='utf-8'
            )
            report = {'status': 'REQUIRES_LOCAL_SPATIAL_VALIDATION', 'frames': len(records)}
            (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print(json.dumps(report))
            return
        prepared = prepare(bundle)
        report = {'status': 'READY_FOR_REVIEW', 'diagnostics': prepared.metadata}
    except (ValueError, KeyError, TypeError) as exc:
        report = {'status': 'NEEDS_REVIEW', 'reason': str(exc)}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
