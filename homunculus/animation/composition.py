"""Compose local joint tracks after retargeting, before preview and GLB export.

Excluded mask tracks are omitted, never filled with rest keys. Layering preserves
base tracks outside the selection. Parent motion still affects child world poses.
"""

import copy
import math
import numpy as np

from homunculus.retarget.body import BODY_BONES


def validate_options(options):
    if not isinstance(options, dict) or set(options) - {'mode', 'bones', 'rootMotion', 'blend', 'source'}:
        raise ValueError('Invalid composition fields')
    mode = options.get('mode')
    if mode not in ('mask', 'layer', 'sequence'):
        raise ValueError('Choose mask, layer or sequence')
    bones = options.get('bones')
    if (
        not isinstance(bones, list)
        or not all(isinstance(b, str) and b in BODY_BONES for b in bones)
        or len(bones) != len(set(bones))
    ):
        raise ValueError('Targets must be unique supported bone names')
    root = options.get('rootMotion', False)
    if type(root) is not bool or not (bones or root):
        raise ValueError('Select at least one joint or pelvis translation')
    blend = options.get('blend', 0.25)
    if (
        isinstance(blend, bool)
        or not isinstance(blend, (int, float))
        or not math.isfinite(blend)
        or not 0 <= blend <= 5
    ):
        raise ValueError('Transition must be between 0 and 5 seconds')
    return mode, bones, root, blend


def slerp(a, b, u):
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    if dot > 0.9995:
        q = a + u * (b - a)
    else:
        theta = np.arccos(np.clip(dot, -1, 1))
        q = (np.sin((1 - u) * theta) * a + np.sin(u * theta) * b) / np.sin(theta)
    return (q / np.linalg.norm(q)).tolist()


def sample(track, t):
    frames = track['frames']
    times = [f['t'] for f in frames]
    i = min(max(int(np.searchsorted(times, t, side='right')) - 1, 0), len(frames) - 2)
    a, b = frames[i : i + 2]
    u = float(np.clip((t - a['t']) / (b['t'] - a['t']), 0, 1))
    out = {'rotations_xyzw': [slerp(x, y, u) for x, y in zip(a['rotations_xyzw'], b['rotations_xyzw'])]}
    if track.get('translation_node') is not None:
        out['translation'] = (
            (1 - u) * np.asarray(a['translation']) + u * np.asarray(b['translation'])
        ).tolist()
    return out


def compose(base, options, secondary=None):
    mode, bones, root, blend = validate_options(options)
    if set(bones) - set(base['bones']):
        raise ValueError('Selected joints are not present in the current capture')
    if root and base.get('translation_node') is None:
        raise ValueError('Current capture has no pelvis translation track')
    out = copy.deepcopy(base)
    selected = [base['bones'].index(b) for b in bones]
    if mode == 'mask':
        out['bones'] = bones[:]
        out['nodes'] = [base['nodes'][i] for i in selected]
        for frame in out['frames']:
            frame['rotations_xyzw'] = [frame['rotations_xyzw'][i] for i in selected]
            if not root:
                frame.pop('translation', None)
        if not root:
            out.pop('translation_node', None)
            out.pop('translation_bone', None)
    else:
        if secondary is None:
            raise ValueError('Attach a second captured animation first')
        if set(bones) - set(secondary['bones']):
            raise ValueError('Second capture is missing selected joints')
        if root and secondary.get('translation_node') is None:
            raise ValueError('Second capture has no pelvis translation')
        other = [secondary['bones'].index(b) for b in bones]
        da, db = base['frames'][-1]['t'], secondary['frames'][-1]['t']
        if mode == 'sequence' and blend >= min(da, db):
            raise ValueError('Transition must be shorter than both clips')
        duration = da if mode == 'layer' else da + db - blend
        if duration > 60:
            raise ValueError('Combined animation exceeds 60 seconds')
        if mode == 'layer':
            times = [f['t'] for f in base['frames']]
        else:
            # Include exact transition boundaries as well as the regular 50 Hz samples.
            times = sorted(
                set(np.linspace(0, duration, math.ceil(duration * 50) + 1).tolist() + [da - blend, da])
            )
        frames = []
        for t in times:
            a = sample(base, t)
            if mode == 'layer':
                b, weight = sample(secondary, t / da * db), 1.0
            else:
                b = sample(secondary, t - (da - blend))
                weight = float(np.clip((t - (da - blend)) / blend, 0, 1)) if blend else float(t >= da)
            for i, j in zip(selected, other):
                a['rotations_xyzw'][i] = slerp(a['rotations_xyzw'][i], b['rotations_xyzw'][j], weight)
            if root:
                a['translation'] = (
                    (1 - weight) * np.asarray(a['translation']) + weight * np.asarray(b['translation'])
                ).tolist()
            a['t'] = float(t)
            frames.append(a)
        out['frames'] = frames
    out['composition'] = {k: copy.deepcopy(v) for k, v in options.items() if k != 'source'}
    out['note'] = (
        'Joint-local composition. Unselected layer tracks preserve the base; masked tracks are omitted. No world-space pinning or contact solver.'
    )
    return out
