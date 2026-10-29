"""Per-range edits over source time (capture['timing'], homunculus.timing.v1).

Segments override clip-wide physics gains inside [start, end] (source seconds), easing in
and out over `blend` seconds along `curve`. Speed segments are planned (docs/PLAN.md).
"""
import copy
from homunculus.contracts import number, object_value

SCHEMA = 'homunculus.timing.v1'
CURVES = {
    'step': lambda u: float(u >= 1),
    'linear': lambda u: u,
    'smoothstep': lambda u: u*u*(3-2*u),
    'smootherstep': lambda u: u*u*u*(u*(6*u-15)+10),
    'ease_in': lambda u: u**3,
    'ease_out': lambda u: 1-(1-u)**3,
    'ease_in_out': lambda u: 4*u**3 if u < .5 else 1-(-2*u+2)**3/2,
    'expo_in': lambda u: 0. if u <= 0 else 2**(10*u-10),
    'expo_out': lambda u: 1. if u >= 1 else 1-2**(-10*u),
}
GAINS = {'strength': (.1, 2), 'damping': (.2, 3)}
FIELDS = {'id', 'start', 'end', 'blend', 'curve', *GAINS}
MAX_SEGMENTS = 64


def empty():
    return {'schema': SCHEMA, 'segments': []}


def validate(document, source_duration):
    """Checked copy, segments sorted by start; raises ValueError naming the segment."""
    object_value(document, 'timing')
    if document.get('schema') != SCHEMA or set(document) != {'schema', 'segments'}: raise ValueError(f'timing must be {SCHEMA} with segments only')
    segments = document['segments']
    if not isinstance(segments, list) or len(segments) > MAX_SEGMENTS: raise ValueError(f'timing allows at most {MAX_SEGMENTS} segments')
    clean = []
    for s in segments:
        object_value(s, 'segment')
        name = s.get('id')
        if not isinstance(name, str) or not 1 <= len(name) <= 40: raise ValueError('Segment id must be 1–40 characters')
        if set(s) - FIELDS: raise ValueError(f'{name}: unknown fields')
        if not set(s) & set(GAINS): raise ValueError(f'{name}: set strength and/or damping')
        start, end = number(s.get('start'), f'{name}.start'), number(s.get('end'), f'{name}.end')
        if not 0 <= start < end <= source_duration + 1e-6: raise ValueError(f'{name}: range must lie within the 0–{source_duration:.2f} s clip')
        blend = number(s.get('blend', 0), f'{name}.blend')
        if not 0 <= blend <= (end-start)/2: raise ValueError(f'{name}: blend must be 0 to half the segment length')
        if s.get('curve', 'smoothstep') not in CURVES: raise ValueError(f'{name}: curve must be one of '+', '.join(CURVES))
        for key, (lo, hi) in GAINS.items():
            if key in s and not lo <= number(s[key], f'{name}.{key}') <= hi: raise ValueError(f'{name}: {key} must be within [{lo}, {hi}]')
        clean.append({**copy.deepcopy(s), 'blend': blend, 'curve': s.get('curve', 'smoothstep')})
    clean.sort(key=lambda s: s['start'])
    if len({s['id'] for s in clean}) != len(clean): raise ValueError('Segment ids must be unique')
    for a, b in zip(clean, clean[1:]):
        if b['start'] < a['end'] - 1e-9: raise ValueError(f"{a['id']} and {b['id']} overlap")
    return {'schema': SCHEMA, 'segments': clean}


def weight(segment, s):
    """0 outside, 1 inside, eased over the blend at each end."""
    if not segment['start'] <= s <= segment['end']: return 0.
    b = segment['blend']
    if b <= 0: return 1.
    edge = min(s-segment['start'], segment['end']-s)
    return float(CURVES[segment['curve']](min(edge/b, 1.)))


def gains(document, s, strength, damping):
    """(strength, damping) at source time s; clip-wide values outside segments."""
    values = {'strength': strength, 'damping': damping}
    for segment in document['segments'] if document else ():
        if segment['start'] <= s <= segment['end']:
            w = weight(segment, s)
            for key in GAINS:
                if key in segment: values[key] = segment[key] if w >= 1 else values[key]+w*(segment[key]-values[key])
            break
    return values['strength'], values['damping']


def apply(document, operation, source_duration):
    """set (insert/replace by id, trimming nothing) or clear (by ids, or all)."""
    doc = copy.deepcopy(document) if document else empty()
    op = operation.get('operation')
    if op == 'set':
        segment = operation['segment']
        doc['segments'] = [s for s in doc['segments'] if s['id'] != segment['id']] + [segment]
    elif op == 'clear':
        ids = operation.get('ids')
        doc['segments'] = [] if ids is None else [s for s in doc['segments'] if s['id'] not in ids]
    else: raise ValueError('Segment operation must be set or clear')
    return validate(doc, source_duration)


def describe(document):
    return [{k: s[k] for k in ('id', 'start', 'end', 'blend', 'curve', *GAINS) if k in s} for s in (document or empty())['segments']]
